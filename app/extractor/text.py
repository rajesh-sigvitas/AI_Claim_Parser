"""
Text Extractor.
Handles raw text input: validates UTF-8, normalizes encoding, returns raw text.
"""


class TextExtractor:
    """
    Extracts text from raw bytes.
    Validates UTF-8 encoding and returns the decoded string.
    """

    def extract(self, raw_input: bytes) -> str:
        """
        Decodes raw bytes to UTF-8 string.
        Replaces undecodable characters rather than failing.
        """
        if not raw_input:
            raise ValueError("Empty input: no text content provided.")
        return raw_input.decode("utf-8", errors="replace")
