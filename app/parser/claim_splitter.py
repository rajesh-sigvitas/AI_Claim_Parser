"""
Claim Splitter.
Splits normalized claim text into individual raw claim blocks.
Each block corresponds to exactly one patent claim.
"""
import re
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class RawClaim:
    """Intermediate representation of a claim before full parsing."""
    number: int
    text: str  # The full raw text of this single claim (without the number prefix)


class ClaimSplitter:
    """
    Splits a block of patent claim text into individual RawClaim objects.
    Handles multiline claims, OCR spacing, and various numbering conventions.
    """

    # Pattern to find claim boundaries: a number followed by period at line start
    # Negative lookbehind prevents matching decimals like "3.5"
    _BOUNDARY = re.compile(
        r'(?:^|\n)[ \t]*(?:claim[ \t]+)?(\d+)\.[ \t]*',
        re.IGNORECASE
    )

    def split(self, claims_text: str) -> List[RawClaim]:
        """
        Splits the full claims section text into individual RawClaim objects.
        """
        # Find all claim boundary positions
        boundaries: List[Tuple[int, int, int]] = []  # (match_start, number, body_start)
        for m in self._BOUNDARY.finditer(claims_text):
            claim_num = int(m.group(1))
            boundaries.append((m.start(), claim_num, m.end()))

        if not boundaries:
            # If no numbered claims found, treat the entire text as claim 1
            stripped = claims_text.strip()
            if stripped:
                return [RawClaim(number=1, text=stripped)]
            return []

        raw_claims: List[RawClaim] = []
        for i, (start, num, body_start) in enumerate(boundaries):
            # The claim body extends from body_start to the start of the next claim
            if i + 1 < len(boundaries):
                body_end = boundaries[i + 1][0]
            else:
                body_end = len(claims_text)

            body = claims_text[body_start:body_end].strip()
            raw_claims.append(RawClaim(number=num, text=body))

        return raw_claims
