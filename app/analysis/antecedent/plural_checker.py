"""
Number-agreement warnings: the same element recited as one thing and as several.

Once a claim recites "a plurality of suction conduits", a later bare "the primary
suction conduit" no longer identifies which conduit is meant, and the reverse -- a plural
reference to something introduced singly -- has no antecedent basis at all.

Four decisions shape what is reported.

*The number is established along the claim's own chain.*  A dependent claim incorporates
its ancestors' limitations and nothing else, so what a sibling claim recited cannot put
it in the wrong.

*Matching is on the head noun*, not on the full phrase.  "the plurality of suction
conduits" and "the primary suction conduit" never match as phrases, yet they are the same
noun in two numbers, and that mismatch is the whole point of the check.

*A claim that uses both numbers is not reported.*  "a suction conduit of the plurality of
suction conduits" is the correct way to draw one member out of a set; flagging it would
report the fix as the defect.

*Only a reference can disagree.*  "a plurality of pins ... the pin" is a mismatch (spec
section 3.5): "the pin" points back at something that was never recited singly.  A
dependent claim's "a seed" after "a plurality of seeds" points back at nothing -- it
introduces an element of its own -- so it has no number to disagree with.  Introductions
still establish the number that later references are measured against.

*A different compound is a different element.*  "a higher execution privilege level"
and "multiple translation levels" share only their last word.  When both terms carry a
word before the head noun, those words must agree ("suction conduits" / "the primary
suction conduit" still match); a term with no such word matches either.

*One warning per claim.*  A claim that mixes numbers usually does so for several related
terms at once ("conduit" and "nozzle" in the same sentence); they share a cause, so the
first is reported and the rest are recorded as evidence.
"""
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from app.analysis.antecedent.lexicon import (
    ALL_DETERMINERS,
    DEICTIC_MODIFIERS,
    DISTRIBUTIVE_DETERMINERS,
)
from app.analysis.antecedent.swallowed_verbs import SwallowedVerbs
from app.analysis.antecedent.term_normalizer import head_noun
from app.analysis.antecedent.term_registry import REFERENCE, Occurrence, TermRegistry
from app.analysis.models import (
    DEFAULT_SEVERITY,
    AntecedentFinding,
    FindingLocation,
    FindingType,
)

SINGULAR = "singular"
PLURAL = "plural"

# Spec section 3.5: "one or more X" and "at least one X" leave the number open and match
# both a singular and a plural reference.
_INDETERMINATE = {"one or more", "one or more of", "at least one", "at least one of"}
_DETERMINER_WORDS = {w for determiner in ALL_DETERMINERS for w in determiner.split()}

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
    """Warns where a claim recites one element in a number its chain contradicts."""
    conflicts: Dict[int, List[Occurrence]] = defaultdict(list)
    reported = set()

    verbs = SwallowedVerbs(registry, block_text)
    for occurrences in _by_head_noun(registry, verbs).values():
        for group in _compound_groups(occurrences):
            for found in _conflicts(group, registry):
                if id(found) not in reported:
                    reported.add(id(found))
                    conflicts[found.claim_number].append(found)

    findings: List[AntecedentFinding] = []
    for claim_number in sorted(conflicts):
        # Reading order, so the term reported is the first one in the claim.
        ordered = sorted(conflicts[claim_number], key=lambda o: o.sort_key)
        findings.append(_finding(ordered[0], ordered[1:], block_text))

    return findings


def _by_head_noun(
    registry: TermRegistry, verbs: SwallowedVerbs
) -> Dict[str, List[Tuple[int, Occurrence]]]:
    """Every occurrence in the claim set, grouped by head noun, in claim order."""
    grouped: Dict[str, List[Tuple[int, Occurrence]]] = defaultdict(list)

    for claim_number in sorted(registry.occurrences_by_claim):
        is_dependent = bool(registry.claim_ancestors.get(claim_number))
        for occurrence in sorted(registry.claim_occurrences(claim_number),
                                 key=lambda o: o.sort_key):
            if is_dependent and occurrence.kind == REFERENCE \
                    and occurrence.block_index < 0 and occurrence.char_start == 0:
                # "The rear attachment lens according to claim 1" opens every dependent
                # claim of that application.  It restates the parent's subject to say
                # what this claim depends from; it recites nothing, so it cannot
                # disagree about number.
                continue
            if occurrence.is_gerund:
                # A gerund names an act ("providing"), not a countable element, so
                # it has no grammatical number to agree or disagree with.
                continue
            # "each container" and "one or more synonyms" are kept: neither can itself
            # disagree, but both make a number available for a later reference to point
            # back at, which is decided in _introduced_numbers.
            if verbs.trimmed(occurrence) is not None:
                # "component points": the "-s" is the verb's, not a plural.
                continue
            noun = head_noun(occurrence.normalized_term)
            if noun:
                grouped[noun].append((claim_number, occurrence))

    return grouped


