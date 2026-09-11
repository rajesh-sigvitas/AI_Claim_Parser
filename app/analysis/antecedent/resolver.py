"""
Missing and reverse antecedent detection.

For every referential noun phrase ("the X", "said X") the resolver asks a
single question: is there an introduction of X that this reference can legally
rely on?  An introduction qualifies when it is

  * in an ancestor claim (a dependent claim incorporates every limitation of
    the claims it depends from), or
  * earlier in the same claim, by ``(block_index, char_start)``.

If no introduction qualifies but one exists *later* in the same claim, the
reference is a reverse antecedent -- the element is used before it is defined.
If no introduction exists at all, the antecedent basis is missing.

The previous implementation approximated "earlier" with a per-claim counter and
then papered over the resulting mistakes with a whole-claim regex re-scan
(``check_retroactive_introduction``).  That re-scan searched the entire element
containing the reference, so any reverse antecedent inside a single element was
silently swallowed.  Exact offsets remove the need for it.
"""
from typing import Dict, List, Tuple

from app.analysis.antecedent.lexicon import RELATIONAL_NOUNS
from app.analysis.antecedent.term_normalizer import head_noun
from app.analysis.antecedent.term_registry import (
    INTRODUCTION,
    REFERENCE,
    Occurrence,
    TermRegistry,
)
from app.analysis.models import (
    AntecedentFinding,
    FindingLocation,
    FindingType,
    Severity,
)


def _is_inherent(term: str) -> bool:
    """
    True for inherent structural nouns that need no explicit introduction.

    MPEP 2173.05(e) accepts inherent antecedent basis for a thing's own parts,
    so "the bottom of the housing" is fine.  The test is on the *whole*
    normalised term, so a qualified phrase such as "the open bottom" is still
    reported -- "open bottom" is a specific feature, not an inherent part.
    """
    return term in RELATIONAL_NOUNS


def _location(occurrence: Occurrence, block_text: Dict[Tuple[int, int], str]) -> FindingLocation:
    return FindingLocation(
        element_index=occurrence.block_index,
        element_text=block_text.get((occurrence.claim_number, occurrence.block_index)),
        char_start=occurrence.char_start,
        char_end=occurrence.char_end,
        source=occurrence.source,
    )


def resolve_antecedents(
    registry: TermRegistry,
    block_text: Dict[Tuple[int, int], str] = None,
) -> List[AntecedentFinding]:
    block_text = block_text or {}
    findings: List[AntecedentFinding] = []

    for claim in registry.document.claims:
        claim_number = claim.number
        occurrences = registry.claim_occurrences(claim_number)

        # One finding per (term, problem) per claim; every occurrence of that
        # term is still recorded so the report can highlight them all.
        grouped: Dict[Tuple[str, FindingType], List[Occurrence]] = {}
        first_later_intro: Dict[str, Occurrence] = {}

        for occurrence in occurrences:
            if occurrence.kind != REFERENCE:
                continue

            term = occurrence.normalized_term
            if not term or _is_inherent(term):
                continue

            inherited = registry.inherited_introductions(claim_number, term)
            same_claim = registry.introductions_in_claim(claim_number, term)

            earlier = [i for i in same_claim if i.sort_key < occurrence.sort_key]
            later = [i for i in same_claim if i.sort_key > occurrence.sort_key]

            if inherited or earlier:
                continue  # properly supported

            if later:
                problem = FindingType.REVERSE_ANTECEDENT
                first_later_intro.setdefault(term, later[0])
            else:
                problem = FindingType.MISSING_ANTECEDENT

            grouped.setdefault((term, problem), []).append(occurrence)

        for (term, problem), refs in grouped.items():
            first = refs[0]
            locations = [_location(r, block_text) for r in refs]

            if problem is FindingType.REVERSE_ANTECEDENT:
                intro = first_later_intro[term]
                message = (
                    f"Reverse antecedent: \"{first.surface_form}\" is referenced "
                    f"before \"{intro.surface_form}\" introduces it in claim "
                    f"{claim_number}."
                )
                evidence = {
                    "reference": first.surface_form,
                    "normalized_term": term,
                    "introduced_as": intro.surface_form,
                    "reference_position": list(first.sort_key),
                    "introduction_position": list(intro.sort_key),
                    "occurrences": len(refs),
                }
                suggestion = (
                    f"Introduce \"{intro.surface_form}\" before it is referenced, or "
                    f"change the earlier \"{first.surface_form}\" to an indefinite "
                    f"form and make the later mention the reference."
                )
            else:
                message = (
                    f"No antecedent basis for \"{first.surface_form}\" in claim "
                    f"{claim_number}."
                )
                evidence = {
                    "reference": first.surface_form,
                    "normalized_term": term,
                    "previous_introduction": None,
                    "occurrences": len(refs),
                }
                article = "an" if term[:1] in "aeiou" else "a"
                suggestion = (
                    f"Introduce the element first (e.g. \"{article} {term}\"), or "
                    f"change \"{first.surface_form}\" to refer to an element that is "
                    f"already recited."
                )

            findings.append(AntecedentFinding(
                type=problem,
                severity=Severity.ERROR,
                claim_number=claim_number,
                term=first.surface_form,
                message=message,
                suggestion=suggestion,
                location=locations[0],
                locations=locations,
                evidence=evidence,
            ))

    return findings
