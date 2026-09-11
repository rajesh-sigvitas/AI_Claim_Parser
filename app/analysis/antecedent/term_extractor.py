"""
Noun-phrase extraction for antecedent analysis.

Design notes
------------
*  Every extracted term carries the exact character span it occupies in the
   source text.  The previous implementation reconstructed the surface form
   with ``text.find(last_word, ...)``, which latched onto the wrong occurrence
   whenever a word repeated in the same element (e.g. "the memory stores a
   memory map").  Exact spans also let the report highlight the precise words.
*  Phrase boundaries come from closed word classes plus morphology
   (see :mod:`app.analysis.antecedent.lexicon`) rather than from a list of
   verbs observed in one specimen document.
*  Determiner-less plural noun phrases are recognised as *implicit*
   introductions, because "stationary rail bearings disposed in the second
   space" genuinely introduces that element and a later "the stationary rail
   bearings" has proper antecedent basis.
*  "the first and second tracks" is expanded into "first track" and
   "second track" so that each resolves against its own introduction.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.analysis.antecedent.lexicon import (
    ALL_DETERMINERS,
    DISTRIBUTIVE_DETERMINERS,
    NON_TERMS,
    NP_TERMINATORS,
    ORDINALS,
    PLURALITY_DETERMINERS,
    REFERENTIAL_DETERMINERS,
    is_adverb,
    is_finite_verb_s,
    is_participle,
    is_predicative_adjective,
    is_plural_form,
)
from app.analysis.antecedent.term_normalizer import normalize_term

MAX_PHRASE_WORDS = 6


@dataclass
class ExtractedTerm:
    """One noun-phrase occurrence located in a block of claim text."""
    surface_form: str
    normalized_term: str
    determiner: str
    number: str                 # 'singular' | 'plural' | 'plurality'
    start_index: int            # char offset of the determiner (or head word)
    end_index: int              # char offset just past the head noun
    is_reference: bool
    is_implicit: bool = False   # introduced without a determiner
    highlight_spans: List[tuple] = field(default_factory=list)

    def __post_init__(self):
        if not self.highlight_spans:
            self.highlight_spans = [(self.start_index, self.end_index)]

    # Kept for backwards compatibility with the previous attribute name.
    @property
    def article(self) -> str:
        return self.determiner


_DETERMINER_RE = re.compile(
    r"(?<![\w-])(?:" + "|".join(
        re.escape(d).replace(r"\ ", r"\s+")
        for d in sorted(ALL_DETERMINERS, key=len, reverse=True)
    ) + r")(?![\w-])",
    re.IGNORECASE,
)

_REFERENTIAL_SET = {d.lower() for d in REFERENTIAL_DETERMINERS}

# A word that may participate in a noun phrase: letters, digits, hyphens,
# apostrophes and slashes (e.g. "rail-side", "3D", "on/off").
_WORD_RE = re.compile(r"[A-Za-z0-9][\w\-'/]*")

_ORDINAL_ALT = "|".join(ORDINALS)

# "the first and second movable rail connection tracks"
# "the first, second and third tracks"
_COMPOUND_RE = re.compile(
    r"(?<![\w-])(the|said)\s+"
    r"((?:" + _ORDINAL_ALT + r")"
    r"(?:\s*,\s*(?:" + _ORDINAL_ALT + r"))*"
    r"\s*(?:,\s*)?and\s+(?:" + _ORDINAL_ALT + r"))\s+"
    r"(?=[A-Za-z])",
    re.IGNORECASE,
)

# Connectors after which a determiner-less noun phrase is an introduction.
_COMPOSITION_CONNECTOR_RE = re.compile(
    r"(?<![\w-])(?:comprised\s+of|comprising|consisting\s+essentially\s+of|"
    r"consisting\s+of|including|includes|selected\s+from|such\s+as|"
    r"defined\s+as|being)(?![\w-])\s*:?\s*",
    re.IGNORECASE,
)


def _tokenize(text: str, from_pos: int, limit: int = MAX_PHRASE_WORDS):
    """Yields (word, start, end) for up to `limit` candidate phrase words."""
    out = []
    pos = from_pos
    while len(out) < limit:
        m = _WORD_RE.search(text, pos)
        if not m:
            break
        # Stop if anything other than whitespace separates us from the word.
        gap = text[pos:m.start()]
        if gap.strip():
            break
        out.append((m.group(0), m.start(), m.end()))
        pos = m.end()
        # Trailing punctuation closes the phrase.
        if re.match(r"\s*[.,;:)\]]", text[pos:pos + 2] or " "):
            break
    return out


def _collect_phrase(text: str, from_pos: int):
    """
    Consumes the noun phrase starting at `from_pos`.

    Returns (words, start, end, stopped_at_determiner) or None.
    """
    candidates = _tokenize(text, from_pos)
    if not candidates:
        return None

    words, spans = [], []
    stopped_at_determiner = False
    has_head_noun = False

    for idx, (word, w_start, w_end) in enumerate(candidates):
        bare = re.sub(r"[^\w\-/']", "", word).lower()
        if not bare:
            break

        # Another determiner starts a new phrase.
        det_here = _DETERMINER_RE.match(text, w_start)
        if det_here and det_here.end() > w_start:
            stopped_at_determiner = True
            break

        # Closed-class function word: hard boundary.
        if bare in NP_TERMINATORS:
            break

        # Adverbs never belong to a noun phrase ("the slider diagonally
        # extended toward ..." -> "the slider").
        if is_adverb(bare):
            break

        # A predicative -able adjective sits outside the noun phrase -- but
        # only once a head noun has actually been collected.  In "a first
        # movable rail" the -able word is still attributive, because
        # everything before it is just an ordinal.
        if has_head_noun and is_predicative_adjective(bare):
            break

        # An -ing/-ed word after a head noun ends the phrase.
        #
        # English cannot tell "a sliding part" (attributive modifier) from
        # "a line connecting centers" (reduced relative clause) without a
        # parser, and guessing by look-ahead is worse than not guessing:
        # it truncated "a first extension line connecting centers" one way
        # and the later "the first and second extension lines" another way,
        # so the reference no longer matched its own introduction.  Cutting
        # at every participle truncates an introduction and its references
        # *identically*, which is what antecedent matching actually needs.
        # A participle in first position is kept, so "a rolling part" still
        # yields "rolling part".
        if words and is_participle(bare):
            break

        words.append(word)
        spans.append((w_start, w_end))
        if bare not in NON_TERMS and not is_predicative_adjective(bare):
            has_head_noun = True

        # Punctuation immediately after the word closes the phrase.
        if re.match(r"\s*[.,;:)\]]", text[w_end:w_end + 2] or " "):
            break

    if not words:
        return None

    # Trim a trailing finite verb, but only with syntactic evidence for one.
    # A noun phrase cannot be followed directly by a determiner, so if the scan
    # stopped at a determiner the last token collected must have been a verb:
    # "the base assembly creates an even suction pressure" -> "the base
    # assembly", "the memory stores a memory map" -> "the memory".  This is a
    # structural fact about the sentence, not a lookup, so it generalises to
    # any verb -- including one never catalogued -- without enumerating verbs
    # anywhere.  Only the one word is trimmed: everything before it already
    # forms a complete phrase, and English does not stack a second bare verb
    # directly in front of a determiner.
    if stopped_at_determiner and len(words) > 1:
        words.pop()
        spans.pop()

    # Elsewhere (end of phrase, a preposition, punctuation) there is no such
    # structural proof, so fall back to the small list of verbs that are
    # unambiguous in claim prose regardless of what follows them.
    while len(words) > 1 and is_finite_verb_s(re.sub(r"[^\w]", "", words[-1])):
        words.pop()
        spans.pop()

    # A phrase that is nothing but an ordinal or quantifier is not a term.
    cleaned = [re.sub(r"[^\w\-/']", "", w).lower() for w in words]
    if all(c in NON_TERMS for c in cleaned):
        return None

    return words, spans[0][0], spans[-1][1], stopped_at_determiner


def _number_for(determiner: str, head_word: str) -> str:
    det = determiner.lower().strip()
    if det in PLURALITY_DETERMINERS:
        return "plurality"
    if det in DISTRIBUTIVE_DETERMINERS:
        return "singular"
    if det in ("a", "an"):
        return "singular"
    return "plural" if is_plural_form(re.sub(r"[^\w]", "", head_word)) else "singular"


def _expand_compounds(text: str, covered: List[tuple]) -> List[ExtractedTerm]:
    """Turns "the first and second tracks" into one term per ordinal."""
    terms: List[ExtractedTerm] = []

    for m in _COMPOUND_RE.finditer(text):
        determiner = m.group(1).lower()
        ordinals = [o.lower() for o in re.findall(_ORDINAL_ALT, m.group(2), re.IGNORECASE)]
        phrase = _collect_phrase(text, m.end())
        if not phrase or not ordinals:
            continue

        words, noun_start, noun_end, _ = phrase
        noun_text = " ".join(words)
        head = re.sub(r"[^\w]", "", words[-1])

        for ordinal in ordinals:
            surface = f"{determiner} {ordinal} {noun_text}".strip()
            normalized = normalize_term(f"{ordinal} {noun_text}")
            if not normalized:
                continue
            terms.append(ExtractedTerm(
                surface_form=surface,
                normalized_term=normalized,
                determiner=determiner,
                # "the first and second tracks" refers to two singular
                # elements; the plural is agreement, not a number mismatch.
                number="singular",
                start_index=m.start(),
                end_index=noun_end,
                is_reference=True,
                highlight_spans=[(m.start(), noun_end)],
            ))

        covered.append((m.start(), noun_end))

    return terms


def _extract_determiner_terms(text: str, covered: List[tuple]) -> List[ExtractedTerm]:
    terms: List[ExtractedTerm] = []

    for m in _DETERMINER_RE.finditer(text):
        if any(s <= m.start() < e for s, e in covered):
            continue

        determiner = re.sub(r"\s+", " ", m.group(0)).lower()
        phrase = _collect_phrase(text, m.end())
        if not phrase:
            continue

        words, noun_start, noun_end, _ = phrase
        normalized = normalize_term(" ".join(words))
        if not normalized:
            continue

        head = re.sub(r"[^\w]", "", words[-1])
        is_reference = determiner in _REFERENTIAL_SET

        terms.append(ExtractedTerm(
            surface_form=text[m.start():noun_end],
            normalized_term=normalized,
            determiner=determiner,
            number=_number_for(determiner, head),
            start_index=m.start(),
            end_index=noun_end,
            is_reference=is_reference,
            highlight_spans=[(m.start(), noun_end)],
        ))
        covered.append((m.start(), noun_end))

    return terms


def _implicit_anchor_positions(text: str) -> List[int]:
    """
    Offsets at which a determiner-less noun phrase counts as an introduction:
    the start of the block, after a clause break, and after a composition
    connector such as "comprised of".
    """
    anchors = [0]
    for m in re.finditer(r"[;:]\s+|\.\s+|(?<![\w-])and\s+|(?<![\w-])or\s+|,\s+", text):
        anchors.append(m.end())
    for m in _COMPOSITION_CONNECTOR_RE.finditer(text):
        anchors.append(m.end())
    return sorted(set(anchors))


def _extract_implicit_terms(text: str, covered: List[tuple]) -> List[ExtractedTerm]:
    """
    Bare plural noun phrases at clause boundaries are introductions.

    Restricting this to *plural* heads is a deliberate precision guard: bare
    plurals ("movable rail bearings disposed in ...") are a normal way to
    introduce an element, whereas a bare singular is almost always a fragment
    of some other construction and treating it as an introduction would mask
    genuine missing-antecedent errors.
    """
    terms: List[ExtractedTerm] = []

    for anchor in _implicit_anchor_positions(text):
        m = _WORD_RE.search(text, anchor)
        if not m or text[anchor:m.start()].strip():
            continue
        if any(s <= m.start() < e for s, e in covered):
            continue
        if _DETERMINER_RE.match(text, m.start()):
            continue

        phrase = _collect_phrase(text, m.start())
        if not phrase:
            continue

        words, noun_start, noun_end, _ = phrase
        head = re.sub(r"[^\w]", "", words[-1])
        if not is_plural_form(head):
            continue

        normalized = normalize_term(" ".join(words))
        if not normalized:
            continue

        terms.append(ExtractedTerm(
            surface_form=text[noun_start:noun_end],
            normalized_term=normalized,
            determiner="",
            number="plurality",
            start_index=noun_start,
            end_index=noun_end,
            is_reference=False,
            is_implicit=True,
            highlight_spans=[(noun_start, noun_end)],
        ))
        covered.append((noun_start, noun_end))

    return terms


def extract_terms_from_text(text: str) -> List[ExtractedTerm]:
    """
    Extracts every candidate claim term from a block of text, in reading order.
    """
    if not text or not text.strip():
        return []

    covered: List[tuple] = []

    # Compounds first: they consume spans that the plain determiner scan would
    # otherwise mis-split at the "and".
    terms = _expand_compounds(text, covered)
    terms += _extract_determiner_terms(text, covered)
    terms += _extract_implicit_terms(text, covered)

    terms.sort(key=lambda t: (t.start_index, t.end_index))
    return terms
