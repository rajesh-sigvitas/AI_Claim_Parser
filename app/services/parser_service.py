"""
Parser Service.
Top-level orchestrator that coordinates detection, extraction,
normalization, and parsing to produce a ClaimDocument.
"""
from loguru import logger
import os

from app.models.document import ClaimDocument
from app.core.constants import InputType
from app.services.detector import FileTypeDetector
from app.extractor.factory import ExtractorFactory
from app.normalizer.engine import NormalizationEngine
from app.parser.engine import ParserEngine
from app.formatter.pdf_generator import PDFGenerator
from app.core.config import settings
from app.core.exceptions import MissingClaimsError, OCRFailureError

class ParserService:
    def __init__(self):
        self.detector = FileTypeDetector()
        self.extractor_factory = ExtractorFactory()
        self.normalizer = NormalizationEngine()
        self.parser_engine = ParserEngine()
        self.pdf_generator = PDFGenerator(output_dir=str(settings.OUTPUT_DIR))

    def parse(self, raw_input: bytes, filename: str, generate_pdf: bool = True) -> ClaimDocument:
        logger.info(f"Request received to parse file: {filename}")
        input_type, detection_confidence = self.detector.detect(raw_input, filename)
        logger.info(f"File type detected: {input_type.value} (confidence: {detection_confidence})")

        if input_type == InputType.USPTO_XML:
            extractor = self.extractor_factory.get_extractor(input_type)
            claims, metadata = extractor.extract(raw_input)
            doc = ClaimDocument(
                input_type=input_type, confidence_score=100.0, ocr_used=False,
                claims=claims, metadata=metadata
            )
            logger.info(f"USPTO XML extracted {len(claims)} claims.")
        else:
            doc = self._parse_with_fallbacks(raw_input, input_type, filename)

        if generate_pdf:
            doc.pdf_path = self.pdf_generator.generate(doc)
            
        logger.info(f"Parsing complete. Claims: {doc.claim_count}, Confidence: {doc.confidence_score}")
        return doc

    def _parse_with_fallbacks(self, raw_input: bytes, input_type: InputType, filename: str) -> ClaimDocument:
        errors = []
        
        # 1. Native Extraction
        try:
            logger.info("Attempting Native extraction.")
            if input_type in (InputType.TEXT_PDF, InputType.SCANNED_PDF):
                from app.extractor.pdf import PDFExtractor
                extractor = PDFExtractor()
            else:
                extractor = self.extractor_factory.get_extractor(input_type)
            
            text = extractor.extract(raw_input)
            return self._process_text(text, input_type, False)
        except Exception as e:
            logger.warning(f"Native extraction failed: {e}")
            errors.append(f"Native: {e}")

        # 2. Tesseract OCR (Fallback 1)
        if input_type in (InputType.TEXT_PDF, InputType.SCANNED_PDF):
            try:
                logger.info("Attempting Tesseract OCR extraction.")
                from app.extractor.ocr import TesseractOCRProvider
                text = TesseractOCRProvider().extract(raw_input)
                return self._process_text(text, input_type, True)
            except Exception as e:
                logger.warning(f"Tesseract OCR failed: {e}")
                errors.append(f"Tesseract: {e}")
        elif input_type == InputType.RAW_TEXT:
            pass # Tesseract not applicable to TXT

        # 3. Groq Fallback
        try:
            logger.info("Attempting Groq extraction.")
            api_key = getattr(settings, "OCR_API_KEY", os.environ.get("GROQ_API_KEY", ""))
            if not api_key:
                raise ValueError("No Groq API key available.")
                
            if input_type in (InputType.TEXT_PDF, InputType.SCANNED_PDF):
                from app.extractor.ocr import GroqOCRProvider
                text = GroqOCRProvider(api_key=api_key).extract(raw_input)
            else:
                # Text file Groq processing
                raw_text = raw_input.decode("utf-8", errors="ignore")
                text = self._groq_text_extract(raw_text, api_key)
                
            return self._process_text(text, input_type, True)
        except Exception as e:
            logger.warning(f"Groq extraction failed: {e}")
            errors.append(f"Groq: {e}")

        # If all fail
        raise MissingClaimsError(f"All extraction methods failed. Errors: {'; '.join(errors)}")

    def _groq_text_extract(self, raw_text: str, api_key: str) -> str:
        from groq import Groq
        client = Groq(api_key=api_key)
        # Using Llama 3.3 70B as per rate limit text-to-text model
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": f"Extract the patent claims from the following text exactly as they appear. Do not add conversational filler.\n\n{raw_text[:20000]}"
                }
            ],
            temperature=0,
            max_tokens=4096,
        )
        content = completion.choices[0].message.content
        if not content:
            raise ValueError("Groq text extraction returned empty.")
        return content

    def _process_text(self, text: str, input_type: InputType, ocr_used: bool) -> ClaimDocument:
        if not text or not text.strip():
            raise ValueError("Extracted text is empty.")
        normalized_text, norm_ops = self.normalizer.normalize(text)
        doc = self.parser_engine.parse(normalized_text, input_type)
        doc.ocr_used = ocr_used
        return doc

parser_service = ParserService()
