"""
Limiting-preamble warnings.

Whether a preamble limits a claim is decided by how the body uses it: a preamble term
relied on for antecedent basis in the body is given patentable weight, while a preamble
that only states an intended use generally is not (MPEP 2111.02).  That is a judgement
about the whole claim, not something a parser can settle, so every element a claim
introduces in its preamble is surfaced for the drafter to confirm.

Only independent claims are checked.  A dependent claim's opening words restate its
parent's subject matter to identify what it depends from -- "The base assembly of the
cleaning appliance ... of claim 1" -- so they are a back-reference, not a preamble whose
weight is in question.
"""
import re
from typing import Dict, List, Tuple

from app.analysis.antecedent.claim_walker import HEADER_INDEX
from app.analysis.antecedent.term_registry import INTRODUCTION, Occurrence, TermRegistry
from app.analysis.models import (
    AntecedentFinding,
    FindingLocation,
    FindingType,
    Severity,
)
from app.core.constants import ClaimType

_MESSAGE = (
    'Limiting preamble?: "{term}." Terms in the preamble may be given patentable weight '
    "if re-used in the claim body. See, e.g., MPEP 2111.02."
)

_SUGGESTION = (
    "Confirm this is intended to limit the claim. If it is only the intended use or field, "
    "consider whether the body should recite it; if it is a claim element, introduce it in "
    "the body instead."
)


def check_limiting_preamble(
    registry: TermRegistry, block_text: Dict[Tuple[int, int], str]
) -> List[AntecedentFinding]:
    """One warning per element introduced in an independent claim's preamble."""
    findings: List[AntecedentFinding] = []

    for claim_number, claim in sorted(registry.claims_by_number.items()):
        if not _is_independent(registry, claim_number, claim):
            continue

        seen: set = set()
        for occurrence in _preamble_introductions(registry, claim_number):
            if occurrence.normalized_term in seen:
                continue
            seen.add(occurrence.normalized_term)
            findings.append(_finding(occurrence, block_text))

    return findings


def _is_independent(registry: TermRegistry, claim_number: int, claim) -> bool:
    if registry.claim_ancestors.get(claim_number):
        return False
    return claim.claim_type == ClaimType.INDEPENDENT


def _preamble_introductions(registry: TermRegistry, claim_number: int) -> List[Occurrence]:
    """Elements the claim introduces in its preamble, in reading order."""
    return [
        occurrence for occurrence in registry.claim_occurrences(claim_number)
        if occurrence.block_index == HEADER_INDEX
        and occurrence.kind == INTRODUCTION
        and not occurrence.is_implicit
    ]


def _finding(
    occurrence: Occurrence, block_text: Dict[Tuple[int, int], str]
) -> AntecedentFinding:
    term = _display_term(occurrence.surface_form)
    location = FindingLocation(
        element_index=occurrence.block_index,
        element_text=block_text.get((occurrence.claim_number, occurrence.block_index)),
        char_start=occurrence.char_start,
        char_end=occurrence.char_end,
        source=occurrence.source,
    )
    return AntecedentFinding(
        type=FindingType.LIMITING_PREAMBLE,
        severity=Severity.WARNING,
        claim_number=occurrence.claim_number,
        term=term,
        message=_MESSAGE.format(term=term),
        suggestion=_SUGGESTION,
        location=location,
        locations=[location],
        evidence={"normalized_term": occurrence.normalized_term},
    )


def _display_term(surface_form: str) -> str:
    """
    The term as the report quotes it.

    A preamble term is usually the first phrase in the claim, so its article is
    capitalised -- "A base assembly".  Quoted mid-sentence it reads as the element, not
    the start of a sentence, so the article is lowercased again.

    Internal whitespace is collapsed: a term that spans a line break in the source
    carries the newline and the next line's indentation in its surface form, and quoting
    that verbatim would break the sentence the report prints it in.
    """
    term = re.sub(r"\s+", " ", surface_form).strip()
    if term[:1].isupper() and not term[1:2].isupper():
        return term[0].lower() + term[1:]
    return term
