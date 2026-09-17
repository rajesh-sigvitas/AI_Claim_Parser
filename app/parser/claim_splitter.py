"""
Claim Splitter.
Splits normalized claim text into individual raw claim blocks.
Each block corresponds to exactly one patent claim.

Claim numbers can also appear in bracketed forms:

    [12.]      ...
    12.[13.]   ...

This is what a document's automatic numbering looks like when its tracked changes are
rendered: LibreOffice prints a list number shifted by an edit beside the other.  A .docx
never reaches the splitter in that form -- its tracked changes are accepted before it is
read (app/document/revisions.py) -- but a PDF exported from such a rendering can.

Both forms are claim boundaries; treating them as body text appends the claim to the one
above it.  The bracketed number is taken as the claim's number: on the tracked-change
drafts compared against ClaimMaster it is the one that matches the accepted document's
numbering, and so the one the claims' own cross-references ("of claim 16") use.

A bracketed number is only a claim start with its period, "[12.]".  Paragraph numbers
("[0012]") never carry one, and accepting them made every paragraph of a specification a
claim whenever the claims could not be isolated first.

Brackets never mark a claim as cancelled.  Only the status identifier does: a cancelled
claim keeps its number and reads "12. (Canceled)" (37 CFR 1.121(c)).
"""
import re
from typing import List, Optional, Tuple
from dataclasses import dataclass

_CANCELED_STATUS = re.compile(r"^\s*[\(\[]\s*(?:canceled|cancelled)\s*[\)\]]", re.IGNORECASE)


@dataclass
class RawClaim:
    """Intermediate representation of a claim before full parsing."""
    number: int
    text: str  # The full raw text of this single claim (without the number prefix)
    rendered_number: Optional[int] = None  # the other number shown beside it: "12.[13.]" -> 12
    deleted: bool = False                  # carries the "(Canceled)" status identifier


class ClaimSplitter:
    """
    Splits a block of patent claim text into individual RawClaim objects.
    Handles multiline claims, OCR spacing, and various numbering conventions.
    """

    # A claim boundary at the start of a line, in one of three forms:
    #   group 1 (+ optional group 2): "12." or "12.[13.]"
    #   group 3:                      "[12.]"
    # The negative lookahead keeps decimals such as "3.5" from splitting a claim.
    _BOUNDARY = re.compile(
        r'(?:^|\n)[ \t]*(?:claim[ \t]+)?'
        r'(?:'
        r'(\d+)[ \t]*\.(?!\d)[ \t]*(?:\[[ \t]*(\d+)[ \t]*\.?[ \t]*\])?'
        r'|\[[ \t]*(\d+)[ \t]*\.[ \t]*\]'
        r')[ \t]*',
        re.IGNORECASE
    )

    def split(self, claims_text: str) -> List[RawClaim]:
        """
        Splits the full claims section text into individual RawClaim objects.
        """
        # Find all claim boundary positions
        boundaries: List[Tuple[int, int, int, Optional[int]]] = []
        for m in self._BOUNDARY.finditer(claims_text):
            number, rendered_number = self._read_boundary(m)
            boundaries.append((m.start(), number, m.end(), rendered_number))

        boundaries = self._drop_stray_numbers(boundaries)

        if not boundaries:
            # If no numbered claims found, treat the entire text as claim 1
            stripped = claims_text.strip()
            if stripped:
                return [RawClaim(number=1, text=stripped)]
            return []

        raw_claims: List[RawClaim] = []
        for i, (start, num, body_start, rendered_number) in enumerate(boundaries):
            # The claim body extends from body_start to the start of the next claim
            if i + 1 < len(boundaries):
                body_end = boundaries[i + 1][0]
            else:
                body_end = len(claims_text)

            body = claims_text[body_start:body_end].strip()
            raw_claims.append(RawClaim(
                number=num,
                text=body,
                rendered_number=rendered_number,
                deleted=bool(_CANCELED_STATUS.match(body)),
            ))

        return raw_claims

    # A number this far past the previous claim is not the next claim.
    _MAX_JUMP = 20

    @classmethod
    def _drop_stray_numbers(
        cls, boundaries: List[Tuple[int, int, int, Optional[int]]]
    ) -> List[Tuple[int, int, int, Optional[int]]]:
        """
        Removes line-initial numbers that are claim text, not claim starts.

        A value that wraps onto its own line ("... a viscosity of\n4300. ...") looks
        exactly like a claim number.  It is recognised by breaking the sequence: far past
        the previous claim while the claim that should come next appears later.  The
        number is then left in the body of the claim it belongs to.
        """
        kept: List[Tuple[int, int, int, Optional[int]]] = []
        for position, boundary in enumerate(boundaries):
            number = boundary[1]
            if kept:
                previous = kept[-1][1]
                expected_later = any(b[1] == previous + 1 for b in boundaries[position + 1:])
                if number - previous > cls._MAX_JUMP and expected_later:
                    continue
            kept.append(boundary)
        return kept

    @staticmethod
    def _read_boundary(match: re.Match) -> Tuple[int, Optional[int]]:
        """Returns (claim number, the other number shown beside it) for one boundary."""
        if match.group(3) is not None:
            return int(match.group(3)), None                  # "[12.]"

        number = int(match.group(1))
        if match.group(2):
            return int(match.group(2)), number                # "12.[13.]" -> 13
        return number, None
