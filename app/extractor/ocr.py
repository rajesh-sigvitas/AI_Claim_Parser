"""
OCR Extractor.
Invokes an OCR provider to extract text from scanned PDFs.
Provider-independent: uses the abstract OCRProvider interface.
"""
from typing import Optional
from pathlib import Path
from abc import ABC, abstractmethod
from loguru import logger


class OCRProvider(ABC):
    """Abstract base class for OCR providers."""

    @abstractmethod
    def extract(self, pdf_bytes: bytes) -> str:
        """Extract text from scanned PDF bytes."""
        ...


from app.core.exceptions import OCRFailureError

class DummyOCRProvider(OCRProvider):
    """
    Dummy provider that extracts text using pdfplumber's basic extraction
    as a fallback when a real OCR engine like Tesseract or Llama Scout is unavailable.
    """

    def extract(self, pdf_bytes: bytes) -> str:
        import pdfplumber
        import io
        import pytesseract
        try:
            text = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    # Attempt to extract words
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        text.append(page_text)
                    else:
                        # Fallback to OCR for this page
                        try:
                            img = page.to_image(resolution=300).original
                            ocr_text = pytesseract.image_to_string(img)
                            if ocr_text and ocr_text.strip():
                                text.append(ocr_text)
                        except Exception as e:
                            logger.warning(f"Failed to OCR page {page.page_number}: {e}")
            
            if not text:
                raise OCRFailureError("Real OCR engine failed to process this completely scanned document or document is empty.")
                
            return "\n".join(text)
        except Exception as e:
            if isinstance(e, OCRFailureError):
                raise
            raise OCRFailureError(f"OCR extraction failed: {str(e)}")


class GroqOCRProvider(OCRProvider):
    """
    Provider that extracts text using Groq's Llama 3.2 Vision model.
    """
    def __init__(self, api_key: str):
        from groq import Groq
        self.client = Groq(api_key=api_key)
        self.model = "meta-llama/llama-4-scout-17b-16e-instruct"

    def extract(self, pdf_bytes: bytes) -> str:
        import pdfplumber
        import io
        import base64
        
        try:
            text = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    # Render the page to a PIL image
                    img = page.to_image(resolution=300).original
                    # Convert to JPEG bytes
                    img_byte_arr = io.BytesIO()
                    # Llama Vision supports JPEG
                    if img.mode in ("RGBA", "P"): 
                        img = img.convert("RGB")
                    img.save(img_byte_arr, format='JPEG')
                    img_bytes = img_byte_arr.getvalue()
                    
                    base64_image = base64.b64encode(img_bytes).decode('utf-8')
                    
                    # Call Groq API
                    completion = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Extract all the text from this document image exactly as it appears. Do not add any conversational filler, markdown formatting, or comments. Only return the raw extracted text."
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{base64_image}",
                                        }
                                    }
                                ]
                            }
                        ],
                        temperature=0,
                        max_tokens=4096,
                    )
                    
                    page_text = completion.choices[0].message.content
                    if page_text:
                        text.append(page_text.strip())
            
            if not text:
                raise OCRFailureError("Llama Vision failed to extract any text from this document.")
                
            return "\n".join(text)
        except Exception as e:
            if isinstance(e, OCRFailureError):
                raise
            raise OCRFailureError(f"Groq OCR extraction failed: {str(e)}")

class OCRExtractor:
    """
    Extracts text from scanned PDFs using a pluggable OCR provider.
    """

    def __init__(self, provider: Optional[OCRProvider] = None):
        from app.core.config import settings
        import os
        
        if provider:
            self.provider = provider
        else:
            api_key = getattr(settings, "OCR_API_KEY", os.environ.get("GROQ_API_KEY", ""))
            
            if settings.OCR_PROVIDER == "llama_scout" and api_key:
                self.provider = GroqOCRProvider(api_key=api_key)
            else:
                self.provider = DummyOCRProvider()

    def extract(self, raw_input: bytes) -> str:
        """
        Runs OCR on the raw PDF bytes and returns extracted text.
        """
        if not raw_input or len(raw_input) < 10:
            raise ValueError("Invalid PDF: file is empty or too small.")

        logger.info("Invoking OCR provider for scanned PDF.")
        text = self.provider.extract(raw_input)
        if not text or not text.strip():
            raise ValueError("OCR extraction produced no text.")
        return text
