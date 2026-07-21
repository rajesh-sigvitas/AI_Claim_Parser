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

        text = self._try_pymupdf(raw_input)
        if text and text.strip():
            return text

        text = self._try_pdfplumber(raw_input)
        if text and text.strip():
            return text

        raise ValueError("PDF extraction failed: no selectable text found. Document may be scanned.")

    @staticmethod
    def _try_pymupdf(raw_input: bytes) -> str:
        """Attempts extraction using PyMuPDF (fitz)."""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=raw_input, filetype="pdf")
            pages = []
            for page in doc:
                pages.append(page.get_text())
            doc.close()
            return "\n".join(pages)
        except ImportError:
            logger.warning("PyMuPDF not installed. Falling back to pdfplumber.")
            return ""
        except Exception as e:
            logger.warning(f"PyMuPDF extraction failed: {e}")
            return ""

    @staticmethod
    def _try_pdfplumber(raw_input: bytes) -> str:
        """Attempts extraction using pdfplumber."""
        try:
            import pdfplumber
            import io
            pdf = pdfplumber.open(io.BytesIO(raw_input))
            pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            pdf.close()
            return "\n".join(pages)
        except ImportError:
            logger.warning("pdfplumber not installed.")
            return ""
        except Exception as e:
            logger.warning(f"pdfplumber extraction failed: {e}")
            return ""
