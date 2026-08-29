import io
from loguru import logger
from app.core.exceptions import UnsupportedFileTypeError

try:
    from docx import Document
except ImportError:
    Document = None

class WordExtractor:
    """
    Extracts text from Microsoft Word documents.
    Refactored to use python-docx to avoid LibreOffice dependency for Render's Native Python environment.
    Note: .doc (legacy) files are not natively supported by python-docx, only .docx.
    """
    
    def extract(self, raw_input: bytes) -> str:
        """
        Extracts raw text from a .docx document.
        """
        if Document is None:
            raise UnsupportedFileTypeError("python-docx is not installed. Add it to requirements.txt")

        try:
            logger.info("Extracting Word document using python-docx...")
            doc = Document(io.BytesIO(raw_input))
            
            text_lines = []
            for para in doc.paragraphs:
                # Add simulated indentation based on paragraph format to help the parser engine
                indent = para.paragraph_format.left_indent
                prefix = ""
                if indent and indent.pt and indent.pt > 0:
                    # roughly 1 space per 5 points of indent
                    prefix = " " * int(indent.pt / 5)
                
                if para.text.strip():
                    text_lines.append(prefix + para.text)
                    
            text_output = "\n".join(text_lines)
            
            if not text_output.strip():
                logger.warning("python-docx extracted empty text.")
                
            return text_output
            
        except Exception as e:
            logger.error(f"Failed to extract text from Word document using python-docx: {e}")
            raise UnsupportedFileTypeError(f"Failed to extract text from Word document. Error: {e}")