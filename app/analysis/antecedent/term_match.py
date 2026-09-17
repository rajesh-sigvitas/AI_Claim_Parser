"""
When does an introduction support a reference whose wording is not identical?

Spec (docs/antecedent-basis-spec.md) section 2: "Non-identical wording still counts ...
Match on head noun, not on exact string."  Section 3.2: going from specific to general
("an aluminum lever" ... "the lever") is usually fine; going from general to specific
("a lever" ... "said aluminum lever") is indefinite.

A term is therefore reduced to its head noun and the set of words qualifying it.  An
introduction supports a reference when the heads agree and every qualifier of the
reference also qualifies the introduction:

    a flat top surface   surface {flat, top}  supports    the top surface     surface {top}
    fibres of plastic    fibre {plastic}      supports    the plastic fibres  fibre {plastic}
    a lever              lever {}             does not    the aluminum lever  lever {aluminum}
    a sensor housing     housing {sensor}     does not    the sensor          sensor {}
    a first wheel        wheel {first}        does not    the second wheel    wheel {second}

Word order carries no weight -- "fibres of plastic" and "plastic fibres" name the same
thing -- but the head does: in "X of Y" the head is X's noun, not Y.
"""
from typing import FrozenSet, Tuple

from app.analysis.antecedent.lexicon import ANAPHORIC_MODIFIERS
from app.analysis.antecedent.term_normalizer import singularize

TermKey = Tuple[str, FrozenSet[str]]


def term_key(normalized_term: str) -> TermKey:
    """(head noun, qualifiers) of a normalized term."""
    words = normalized_term.split()
    if "of" in words:
        split = words.index("of")
        before, after = words[:split], [w for w in words[split + 1:] if w != "of"]
    else:
        before, after = words, []
    if not before:
        return "", frozenset()
    head = singularize(before[-1])
    qualifiers = (w for w in before[:-1] + after if w not in ANAPHORIC_MODIFIERS)
    return head, frozenset(singularize(w) for w in qualifiers)


def supports(introduction: str, reference: str) -> bool:
    """True when an introduction worded ``introduction`` gives basis to ``reference``."""
    if introduction == reference:
        return True
    # Hyphens are read as spaces ("thrust-bearing" -> "thrust bearing"), and a hyphen
    # OCR dropped ("subbent") must still match one it kept ("sub bent").
    if introduction.replace(" ", "") == reference.replace(" ", ""):
        return True
    intro_head, intro_qualifiers = term_key(introduction)
    ref_head, ref_qualifiers = term_key(reference)
    return bool(ref_head) and ref_head == intro_head and ref_qualifiers <= intro_qualifiers
