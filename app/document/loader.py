"""
Builds a :class:`PatentDocument` from an uploaded file.

The claim pipeline is reused rather than reimplemented: the claims section found here is
handed to :class:`~app.parser.engine.ParserEngine`, so claim structure -- hierarchy,
elements, indentation -- stays defined in exactly one place, and the antecedent module
keeps working unchanged on the ``ClaimDocument`` this produces.

Input handling:

* .doc/.docx/.odt/.rtf are laid out by LibreOffice first, because page and line numbers
  only exist once a document has been rendered.
* PDFs are paginated directly.  A scanned PDF has no text layer, so it is OCRed page by
  page and the OCR lines are used instead.
* Plain text has no pages; it is paginated synthetically at a fixed number of lines so
  citations still resolve.
"""
from typing import List, Optional

from loguru import logger

from app.core.constants import InputType
from app.document.models import Line, Page, PatentDocument, SectionKind
from app.document.office import convert_to_pdf, suffix_for
from app.document.paginator import paginate
from app.document.sections import detect_sections

# Lines per synthetic page for plain-text input.
_TEXT_PAGE_LINES = 50


class DocumentLoader:
    """Produces the whole-document model every report module reads."""

    def __init__(self, parse_claims: bool = True, extract_figures: bool = True):
        self.parse_claims = parse_claims
        self.extract_figures = extract_figures

    def load(self, raw_input: bytes, filename: str = "") -> PatentDocument:
        pages, pdf_bytes = self._to_pages(raw_input, filename)

        document = PatentDocument(filename=filename, pages=pages)
        document.sections = detect_sections(document.lines, document.pages)
        document.assign_sections()

        if self.parse_claims:
            document.claims = self._parse_claims(document)

        if self.extract_figures and pdf_bytes:
            from app.document.figures import extract_figures

            document.figures = extract_figures(pdf_bytes, document)

        document.metadata.setdefault("page_count", document.page_count)
        document.metadata.setdefault("line_count", len(document.lines))
        logger.info(f"Loaded {document!r}")
        return document

    # -- input handling -----------------------------------------------------

    def _to_pages(self, raw_input: bytes, filename: str):
        """Returns the rendered pages and, when there is one, the PDF they came from."""
        if not raw_input:
            raise ValueError("Cannot load an empty document.")

        suffix = suffix_for(filename)
        if suffix:
            pdf_bytes = convert_to_pdf(raw_input, suffix)
            return paginate(pdf_bytes), pdf_bytes

        if raw_input[:5] == b"%PDF-":
            pages = paginate(raw_input)
            if not any(page.lines for page in pages):
                logger.info("PDF has no text layer; falling back to OCR for pagination.")
                pages = self._ocr_pages(raw_input, pages)
            return pages, raw_input

        # Anything else is treated as text.  A .doc that magic could not identify would
        # have been caught by suffix_for above.
        text = raw_input.decode("utf-8", errors="ignore")
        return self._text_pages(text), None

    @staticmethod
    def _text_pages(text: str) -> List[Page]:
        """Synthetic pagination so plain text still produces resolvable citations."""
        pages: List[Page] = []
        page: Optional[Page] = None

        for position, raw_line in enumerate(text.splitlines()):
            if position % _TEXT_PAGE_LINES == 0:
                page = Page(number=len(pages) + 1, width=612.0, height=792.0)
                pages.append(page)
            page.lines.append(Line(
                page=page.number,
                number=len(page.lines) + 1,
                text=raw_line.rstrip(),
            ))

        # Blank lines are kept for numbering but carry no text; drop trailing empties.
        for page in pages:
            while page.lines and not page.lines[-1].text.strip():
                page.lines.pop()
        return [page for page in pages if page.lines]

    @staticmethod
    def _ocr_pages(pdf_bytes: bytes, pages: List[Page]) -> List[Page]:
        """Fills empty pages with OCRed lines, keeping the page geometry already read."""
        import fitz
        import pytesseract
        from PIL import Image
        import io

        source = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            for page in pages:
                if page.lines:
                    continue
                pixmap = source[page.number - 1].get_pixmap(dpi=200)
                image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                try:
                    text = pytesseract.image_to_string(image)
                except Exception as error:                       # pragma: no cover
                    logger.warning(f"OCR failed on page {page.number}: {error}")
                    continue
                for number, raw_line in enumerate(text.splitlines(), start=1):
                    if raw_line.strip():
                        page.lines.append(Line(
                            page=page.number, number=number, text=raw_line.strip()
                        ))
        finally:
            source.close()
        return pages

    # -- claims -------------------------------------------------------------

    def _parse_claims(self, document: PatentDocument):
        """
        Runs the existing claim parser over the claims section.

        Falls back to the whole document when no claims heading was found, which is what
        a claims-only upload looks like.
        """
        from app.normalizer.engine import NormalizationEngine
        from app.parser.engine import ParserEngine

        section = document.section(SectionKind.CLAIMS)
        if section is not None:
            claim_lines = [
                line.text for line in document.lines[section.start_index:section.end_index]
                if not line.is_running_head
            ]
            claim_text = "\n".join(claim_lines)
        else:
            claim_text = "\n".join(
                line.text for line in document.lines if not line.is_running_head
            )

        if not claim_text.strip():
            return None

        try:
            normalized, _operations = NormalizationEngine().normalize(claim_text)
            claim_document = ParserEngine().parse(normalized, InputType.RAW_TEXT)
        except Exception as error:
            logger.warning(f"Claim parsing failed for {document.filename}: {error}")
            return None

        self._attach_claim_lines(claim_document, document, section)
        return claim_document

    @staticmethod
    def _attach_claim_lines(claim_document, document: PatentDocument, section) -> None:
        """
        Records the line each claim starts on, so claim findings can cite a page too.

        The match is on the claim number at the start of a line, which is how the claim
        splitter found the claim in the first place.
        """
        import re

        if claim_document is None:
            return

        start = section.start_index if section else 0
        end = section.end_index if section else len(document.lines)
        window = document.lines[start:end]

        for claim in claim_document.claims:
            # "12. ", "12.[13.] " -- the renumbering bracket sits between the number and
            # the claim text, so it has to be allowed for or amended claims lose their page.
            pattern = re.compile(
                rf"^\s*{claim.number}\s*[.)]\s*(?:\[\s*\d+\s*\.?\s*\]\s*)?\S"
            )
            for line in window:
                if line.is_running_head:
                    continue
                if pattern.match(line.text):
                    claim.metadata["line_index"] = line.index
                    claim.metadata["page"] = line.page
                    claim.metadata["line"] = line.number
                    break


document_loader = DocumentLoader()
