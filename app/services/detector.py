import magic
from typing import Tuple
from loguru import logger
from app.core.constants import InputType
from app.core.exceptions import UnsupportedFileTypeError

class FileTypeDetector:
    """
    Dedicated service for identifying the input document type.
    Analyzes file extensions, MIME types, and content heuristics.
    Never relies solely on file extensions.
    """
    
    def detect(self, raw_input: bytes, filename: str) -> Tuple[InputType, float]:
        """
        Determines the InputType and returns a confidence score (0-100).
        """
        if not raw_input:
            raise ValueError("Cannot detect type of an empty file.")
            
        # 1. MIME Type Validation
        mime_type = magic.from_buffer(raw_input, mime=True)
        logger.debug(f"Detected MIME type: {mime_type} for {filename}")
        
        # 2. PDF Detection
        if mime_type == "application/pdf":
            return self._detect_pdf_type(raw_input)
            
        # 3. XML Detection
        if mime_type in ("application/xml", "text/xml") or filename.lower().endswith(".xml"):
            # Check for USPTO tags vs Generic XML
            if b"<us-claim-statement>" in raw_input or b"<us-patent-grant" in raw_input or b"<claims>" in raw_input:
                return InputType.USPTO_XML, 100.0
            return InputType.OTHER_XML, 90.0
            
        # 4. Text Detection
        if mime_type == "text/plain":
            return InputType.RAW_TEXT, 100.0
            
        # Fallback heuristic
        if filename.lower().endswith(".txt"):
            return InputType.RAW_TEXT, 85.0
            
        raise UnsupportedFileTypeError(f"Unsupported file type: {mime_type}")

    def _detect_pdf_type(self, raw_input: bytes) -> Tuple[InputType, float]:
        """
        Determines if a PDF is Text-based or Scanned (requires OCR).
        Reads the first few pages and checks for selectable text.
        """
        try:
            import fitz # PyMuPDF
            doc = fitz.open(stream=raw_input, filetype="pdf")
            
            # Check up to 3 pages
            pages_to_check = min(len(doc), 3)
            total_text_length = 0
            
            for i in range(pages_to_check):
                page = doc.load_page(i)
                text = page.get_text()
                total_text_length += len(text.strip())
                
            doc.close()
            
            # Threshold for text vs scanned
            if total_text_length > 100:
                logger.debug(f"PDF detected as TEXT_PDF (text length: {total_text_length})")
                return InputType.TEXT_PDF, 95.0
            else:
                logger.debug(f"PDF detected as SCANNED_PDF (text length: {total_text_length})")
                return InputType.SCANNED_PDF, 90.0
                
        except ImportError:
            logger.warning("PyMuPDF not installed, falling back to pdfplumber for detection.")
            return self._detect_pdf_type_plumber(raw_input)
        except Exception as e:
            logger.error(f"Error detecting PDF type: {e}")
            # Safe fallback if detection fails
            return InputType.TEXT_PDF, 50.0

    def _detect_pdf_type_plumber(self, raw_input: bytes) -> Tuple[InputType, float]:
        import pdfplumber
        import io
        try:
            with pdfplumber.open(io.BytesIO(raw_input)) as pdf:
                pages_to_check = min(len(pdf.pages), 3)
                total_text_length = 0
                for i in range(pages_to_check):
                    text = pdf.pages[i].extract_text()
                    if text:
                        total_text_length += len(text.strip())
                        
                if total_text_length > 100:
                    return InputType.TEXT_PDF, 95.0
                return InputType.SCANNED_PDF, 90.0
        except Exception as e:
            logger.error(f"pdfplumber detection failed: {e}")
            return InputType.TEXT_PDF, 50.0
