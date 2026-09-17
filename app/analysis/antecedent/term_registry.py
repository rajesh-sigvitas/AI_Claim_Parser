"""
The occurrence store the checkers query.

Every noun-phrase occurrence found in the document is recorded here together
with the position that decides ordering.  Ordering is the whole point: a
reference is only satisfied by an introduction that *precedes* it, so the
registry sorts by ``(block_index, char_start)`` rather than by an incrementing
counter.  That is what lets a reverse antecedent be detected even when the
reference and its introduction sit inside the same element.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.analysis.antecedent.term_match import supports
from app.models.claim import Claim
from app.models.document import ClaimDocument

INTRODUCTION = "INTRODUCTION"
REFERENCE = "REFERENCE"


@dataclass
class Occurrence:
    """One appearance of a term in one claim."""
    normalized_term: str
    surface_form: str
    determiner: str
    number: str                     # 'singular' | 'plural' | 'plurality'
    claim_number: int
    source: str                     # "PREAMBLE" | "BODY"
    kind: str                       # INTRODUCTION | REFERENCE
    block_index: int                # -1 header, else depth-first element index
    char_start: int
    char_end: int
    is_implicit: bool = False
    is_gerund: bool = False         # weak support (spec section 2)
    # Other readings of the same words, where the phrase boundary was a guess
    # (see term_extractor._collect_phrase).  Matching accepts any reading.
    alternatives: List[str] = field(default_factory=list)
    spans: List[Tuple[int, int]] = field(default_factory=list)

    @property
    def readings(self) -> List[str]:
        """The normalized term, then every alternative reading of the same words."""
        return [self.normalized_term] + [
            a for a in self.alternatives if a and a != self.normalized_term
        ]

    @property
    def sort_key(self) -> Tuple[int, int]:
        return (self.block_index, self.char_start)

    # Compatibility with the previous RegistryEntry field names.
    @property
    def element_index(self) -> int:
        return self.block_index

    @property
    def article(self) -> str:
        return self.determiner


class TermRegistry:
    def __init__(self, document: ClaimDocument):
        self.document = document
        self.occurrences_by_claim: Dict[int, List[Occurrence]] = defaultdict(list)
        self.claims_by_number: Dict[int, Claim] = {c.number: c for c in document.claims}

        self.claim_ancestors: Dict[int, List[int]] = {}
        for claim in document.claims:
            self.claim_ancestors[claim.number] = self._resolve_ancestors(claim)

    # -- dependency graph ---------------------------------------------------

    def _direct_parents(self, claim: Claim) -> List[int]:
        if claim.metadata and claim.metadata.get("parent_claims"):
            return [int(p) for p in claim.metadata["parent_claims"]]
        if claim.parent_claim is not None:
            return [int(claim.parent_claim)]
        return []

    def _resolve_ancestors(self, claim: Claim) -> List[int]:
        """
        Every claim this one inherits from, nearest first.

        A dependent claim incorporates all limitations of its parents, so any
        term introduced anywhere up the chain provides antecedent basis.
        """
        ancestors: List[int] = []
        visited = {claim.number}
        queue = list(self._direct_parents(claim))

        while queue:
            number = queue.pop(0)
            if number in visited:
                continue
            visited.add(number)
            ancestors.append(number)

            parent_claim = self.claims_by_number.get(number)
            if parent_claim:
                queue.extend(
                    p for p in self._direct_parents(parent_claim) if p not in visited
                )

        return ancestors

    # -- population ---------------------------------------------------------

    def add(self, occurrence: Occurrence) -> None:
        self.occurrences_by_claim[occurrence.claim_number].append(occurrence)

    def finalize(self) -> None:
        """Sorts each claim's occurrences into reading order."""
        for entries in self.occurrences_by_claim.values():
            entries.sort(key=lambda o: o.sort_key)

    # -- queries ------------------------------------------------------------

    def claim_occurrences(self, claim_number: int) -> List[Occurrence]:
        return self.occurrences_by_claim.get(claim_number, [])

    def introductions_in_claim(self, claim_number: int, term: str) -> List[Occurrence]:
        return [
            o for o in self.claim_occurrences(claim_number)
            if o.kind == INTRODUCTION and o.normalized_term == term
        ]

    def inherited_introductions(self, claim_number: int, term: str) -> List[Occurrence]:
        """Introductions of `term` available from ancestor claims."""
        found: List[Occurrence] = []
        for ancestor in self.claim_ancestors.get(claim_number, []):
            found.extend(self.introductions_in_claim(ancestor, term))
        return found

    def supporting_introductions(
        self, claim_number: int, reference_term: str
    ) -> Tuple[List[Occurrence], List[Occurrence]]:
        """
        (same-claim, inherited) introductions whose wording supports ``reference_term``.

        Exact matches are included; so are introductions that say the same thing more
        specifically ("a flat top surface" for "the top surface") -- see
        :mod:`app.analysis.antecedent.term_match`.
        """
        def supporting(o: Occurrence) -> bool:
            return o.kind == INTRODUCTION and any(
                supports(reading, reference_term) for reading in o.readings
            )

        same = [o for o in self.claim_occurrences(claim_number) if supporting(o)]
        inherited: List[Occurrence] = []
        for ancestor in self.claim_ancestors.get(claim_number, []):
            inherited.extend(o for o in self.claim_occurrences(ancestor) if supporting(o))
        return same, inherited

    def visible_occurrences(self, claim_number: int, term: str) -> List[Occurrence]:
        """All occurrences of `term` visible to a claim, ancestors included."""
        found: List[Occurrence] = []
        for ancestor in reversed(self.claim_ancestors.get(claim_number, [])):
            found.extend(
                o for o in self.claim_occurrences(ancestor) if o.normalized_term == term
            )
        found.extend(
            o for o in self.claim_occurrences(claim_number) if o.normalized_term == term
        )
        return found

    def all_terms_in_claim(self, claim_number: int) -> List[str]:
        seen, ordered = set(), []
        for o in self.claim_occurrences(claim_number):
            if o.normalized_term not in seen:
                seen.add(o.normalized_term)
                ordered.append(o.normalized_term)
        return ordered
