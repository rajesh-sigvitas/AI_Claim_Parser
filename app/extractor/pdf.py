"""
PDF Extractor.
Extracts selectable text from text-based PDFs using PyMuPDF (fitz).
Falls back to pdfplumber if PyMuPDF is unavailable.
"""
from loguru import logger


class PDFExtractor:
    """
    Extracts selectable text from PDF files.
    Does NOT invoke OCR — that is handled by OCRExtractor.
    """

    def extract(self, raw_input: bytes) -> str:
        """
        Extracts text from a PDF byte stream.
        Preserves line breaks, whitespace, and ordering.
        """
        if not raw_input or len(raw_input) < 10:
            raise ValueError("Invalid PDF: file is empty or too small.")

        text = self._try_pypdf(raw_input)
        if text and text.strip():
            return text

        raise ValueError("PDF extraction failed: no selectable text found. Document may be scanned.")

    @staticmethod
    def _try_pypdf(raw_input: bytes) -> str:
        """Attempts extraction using pypdf."""
        try:
            import pypdf
            import io
            reader = pypdf.PdfReader(io.BytesIO(raw_input))
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n".join(pages)
        except ImportError:
            logger.warning("pypdf not installed.")
            return ""
        except Exception as e:
            logger.warning(f"pypdf extraction failed: {e}")
            return ""
