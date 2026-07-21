"""
Transition Detector.
Identifies the primary transition phrase in a patent claim
and splits the claim into preamble + body.
"""
import re
from typing import Optional, Tuple
from app.parser.patterns import PRIMARY_TRANSITION_PATTERN, CATEGORY_PATTERNS


class TransitionResult:
    """Result of transition detection for a single claim."""
    __slots__ = ("preamble", "transition", "body", "category", "has_colon")

    def __init__(
        self,
        preamble: Optional[str],
        transition: Optional[str],
        body: str,
        category: str,
        has_colon: bool = False,
    ):
        self.preamble = preamble
        self.transition = transition
        self.body = body
        self.category = category
        self.has_colon = has_colon


class TransitionDetector:
    """
    Detects the primary transition word (comprising, consisting of, etc.)
    and splits the claim into preamble, transition, and body.
    Also detects claim category (method, system, apparatus, etc.).
    """

    def detect(self, claim_text: str) -> TransitionResult:
        """
        Parses the claim text and returns its structural components.
        """
        preamble: Optional[str] = None
        transition: Optional[str] = None
        body: str = claim_text
        has_colon: bool = False

        match = PRIMARY_TRANSITION_PATTERN.search(claim_text)
        if match:
            transition = match.group(1)
            preamble = claim_text[:match.start()].strip() or None
            # Body is everything after the transition word
            body = claim_text[match.end():].strip()
            # Include the colon if present
            if body.startswith(":"):
                has_colon = True
                body = body[1:].strip()

        category = self._detect_category(claim_text)

        return TransitionResult(
            preamble=preamble,
            transition=transition,
            body=body,
            category=category,
            has_colon=has_colon,
        )

    @staticmethod
    def _detect_category(text: str) -> str:
        """Classifies the claim into a category using keyword matching."""
        for cat, pattern in CATEGORY_PATTERNS.items():
            if pattern.search(text):
                return cat
        return "unknown"
