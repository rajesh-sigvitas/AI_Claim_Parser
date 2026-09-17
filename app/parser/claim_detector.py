"""
Claim Statement Detector.
Locates the beginning of the claims section in raw patent text.
Everything before the claim statement header is discarded.
"""
import re
from typing import Optional
from app.parser.patterns import CLAIM_STATEMENT_PATTERN

# The explicit claim statements, matched anywhere in a line.  Line merging can join the
# statement to the text before it ("... CLAIM What is claimed is: 1. ..."); the
# line-anchored pattern then finds nothing and the whole document, specification
# included, is parsed as claims.  The last occurrence is taken, since the claims follow
# the description.
_INLINE_STATEMENT = re.compile(
    r"\b(?:what\s+is\s+claimed\s+is|the\s+invention\s+claimed\s+is|we\s+claim|i\s+claim)\s*[:.]",
    re.IGNORECASE,
)


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

        inline = list(_INLINE_STATEMENT.finditer(text))
        if inline:
            return text[inline[-1].end():].strip()
        return text.strip()
