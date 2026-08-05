"""
Extractor Factory.
Routes to the correct extractor based on detected InputType.
"""
from app.core.constants import InputType


class ExtractorFactory:
    """
    Factory responsible for instantiating the correct extractor
    based on the detected input type.
    """

    def get_extractor(self, input_type: InputType):
        """Returns the appropriate extractor instance."""
        if input_type == InputType.USPTO_XML:
            from app.extractor.xml import USPTOXMLExtractor
            return USPTOXMLExtractor()
        elif input_type == InputType.OTHER_XML:
            from app.extractor.generic_xml import GenericXMLExtractor
            return GenericXMLExtractor()
        elif input_type == InputType.TEXT_PDF:
            from app.extractor.pdf import PDFExtractor
            return PDFExtractor()
        elif input_type == InputType.SCANNED_PDF:
            from app.extractor.ocr import OCRExtractor
            return OCRExtractor()
        elif input_type == InputType.MICROSOFT_WORD:
            from app.extractor.word import WordExtractor
            return WordExtractor()
        else:
            from app.extractor.text import TextExtractor
            return TextExtractor()
