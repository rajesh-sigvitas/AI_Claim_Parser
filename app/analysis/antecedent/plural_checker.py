"""
Number-agreement warnings: the same element recited as one thing and as several.

Once a claim set recites "a plurality of suction conduits", a later bare "the primary
suction conduit" no longer identifies which conduit is meant, and the reverse -- a plural
reference to something introduced singly -- has no antecedent basis at all.

Three decisions shape what is reported.

*Matching is on the head noun*, not on the full phrase.  "the plurality of suction
conduits" and "the primary suction conduit" never match as phrases, yet they are the same
noun in two numbers, and that mismatch is the whole point of the check.

*A claim that uses both numbers is not reported.*  "a suction conduit of the plurality of
suction conduits" is the correct way to draw one member out of a set; flagging it would
report the fix as the defect.

*One warning per claim.*  A claim that mixes numbers usually does so for several related
terms at once ("conduit" and "nozzle" in the same sentence); they share a cause, so the
first is reported and the rest are recorded as evidence.
"""
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from app.analysis.antecedent.term_normalizer import head_noun
from app.analysis.antecedent.term_registry import Occurrence, TermRegistry
from app.analysis.models import (
    AntecedentFinding,
    FindingLocation,
    FindingType,
    Severity,
)

SINGULAR = "singular"
PLURAL = "plural"

_MESSAGE = (
    'Singular/plural mismatch?: "{term}." Found the same term in singular and plural forms.'
)

_SUGGESTION = (
    "Make the number consistent, or tie the reference to the set it comes from "
    '(for example "a suction conduit of the plurality of suction conduits").'
)


def check_number_agreement(
    registry: TermRegistry, block_text: Dict[Tuple[int, int], str]
) -> List[AntecedentFinding]:
    """Warns where one element is recited in both numbers across the claim set."""
    conflicts: Dict[int, List[Occurrence]] = defaultdict(list)

    for occurrences in _by_head_noun(registry).values():
        found = _first_conflict(occurrences)
        if found is not None:
            conflicts[found.claim_number].append(found)

    findings: List[AntecedentFinding] = []
    for claim_number in sorted(conflicts):
        # Reading order, so the term reported is the first one in the claim.
        ordered = sorted(conflicts[claim_number], key=lambda o: o.sort_key)
        findings.append(_finding(ordered[0], ordered[1:], block_text))

    return findings


def _by_head_noun(registry: TermRegistry) -> Dict[str, List[Tuple[int, Occurrence]]]:
    """Every occurrence in the claim set, grouped by head noun, in claim order."""
    grouped: Dict[str, List[Tuple[int, Occurrence]]] = defaultdict(list)

    for claim_number in sorted(registry.occurrences_by_claim):
        for occurrence in sorted(registry.claim_occurrences(claim_number),
                                 key=lambda o: o.sort_key):
            noun = head_noun(occurrence.normalized_term)
            if noun:
                grouped[noun].append((claim_number, occurrence))

    return grouped


def _number_of(occurrence: Occurrence) -> str:
    """"a plurality of X" is a plural recitation of X, as far as agreement goes."""
    return PLURAL if occurrence.number in ("plural", "plurality") else SINGULAR


def _first_conflict(
    occurrences: List[Tuple[int, Occurrence]]
) -> Optional[Occurrence]:
    """
    The first occurrence that contradicts the number established before it.

    Walking claim by claim is what makes the result stable: the established number is
    whatever the previous claims used, so the claim that introduces the disagreement is
    reported rather than every claim that inherits it.
    """
    numbers = {_number_of(occurrence) for _claim, occurrence in occurrences}
    if len(numbers) < 2:
        return None

    per_claim: Dict[int, set] = defaultdict(set)
    order: List[int] = []
    for claim_number, occurrence in occurrences:
        if claim_number not in per_claim:
            order.append(claim_number)
        per_claim[claim_number].add(_number_of(occurrence))

    established: Optional[str] = None
    for claim_number in order:
        forms = per_claim[claim_number]

        if len(forms) > 1:
            # The claim recites the set and a member of it; proper, and it establishes
            # that a set exists for the claims that follow.
            established = PLURAL
            continue

        form = next(iter(forms))
        if established is not None and form != established:
            return next(
                occurrence for number, occurrence in occurrences
                if number == claim_number and _number_of(occurrence) == form
            )
        established = form

    return None


def _finding(
    occurrence: Occurrence, others: List[Occurrence],
    block_text: Dict[Tuple[int, int], str],
) -> AntecedentFinding:
    # Collapsed, because a term spanning a line break carries the newline and the next
    # line's indentation in its surface form.
    term = re.sub(r"\s+", " ", occurrence.surface_form).strip()
    location = FindingLocation(
        element_index=occurrence.block_index,
        element_text=block_text.get((occurrence.claim_number, occurrence.block_index)),
        char_start=occurrence.char_start,
        char_end=occurrence.char_end,
        source=occurrence.source,
    )
    evidence = {"normalized_term": occurrence.normalized_term}
    if others:
        evidence["also"] = [
            re.sub(r"\s+", " ", other.surface_form).strip() for other in others
        ]

    return AntecedentFinding(
        type=FindingType.SINGULAR_PLURAL,
        severity=Severity.WARNING,
        claim_number=occurrence.claim_number,
        term=term,
        message=_MESSAGE.format(term=term),
        suggestion=_SUGGESTION,
        location=location,
        locations=[location],
        evidence=evidence,
    )
