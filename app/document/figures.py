"""
Drawing sheets: their figure labels, the part numbers printed on them, and sheet warnings.

Section VI of the report compares the part numbers on the drawings against the ones named
in the specification, so the numbers have to be read off the sheets first.  Two sources
are used, in order:

1. The PDF text layer.  Drawings exported from CAD or Visio keep their labels as text, and
   reading them is exact -- including the font size, which is what the "Fonts may be too
   small" warning needs (37 CFR 1.84(p)(3) requires characters at least 0.32 cm high,
   about 9pt at full size).
2. OCR of a rendered image of the sheet, when the sheet is a scan or the text layer is
   empty.  This is inherently approximate, which is why the report footnotes section VI as
   depending on what can be extracted from the figures.

Part numbers use the draftsman's forms: ``104``, ``104-1``, ``104a``.  A bare number is
only taken as a part number when it is short and stands alone -- otherwise every dimension
and angle on the sheet would be reported as a part.
"""
import io
import re
from typing import List, Optional, Tuple

from loguru import logger

from app.document.models import Figure, FigurePart, Page, PatentDocument
from app.document.sections import is_drawing_sheet

# 104, 104-1, 104a, 1042 -- two to four digits with an optional suffix.
PART_NUMBER_PATTERN = re.compile(r"\b(\d{2,4})\s*[-‐-―]?\s*([a-dA-D]|\d)?\b")

FIGURE_LABEL_PATTERN = re.compile(r"\bFIG(?:URE)?S?\.?\s*(\d+[A-Za-z]?(?:\s*[-–]\s*\d*[A-Za-z]?)?)", re.I)

# 37 CFR 1.84(p)(3): text on a drawing must not be smaller than this.
MIN_DRAWING_FONT_PT = 9.5

# OCR below this confidence is noise on a line drawing.
_MIN_OCR_CONFIDENCE = 40.0

_OCR_DPI = 300


def extract_figures(pdf_bytes: bytes, document: PatentDocument) -> List[Figure]:
    """Reads every drawing sheet in the document."""
    sheets = [page for page in document.pages if is_drawing_sheet(page)]
    if not sheets:
        return []

    import fitz

    source = fitz.open(stream=pdf_bytes, filetype="pdf")
    figures: List[Figure] = []
    try:
        for sheet_number, page in enumerate(sheets, start=1):
            figure = Figure(sheet=sheet_number, page=page.number)
            figure.labels = _labels_for(page)

            parts, smallest_font = _parts_from_text_layer(source[page.number - 1])
            if not parts:
                parts = _parts_from_ocr(source[page.number - 1])

            figure.parts = _deduplicate(parts)
            if smallest_font and smallest_font < MIN_DRAWING_FONT_PT:
                figure.warnings.append(f"Fonts may be too small: {smallest_font:g}pt.")

            figures.append(figure)
    finally:
        source.close()

    logger.info(f"Read {len(figures)} drawing sheets.")
    return figures


def _labels_for(page: Page) -> List[str]:
    """The "FIG. 1A" captions printed on a sheet."""
    found: List[str] = []
    for match in FIGURE_LABEL_PATTERN.finditer(page.text):
        label = re.sub(r"\s+", "", match.group(0).upper()).replace("FIGURE", "FIG.")
        if not label.startswith("FIG."):
            label = label.replace("FIG", "FIG.")
        if label not in found:
            found.append(label)
    return found


def _parts_from_text_layer(source) -> Tuple[List[FigurePart], Optional[float]]:
    """Part numbers and the smallest font size found in the sheet's text layer."""
    parts: List[FigurePart] = []
    smallest: Optional[float] = None

    for block in source.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                size = float(span.get("size", 0.0) or 0.0)
                if size and (smallest is None or size < smallest):
                    smallest = round(size, 1)

                number = _as_part_number(text)
                if number:
                    parts.append(FigurePart(
                        number=number,
                        confidence=100.0,
                        bbox=tuple(float(v) for v in span.get("bbox", (0, 0, 0, 0))),
                    ))

    return parts, smallest


def _parts_from_ocr(source) -> List[FigurePart]:
    """Reads part numbers off a rendered image of the sheet."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:                                   # pragma: no cover
        logger.warning("pytesseract/Pillow unavailable; figure part numbers not read.")
        return []

    try:
        pixmap = source.get_pixmap(dpi=_OCR_DPI)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        data = pytesseract.image_to_data(
            image, output_type=pytesseract.Output.DICT,
            config="--psm 11",                            # sparse text, as on a drawing
        )
    except Exception as error:
        logger.warning(f"Figure OCR failed: {error}")
        return []

    parts: List[FigurePart] = []
    scale = 72.0 / _OCR_DPI
    for index, text in enumerate(data.get("text", [])):
        text = (text or "").strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (KeyError, ValueError, TypeError):
            confidence = 0.0
        if confidence < _MIN_OCR_CONFIDENCE:
            continue

        number = _as_part_number(text)
        if not number:
            continue

        left, top = data["left"][index] * scale, data["top"][index] * scale
        width, height = data["width"][index] * scale, data["height"][index] * scale
        parts.append(FigurePart(
            number=number, confidence=confidence,
            bbox=(left, top, left + width, top + height),
        ))

    return parts


def _as_part_number(text: str) -> Optional[str]:
    """
    The part number a label holds, or None when the label is not one.

    The label has to *be* the number: "104-1" is a part, "300mm" and "FIG. 3" are not.
    """
    cleaned = text.strip().strip("().,;:")
    if not cleaned or len(cleaned) > 8:
        return None
    if re.fullmatch(r"\d{2,4}", cleaned):
        return cleaned

    match = re.fullmatch(r"(\d{2,4})\s*[-‐-―]\s*([a-dA-D]|\d)", cleaned)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    match = re.fullmatch(r"(\d{2,4})([a-dA-D])", cleaned)
    if match:
        return f"{match.group(1)}{match.group(2).lower()}"

    return None


def _deduplicate(parts: List[FigurePart]) -> List[FigurePart]:
    """One entry per number per sheet, keeping the best-read instance."""
    best: dict = {}
    for part in parts:
        current = best.get(part.number)
        if current is None or part.confidence > current.confidence:
            best[part.number] = part
    return [best[number] for number in sorted(best, key=_sort_key)]


def _sort_key(number: str) -> Tuple[int, str]:
    match = re.match(r"(\d+)", number)
    return (int(match.group(1)) if match else 0, number)
