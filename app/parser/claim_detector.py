"""
Claim Statement Detector.
Locates the beginning of the claims section in raw patent text.
Everything before the claim statement header is discarded.
"""
import re
from typing import Optional
from app.parser.patterns import CLAIM_STATEMENT_PATTERN


class ClaimStatementDetector:
    """
    Detects the claim section header and returns only the claim text.
    """

    def detect_and_strip(self, text: str) -> str:
        """
        Finds the claims header (e.g. 'What is claimed is:') and returns
        everything after it. If no header is found, returns the full text
        (the input may already be claims-only).
        """
        match = CLAIM_STATEMENT_PATTERN.search(text)
        if match:
            return text[match.end():].strip()
        return text.strip()
