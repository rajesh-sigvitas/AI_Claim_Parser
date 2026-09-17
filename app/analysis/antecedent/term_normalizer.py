"""
Turns a surface noun phrase into the canonical key used for antecedent matching.

Two occurrences refer to the same claim element when, and only when, their
canonical keys are equal.  The key therefore has to discard everything that a
patent examiner would consider cosmetic (articles, hyphenation, deictic
modifiers, grammatical number) while preserving everything that identifies the
element (ordinals such as "first"/"second", and every substantive modifier).
"""
import re

from app.analysis.antecedent.lexicon import ALL_DETERMINERS, DEICTIC_MODIFIERS

# Longest determiner first, so "a plurality of" wins over "a".
_DET_PREFIX = re.compile(
    r"^(?:" + "|".join(
        re.escape(d).replace(r"\ ", r"\s+")
        for d in sorted(ALL_DETERMINERS, key=len, reverse=True)
    ) + r")\s+",
    re.IGNORECASE,
)

_IRREGULAR_PLURALS = {
    "teeth": "tooth", "feet": "foot", "children": "child", "men": "man",
    "women": "woman", "people": "person", "mice": "mouse", "geese": "goose",
    "media": "medium", "data": "datum", "axes": "axis", "bases": "basis",
    "analyses": "analysis", "matrices": "matrix", "indices": "index",
    "vertices": "vertex", "vortices": "vortex", "apices": "apex",
    "apparatuses": "apparatus", "apparatus": "apparatus",
    "series": "series", "species": "species", "means": "means",
}

# Nouns whose singular already ends in -s; never strip the final s.
_INVARIANT_S = {
    "apparatus", "series", "species", "means", "gas", "glass", "lens",
    "axis", "basis", "chassis", "bus", "process", "class", "cross", "press",
    "status", "focus", "radius", "nucleus", "bias", "plus", "surplus",
}


def singularize(word: str) -> str:
    """Best-effort singular form of a single noun."""
    w = word.lower()
    if w in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[w]
    if w in _INVARIANT_S or len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ses") or w.endswith("xes") or w.endswith("zes") \
            or w.endswith("ches") or w.endswith("shes"):
        return w[:-2]
    if w.endswith("ves"):
        return w[:-3] + "f"
    if w.endswith("ss") or w.endswith("us") or w.endswith("is"):
        return w
    if w.endswith("s"):
        return w[:-1]
    return w


# A quantity noun leading a phrase says how many, not what: "the pair of distance
# sensors" and "each of the pair of look-up tables" name the sensors and the tables.
# "a pair of" is already a determiner, so without this the reference ("pair of
# distance sensor") could never match its own introduction ("distance sensor").
_QUANTITY_NOUN_PREFIX = re.compile(
    r"^(?:(?:pair|set|plurality|number|group|series|array|piece)\s+of\s+)+", re.IGNORECASE
)


def strip_determiner(surface_form: str) -> str:
    """Removes a leading determiner such as 'the' or 'a plurality of'."""
    term = surface_form.strip()
    previous = None
    while previous != term:
        previous = term
        term = _DET_PREFIX.sub("", term).strip()
    return term


def normalize_term(surface_form: str) -> str:
    """
    Canonical matching key for a noun phrase.

    "a plurality of Sub-Bent Portions"           -> "subbent portion"
    "the corresponding stationary rail bearings" -> "stationary rail bearing"
    """
    term = strip_determiner(surface_form.lower())
    term = strip_determiner(_QUANTITY_NOUN_PREFIX.sub("", term))

    # Drop surrounding punctuation and collapse whitespace.
    term = re.sub(r"^[\s\-]+|[\s.,;:)\]]+$", "", term)
    term = re.sub(r"\s+", " ", term).strip()
    if not term:
        return ""

    # A hyphen joins words; it does not make them one word.  "second-wheel assemblies"
    # names wheel assemblies, and "a thrust bearing" is "the thrust-bearing".
    term = re.sub(r"(?<=\w)-(?=\w)", " ", term)
    words = term.split(" ")

    # Deictic modifiers do not identify the element they qualify.
    words = [w for w in words if w not in DEICTIC_MODIFIERS] or words

    # Hyphens and internal punctuation are pure formatting noise; OCR routinely
    # loses them ("sub-bent" vs "subbent"), so they must not affect the key.
    words = [re.sub(r"[^\w]", "", w) for w in words]
    words = [w for w in words if w]
    if not words:
        return ""

    # Grammatical number is tracked as separate metadata by the plural checker,
    # so the key itself is always singular.
    words[-1] = singularize(words[-1])

    return " ".join(words)


def head_noun(normalized_term: str) -> str:
    """The final word of a normalised term, used for relational-noun lookups."""
    if not normalized_term:
        return ""
    return normalized_term.split(" ")[-1]
