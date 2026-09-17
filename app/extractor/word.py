import subprocess

from loguru import logger

from app.core.exceptions import UnsupportedFileTypeError
from app.document.office import convert_to_pdf
from app.extractor.pdf import PDFExtractor


class WordExtractor:
    """
    Extracts text from Microsoft Word documents.

    The document is laid out to PDF by LibreOffice -- which preserves hierarchical
    alignment and spacing -- and read by the PDFExtractor.  Conversion goes through
    :func:`app.document.office.convert_to_pdf`, the same path the report pipeline uses,
    so tracked changes are accepted here too instead of being read as rendered markup.
    """

    def extract(self, raw_input: bytes) -> str:
        """
        Extracts raw text from a word document by converting to PDF first.
        """
        # A .docx is a zip archive; anything else is a legacy binary .doc.
        suffix = ".docx" if raw_input[:2] == b"PK" else ".doc"
        try:
            pdf_bytes = convert_to_pdf(raw_input, suffix)
        except subprocess.TimeoutExpired:
            logger.error("LibreOffice conversion timed out.")
            raise UnsupportedFileTypeError("Failed to extract text: Document conversion timed out.")
        except Exception as e:
            logger.error(f"Failed to extract text from Word document via PDF conversion: {e}")
            raise UnsupportedFileTypeError(f"Failed to extract text from Word document. Error: {e}")

        logger.info("Converted Word document to PDF; passing to PDFExtractor.")
        return PDFExtractor().extract(pdf_bytes)
