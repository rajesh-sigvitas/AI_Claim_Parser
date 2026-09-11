"""
Turns a rendered PDF into pages of numbered lines.

Line numbering follows what a reader sees: lines are taken top to bottom, left to right,
and numbered from 1 on each page, running header included -- that is how the citations in
a Claim Master report line up with the printed document.

Two things are worth knowing about the geometry:

* PyMuPDF returns text in *block* order, which is not always visual order for multi-column
  or floated content, so lines are re-sorted by their y coordinate (with a tolerance, since
  glyphs on one visual line rarely share an exact baseline) and then by x.
* Running heads ("Atty Docket No. 50OR570" on all 53 pages) are numbered like any other
  line, because they occupy a line on the page, but they are flagged so prose analysis can
  skip them instead of reporting the docket number 53 times.
"""
from collections import Counter
from typing import List, Tuple

from loguru import logger

from app.document.models import Line, Page

# Two spans belong to the same visual line when their tops differ by less than this.
_Y_TOLERANCE = 3.0

# A repeated line is a running head when it appears on at least this share of pages.
_RUNNING_HEAD_RATIO = 0.6
_RUNNING_HEAD_MIN_PAGES = 3

# Fraction of the page height that counts as the header / footer band.
_HEADER_BAND = 0.10
_FOOTER_BAND = 0.90


def paginate(pdf_bytes: bytes) -> List[Page]:
    """Extracts every page of a PDF as a :class:`Page` of numbered :class:`Line` objects."""
    import fitz

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages: List[Page] = []

    try:
        for page_index in range(len(document)):
            source = document[page_index]
            page = Page(
                number=page_index + 1,
                width=float(source.rect.width),
                height=float(source.rect.height),
            )

            raw_lines = _extract_lines(source)
            for line_number, (text, bbox) in enumerate(raw_lines, start=1):
                page.lines.append(
                    Line(page=page.number, number=line_number, text=text, bbox=bbox)
                )

            page.image_count, page.image_area_ratio = _image_coverage(source)
            page.drawing_count = len(source.get_drawings())
            pages.append(page)
    finally:
        document.close()

    _flag_running_heads(pages)
    logger.info(f"Paginated document: {len(pages)} pages, {sum(len(p.lines) for p in pages)} lines.")
    return pages


def _extract_lines(source) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    """Every text line on one page, in reading order."""
    collected: List[Tuple[float, float, str, Tuple[float, float, float, float]]] = []

    for block in source.get_text("dict").get("blocks", []):
        if block.get("type") != 0:          # 1 is an image block
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            if not text.strip():
                continue
            bbox = tuple(float(value) for value in line.get("bbox", (0, 0, 0, 0)))
            collected.append((bbox[1], bbox[0], text.rstrip(), bbox))

    collected.sort(key=lambda item: (round(item[0] / _Y_TOLERANCE), item[1]))

    # Fragments that share a visual line are joined, so a line number means one printed
    # line even when the PDF splits it across spans or blocks.
    merged: List[Tuple[str, Tuple[float, float, float, float]]] = []
    previous_top = None
    for top, _left, text, bbox in collected:
        if previous_top is not None and abs(top - previous_top) <= _Y_TOLERANCE:
            last_text, last_bbox = merged[-1]
            merged[-1] = (
                f"{last_text} {text.strip()}".strip(),
                (
                    min(last_bbox[0], bbox[0]), min(last_bbox[1], bbox[1]),
                    max(last_bbox[2], bbox[2]), max(last_bbox[3], bbox[3]),
                ),
            )
        else:
            merged.append((text.strip(), bbox))
            previous_top = top

    return merged


def _image_coverage(source) -> Tuple[int, float]:
    """How much of the page is covered by raster images -- the drawing-sheet signal."""
    try:
        images = source.get_images(full=True)
    except Exception:                      # pragma: no cover - defensive, fitz version drift
        return 0, 0.0

    if not images:
        return 0, 0.0

    page_area = float(source.rect.width * source.rect.height) or 1.0
    covered = 0.0
    for image in images:
        try:
            for rect in source.get_image_rects(image[0]):
                covered += float(rect.width * rect.height)
        except Exception:
            continue

    return len(images), min(covered / page_area, 1.0)


def _flag_running_heads(pages: List[Page]) -> None:
    """
    Marks the repeated header/footer lines.

    They stay in the line numbering -- a reader counting lines on the page counts them --
    but prose analysis skips them, otherwise the docket number on every page turns into
    dozens of identical findings.
    """
    if len(pages) < _RUNNING_HEAD_MIN_PAGES:
        return

    banded: Counter = Counter()
    for page in pages:
        if not page.height:
            continue
        for line in page.lines:
            if _in_margin_band(line, page):
                banded[_normalise(line.text)] += 1

    threshold = max(_RUNNING_HEAD_MIN_PAGES, int(len(pages) * _RUNNING_HEAD_RATIO))
    repeated = {text for text, count in banded.items() if count >= threshold and text}

    for page in pages:
        for line in page.lines:
            if not _in_margin_band(line, page):
                continue
            key = _normalise(line.text)
            if key in repeated or _is_page_number(line.text):
                line.is_running_head = True


def _in_margin_band(line: Line, page: Page) -> bool:
    if not page.height:
        return False
    top = line.bbox[1] / page.height
    return top <= _HEADER_BAND or top >= _FOOTER_BAND


def _normalise(text: str) -> str:
    """Page-varying digits are dropped so 'Page 3 of 53' matches 'Page 4 of 53'."""
    import re

    return re.sub(r"\d+", "#", text.strip().lower())


def _is_page_number(text: str) -> bool:
    stripped = text.strip()
    return stripped.isdigit() and len(stripped) <= 4
