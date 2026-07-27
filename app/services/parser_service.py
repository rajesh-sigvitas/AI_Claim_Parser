"""
Parser Service.
Top-level orchestrator that coordinates detection, extraction,
normalization, and parsing to produce a ClaimDocument.
"""
from loguru import logger

from app.models.document import ClaimDocument
from app.core.constants import InputType
from app.services.detector import FileTypeDetector
from app.extractor.factory import ExtractorFactory
from app.normalizer.engine import NormalizationEngine
from app.parser.engine import ParserEngine
from app.formatter.pdf_generator import PDFGenerator
from app.core.config import settings


class ParserService:
    """
    Service layer responsible for orchestrating the parsing process.
    Delegates extraction, normalization, and claim detection to dedicated layers.
    """

    def __init__(self):
        self.detector = FileTypeDetector()
        self.extractor_factory = ExtractorFactory()
        self.normalizer = NormalizationEngine()
        self.parser_engine = ParserEngine()
        self.pdf_generator = PDFGenerator(output_dir=str(settings.OUTPUT_DIR))

    def parse(self, raw_input: bytes, filename: str, generate_pdf: bool = True) -> ClaimDocument:
        """
        Orchestrates the conversion of raw input into a structured ClaimDocument.
        Pipeline: Detector → Extractor → Normalizer → Parser → Formatter → PDF Generator
        """
        logger.info(f"Request received to parse file: {filename}")

        # ── Step 1: Detect File Type ──
        input_type, detection_confidence = self.detector.detect(raw_input, filename)
        logger.info(f"File type detected: {input_type.value} (confidence: {detection_confidence})")

        # ── Step 2: Extraction ──
        extractor = self.extractor_factory.get_extractor(input_type)

        if input_type == InputType.USPTO_XML:
            # USPTO XML extractor returns Claim objects directly from structured XML
            claims, metadata = extractor.extract(raw_input)
            doc = ClaimDocument(
                input_type=input_type,
                confidence_score=100.0,
                ocr_used=False,
                claims=claims,
                metadata=metadata
            )
            logger.info(f"USPTO XML extracted {len(claims)} claims.")
        else:
            # All other inputs: extract text → normalize → parse via Rule Engine
            extracted_text = extractor.extract(raw_input)
            ocr_used = input_type == InputType.SCANNED_PDF

            # ── Step 3: Normalization ──
            normalized_text, norm_ops = self.normalizer.normalize(extracted_text)
            logger.info(f"Normalization applied ops: {norm_ops}")

            # ── Step 4: Parse into Hierarchy and Claim Objects ──
            doc = self.parser_engine.parse(normalized_text, input_type)
            doc.ocr_used = ocr_used

        # ── Step 5: PDF Generation ──
        if generate_pdf:
            doc.pdf_path = self.pdf_generator.generate(doc)

        logger.info(f"Parsing complete. Claims: {doc.claim_count}, Confidence: {doc.confidence_score}")

        return doc


parser_service = ParserService()
