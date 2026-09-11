"""
Single traversal order for a claim's text blocks.

The analyser and the annotated report must agree on what "element index 3"
means, otherwise a finding is highlighted on the wrong line.  Both therefore
walk claims through :func:`iter_claim_blocks` instead of iterating
``claim.elements`` independently.

The header is block ``-1``; body elements are numbered from 0 in depth-first
order, so nested children get their own index rather than inheriting their
parent's (the previous code skipped children entirely).
"""
from dataclasses import dataclass
from typing import Iterator, List

from app.core.constants import ElementType
from app.models.claim import Claim, ClaimElement

HEADER_INDEX = -1


@dataclass
class ClaimBlock:
    index: int          # -1 for the header, else depth-first element position
    text: str           # the text the analyser sees and the report highlights
    source: str         # "PREAMBLE" or "BODY"
    level: int          # indentation level (0 for the header)
    marker: str = ""    # list marker such as "(a)", rendered before the text
    element: ClaimElement = None


def _walk(elements: List[ClaimElement], counter: List[int]) -> Iterator[ClaimBlock]:
    for el in elements:
        index = counter[0]
        counter[0] += 1
        source = "PREAMBLE" if el.element_type == ElementType.PREAMBLE else "BODY"
        yield ClaimBlock(
            index=index,
            text=el.text.strip(),
            source=source,
            level=max(1, min(9, el.level)),
            marker=(el.marker or "").strip(),
            element=el,
        )
        if el.children:
            yield from _walk(el.children, counter)


def iter_claim_blocks(claim: Claim) -> Iterator[ClaimBlock]:
    """Yields every text block of a claim in reading order."""
    header = (claim.header or "").strip()
    if header:
        yield ClaimBlock(index=HEADER_INDEX, text=header, source="PREAMBLE", level=0)

    counter = [0]
    yield from _walk(claim.elements, counter)
