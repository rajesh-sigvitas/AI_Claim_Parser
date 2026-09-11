"""
Claim Splitter.
Splits normalized claim text into individual raw claim blocks.
Each block corresponds to exactly one patent claim.

Amendment papers renumber claims in place, and the markup has to be understood or the
claim set comes out wrong:

    11.        ...                 an ordinary claim
    [12.]      ...                 claim 12 was cancelled; its text is struck through
    12.[13.]   ...                 what was claim 13 is now claim 12

A bare bracketed number is a claim boundary like any other.  Treating it as body text --
which is what happens when the boundary pattern only accepts a bare digit -- silently
appends a cancelled claim's whole body to the claim above it.
"""
import re
from typing import List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class RawClaim:
    """Intermediate representation of a claim before full parsing."""
    number: int
    text: str  # The full raw text of this single claim (without the number prefix)
    old_number: Optional[int] = None   # previous number, when the claim was renumbered
    deleted: bool = False              # struck through in an amendment, i.e. cancelled


class ClaimSplitter:
    """
    Splits a block of patent claim text into individual RawClaim objects.
    Handles multiline claims, OCR spacing, and various numbering conventions.
    """

    # A claim boundary at the start of a line, in one of three forms:
    #   group 1 (+ optional group 2): "12." or "12.[13.]"   -- live claim, maybe renumbered
    #   group 3:                      "[12.]"               -- cancelled claim
    # The negative lookahead keeps decimals such as "3.5" from splitting a claim.
    _BOUNDARY = re.compile(
        r'(?:^|\n)[ \t]*(?:claim[ \t]+)?'
        r'(?:'
        r'(\d+)[ \t]*\.(?!\d)[ \t]*(?:\[[ \t]*(\d+)[ \t]*\.?[ \t]*\])?'
        r'|\[[ \t]*(\d+)[ \t]*\.?[ \t]*\]'
        r')[ \t]*',
        re.IGNORECASE
    )

    def split(self, claims_text: str) -> List[RawClaim]:
        """
        Splits the full claims section text into individual RawClaim objects.
        """
        # Find all claim boundary positions
        boundaries: List[Tuple[int, int, int, Optional[int], bool]] = []
        for m in self._BOUNDARY.finditer(claims_text):
            number, old_number, deleted = self._read_boundary(m)
            boundaries.append((m.start(), number, m.end(), old_number, deleted))

        if not boundaries:
            # If no numbered claims found, treat the entire text as claim 1
            stripped = claims_text.strip()
            if stripped:
                return [RawClaim(number=1, text=stripped)]
            return []

        raw_claims: List[RawClaim] = []
        for i, (start, num, body_start, old_number, deleted) in enumerate(boundaries):
            # The claim body extends from body_start to the start of the next claim
            if i + 1 < len(boundaries):
                body_end = boundaries[i + 1][0]
            else:
                body_end = len(claims_text)

            body = claims_text[body_start:body_end].strip()
            raw_claims.append(RawClaim(
                number=num, text=body, old_number=old_number, deleted=deleted
            ))

        return raw_claims

    @staticmethod
    def _read_boundary(match: re.Match) -> Tuple[int, Optional[int], bool]:
        """Returns (claim number, previous number, cancelled) for one boundary match."""
        if match.group(3) is not None:
            # "[12.]" -- the claim was cancelled, and 12 is the number it had.
            return int(match.group(3)), None, True

        number = int(match.group(1))
        old_number = int(match.group(2)) if match.group(2) else None
        return number, old_number, False
