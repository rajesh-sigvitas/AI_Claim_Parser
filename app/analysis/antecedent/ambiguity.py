"""
Ambiguous antecedent basis: a reference that two or more elements answer to.

Spec section 3.3, MPEP 2173.05(e): where a claim recites two different levers, a later
"said lever" does not say which one is meant, and the claim is indefinite for it.

    a sensor on the door ... a sensor on the window ... the sensor transmits
                                                        ^^^^^^^^^^ which one?

The spec's own detection sketch -- count introductions per head noun, flag a definite
reference once the count reaches two -- is too blunt to use directly.  It would flag "the
first wheel" after "a first wheel" and "a second wheel", where the ordinal says exactly
which one is meant.  What decides ambiguity is not how many elements share a head noun
but how many of them *answer to this reference*, which is the question
:func:`app.analysis.antecedent.term_match.supports` already answers everywhere else.

So: a reference is ambiguous when two or more introductions visible to its claim support
it.  "the first wheel" is supported only by "a first wheel", because a reference may add
no qualifier its introduction lacks; "the wheel" is supported by both, and is ambiguous.

Two further rules keep this from firing on one element mentioned twice:

*Readings of the same words are one element.*  The phrase reader registers several
readings of an ambiguous boundary and the of-object of a phrase alongside the phrase, so
one recitation can leave several introductions at overlapping character offsets.  Those
are collapsed by position before the count.

*An introduction must be visible.*  Inherited introductions always are; an introduction
later in the same claim is not -- a reference that precedes its introduction is a reverse
antecedent, which :mod:`app.analysis.antecedent.resolver` reports.
"""
import re
from collections import defaultdict
from typing import Dict, List, Tuple

from app.analysis.antecedent.resolver import (
    _is_inherent,
    _needs_no_antecedent,
    _support_any_reading,
)
from app.analysis.antecedent.lexicon import (
    DEICTIC_MODIFIERS,
    DISTRIBUTIVE_DETERMINERS,
)
from app.analysis.antecedent.swallowed_verbs import SwallowedVerbs
from app.analysis.antecedent.term_registry import REFERENCE, Occurrence, TermRegistry
from app.analysis.models import (
    DEFAULT_SEVERITY,
    AntecedentFinding,
    FindingLocation,
    FindingType,
)

_MESSAGE = (
    'Ambiguous antecedent basis: "{term}" in claim {claim} could be {count} different '
    "elements ({candidates}). A reference that fits more than one recited element does "
    "not say which is meant (MPEP 2173.05(e))."
)

_SUGGESTION = (
    'Name the element the reference means -- repeat the wording that introduced it, or '
    'distinguish the elements when they are recited (for example "a first {head}" and '
    '"a second {head}").'
)


def _distinct_elements(introductions: List[Occurrence]) -> List[Occurrence]:
    """
    One entry per recited element.

    Introductions covering the same words -- other readings of one phrase, or the object
    of "of" registered beside the phrase that governs it -- are one element, so the
    earliest-starting of each overlapping run is kept.
    """
    explicit = [o for o in introductions if not o.is_implicit and not o.is_gerund]
    ordered = sorted(explicit, key=lambda o: (o.claim_number, o.block_index,
                                              o.char_start, o.char_end))
    kept: List[Occurrence] = []
    seen_wording = set()
    for occurrence in ordered:
        last = kept[-1] if kept else None
        if (last is not None
                and last.claim_number == occurrence.claim_number
                and last.block_index == occurrence.block_index
                and occurrence.char_start < last.char_end):
            continue
        wording = " ".join(occurrence.normalized_term.split())
        if wording in seen_wording:
            continue
        seen_wording.add(wording)
        kept.append(occurrence)
    return kept


def check_ambiguous_antecedents(
    registry: TermRegistry, block_text: Dict[Tuple[int, int], str] = None
) -> List[AntecedentFinding]:
    """Reports every definite reference more than one recited element answers to."""
    block_text = block_text or {}
    verbs = SwallowedVerbs(registry, block_text)
    findings: List[AntecedentFinding] = []

    for claim in registry.document.claims:
        claim_number = claim.number
        grouped: Dict[str, List[Occurrence]] = defaultdict(list)
        candidates: Dict[str, List[Occurrence]] = {}

        is_dependent = bool(registry.claim_ancestors.get(claim_number))
        for occurrence in registry.claim_occurrences(claim_number):
            if occurrence.kind != REFERENCE:
                continue
            if is_dependent and occurrence.block_index < 0 and occurrence.char_start == 0:
                # "The system of claim 1" restates the parent's subject to say what this
                # claim depends from.  It names no element, so it cannot be unclear about
                # which one it names.
                continue
            if occurrence.determiner in DISTRIBUTIVE_DETERMINERS:
                # "each of the sensor signals", "one of the faces": the reference reaches
                # every one of the elements on purpose.
                continue
            words = [re.sub(r"[^\w]", "", w).lower() for w in occurrence.surface_form.split()]
            if any(w in DEICTIC_MODIFIERS for w in words):
                # "the respective face", "the corresponding sensor signal": the word
                # points at whichever one the context pairs it with.  Read from the
                # surface form, because normalization strips it from the term.
                continue
            if occurrence.number != "singular":
                # "the ring oscillators" after "a first ring oscillator" and "a second
                # ring oscillator" refers to both of them.  A plural reference covering
                # several elements is how claims refer to a group, not an ambiguity.
                continue
            term = occurrence.normalized_term
            if not term or _is_inherent(term) or _needs_no_antecedent(occurrence, block_text):
                continue

            same, inherited = _support_any_reading(registry, verbs, occurrence)
            visible = list(inherited) + [
                i for i in same if i.sort_key < occurrence.sort_key
            ]
            elements = _distinct_elements(visible)
            if len(elements) < 2:
                continue
            exact = [i for i in elements if i.normalized_term == term]
            if len(exact) == 1:
                # "a semiconductor material" and "a first semiconductor material" both
                # answer to "the semiconductor material", but only one of them is worded
                # as the reference is.  Repeating an introduction's own wording is how a
                # claim points at that element, so it is not unclear which is meant.
                continue

            grouped[term].append(occurrence)
            candidates.setdefault(term, elements)

        for term, references in grouped.items():
            findings.append(_finding(references, candidates[term], block_text))

    return findings


def _finding(
    references: List[Occurrence], elements: List[Occurrence],
    block_text: Dict[Tuple[int, int], str],
) -> AntecedentFinding:
    first = references[0]
    locations = [
        FindingLocation(
            element_index=r.block_index,
            element_text=block_text.get((r.claim_number, r.block_index)),
            char_start=r.char_start,
            char_end=r.char_end,
            source=r.source,
        )
        for r in references
    ]
    wordings = []
    for element in elements:
        wording = " ".join(element.surface_form.split())
        if wording not in wordings:
            wordings.append(wording)

    head = first.normalized_term.split()[-1]
    return AntecedentFinding(
        type=FindingType.AMBIGUOUS_ANTECEDENT,
        severity=DEFAULT_SEVERITY[FindingType.AMBIGUOUS_ANTECEDENT],
        claim_number=first.claim_number,
        term=" ".join(first.surface_form.split()),
        message=_MESSAGE.format(
            term=" ".join(first.surface_form.split()),
            claim=first.claim_number,
            count=len(elements),
            candidates=", ".join(f'"{w}"' for w in wordings),
        ),
        suggestion=_SUGGESTION.format(head=head),
        location=locations[0],
        locations=locations,
        evidence={
            "normalized_term": first.normalized_term,
            "candidates": wordings,
            "occurrences": len(references),
        },
    )