def _pre_head(occurrence: Occurrence) -> Optional[str]:
    """
    The word before the head noun, taken from the phrase as written so a hyphenated
    compound stays one word: "sub-bent portion" -> "subbent", which is not the "bent" of
    "bent portions".  None for a bare head ("the conduits").
    """
    if len(occurrence.normalized_term.split()) < 2:
        return None
    tokens = occurrence.surface_form.split()
    if len(tokens) < 2:
        return None
    word = re.sub(r"[^\w]", "", tokens[-2]).lower()
    if not word or word in DEICTIC_MODIFIERS or word in _DETERMINER_WORDS:
        return None
    return word


def _compound_groups(
    occurrences: List[Tuple[int, Occurrence]]
) -> List[List[Tuple[int, Occurrence]]]:
    """
    Splits one head noun's occurrences by compound: "privilege level" and "translation
    level" apart, a bare "levels" in both.
    """
    compounds = sorted({_pre_head(o) for _claim, o in occurrences} - {None})
    if len(compounds) <= 1:
        return [occurrences]
    return [
        [(c, o) for c, o in occurrences if _pre_head(o) in (compound, None)]
        for compound in compounds
    ]


def _number_of(occurrence: Occurrence) -> str:
    """"a plurality of X" is a plural recitation of X, as far as agreement goes."""
    return PLURAL if occurrence.number in ("plural", "plurality") else SINGULAR


def _chain(registry: TermRegistry, claim_number: int) -> List[int]:
    """The claim and the claims it inherits from, in reading order."""
    ancestors = registry.claim_ancestors.get(claim_number, [])
    return list(reversed(ancestors)) + [claim_number]


def _conflicts(
    occurrences: List[Tuple[int, Occurrence]], registry: TermRegistry
):
    """
    Each claim's own disagreement with the number its chain established.

    Scoped to the chain rather than to the whole claim set.  MID101312US claim 5 depends
    on claim 1, which recites only "a primary suction conduit"; the plural "suction
    conduits" belongs to claims 4, 9, 13 and 19, none of which claim 5 inherits from, and
    the real ClaimMaster report does not flag claim 5.  Reading the whole claim set let a
    sibling claim decide what a claim's own terms meant.
    """
    claims = {claim_number for claim_number, _occurrence in occurrences}
    for claim_number in sorted(claims):
        position = {number: index for index, number in enumerate(_chain(registry, claim_number))}
        visible = sorted(
            (pair for pair in occurrences if pair[0] in position),
            key=lambda pair: (position[pair[0]], pair[1].sort_key),
        )
        found = _first_conflict(visible, claim_number)
        if found is not None:
            yield found


def _introduced_numbers(occurrences: List[Tuple[int, Occurrence]]) -> set:
    """
    The numbers the chain makes available for a reference to point back at.

    An introduction offers its own number.  "each container" offers the singular even
    where only "a plurality of containers" was introduced, because it draws one member
    out of that set -- which is how claims are written, and why "the container" a few
    words later is not a mismatch.  "at least one X" leaves the number open and offers
    both (spec section 3.5).
    """
    numbers = set()
    for _claim, occurrence in occurrences:
        if occurrence.determiner in _INDETERMINATE:
            return {SINGULAR, PLURAL}
        if occurrence.determiner in DISTRIBUTIVE_DETERMINERS:
            numbers.add(SINGULAR)
        elif occurrence.kind != REFERENCE:
            numbers.add(_number_of(occurrence))
    return numbers


def _first_conflict(
    occurrences: List[Tuple[int, Occurrence]], claim_number: int
) -> Optional[Occurrence]:
    """
    The first reference in ``claim_number`` recited in a number its chain never
    introduced.

    Spec section 3.5: "a plurality of pins ... the pin" is a mismatch because nothing was
    ever recited singly, so "the pin" points back at nothing.  What matters is therefore
    which numbers the chain *introduced*, not which number was used most recently.

    Where a chain offers both -- "a plurality of suction conduits ... a primary suction
    conduit of the plurality of suction conduits" -- a reference in either number has
    something to point back at.  That is the MID101312US claim 9 shape, and it is why the
    real ClaimMaster report does not flag claims 10 and 11 for "the primary suction
    conduit".
    """
    introduced = _introduced_numbers(occurrences)
    if len(introduced) != 1:
        # Never introduced at all, or offered in both numbers: nothing to contradict.
        return None

    (established,) = introduced
    return next((
        occurrence for number, occurrence in occurrences
        if number == claim_number and occurrence.kind == REFERENCE
        and occurrence.determiner not in DISTRIBUTIVE_DETERMINERS
        and occurrence.determiner not in _INDETERMINATE
        and _number_of(occurrence) != established
    ), None)


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
        severity=DEFAULT_SEVERITY[FindingType.SINGULAR_PLURAL],
        claim_number=occurrence.claim_number,
        term=term,
        message=_MESSAGE.format(term=term),
        suggestion=_SUGGESTION,
        location=location,
        locations=[location],
        evidence=evidence,
    )
