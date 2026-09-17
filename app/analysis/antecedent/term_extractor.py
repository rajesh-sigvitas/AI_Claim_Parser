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
*  Determiner-less noun phrases are *implicit* introductions (spec
   docs/antecedent-basis-spec.md, section 2): an element is introduced when it
   appears without "the"/"said", article or not.  "receive telecommunication
   data", "provide first content" and "..., or third content" all introduce
   their element, exactly as "stationary rail bearings disposed in ..." does.
*  "the first and second tracks" is expanded into "first track" and
   "second track" so that each resolves against its own introduction.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.analysis.antecedent.lexicon import (
    ALL_DETERMINERS,
    DISTRIBUTIVE_DETERMINERS,
    NOMINAL_ING_ED,
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
from app.analysis.antecedent import lexicon as _lexicon
from app.analysis.antecedent import overrides as _overrides
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
    # The gerund of a recited act ("adjusting a parameter" -> "the adjusting").
    # Spec section 2 rates this as weak support; it is recorded so a severity
    # tier can downgrade it later, but for now it is simply an introduction.
    is_gerund: bool = False
    # Other normalized readings of the same words, where the phrase boundary was a
    # guess (see _collect_phrase).  Antecedent matching accepts any reading.
    alternatives: List[str] = field(default_factory=list)
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
# "the first- and second-wheel assemblies" (suspended hyphen), also written
# "the first - and second-wheel assemblies": the noun after the last ordinal is shared.
# Introductions use the same shorthand: "comprising first and second electrodes",
# "a first and a second power-shift clutch", "first and/or second time periods".
_ORDINAL_ARTICLE = r"(?:(?:a|an|the|said)\s+)?"
_COMPOUND_RE = re.compile(
    r"(?<![\w-])(?:(the|said|a|an)\s+)?"
    r"((?:" + _ORDINAL_ALT + r")(?:\s*-)?"
    r"(?:\s*,\s*" + _ORDINAL_ARTICLE + r"(?:" + _ORDINAL_ALT + r")(?:\s*-)?)*"
    r"\s*(?:,\s*)?(?:and/or|and|or)\s+" + _ORDINAL_ARTICLE + r"(?:" + _ORDINAL_ALT + r"))"
    r"(?:\s+|-)"
    r"(?=[A-Za-z])",
    re.IGNORECASE,
)

# Connectors after which a determiner-less noun phrase is an introduction.
_COMPOSITION_CONNECTOR_RE = re.compile(
    r"(?<![\w-])(?:comprised\s+of|comprising|comprises|comprise|"
    r"consisting\s+essentially\s+of|consisting\s+of|including|includes|include|"
    r"containing|contains|contain|having|has|have|selected\s+from|such\s+as|"
    r"defined\s+as|being)(?![\w-])\s*:?\s*",
    re.IGNORECASE,
)


# "the sensors each generate sensor signals": a quantifier floating after its plural
# subject quantifies that subject; it does not open a noun phrase.  Read as a
# determiner, it made the verb the element ("generate sensor signals") and cut the
# subject short ("the pair of distance" + "each").
_FLOATING_QUANTIFIERS = {"each", "every"}
_FLOATING_RE = re.compile(r"(?<![\w-])(each|every)\s+", re.IGNORECASE)
_PREVIOUS_WORD_RE = re.compile(r"([A-Za-z][\w-]*)\s+$")


def _is_floating_quantifier(text: str, position: int, determiner: str) -> bool:
    """True when the determiner at ``position`` floats after a plural noun."""
    if determiner not in _FLOATING_QUANTIFIERS:
        return False
    before = _PREVIOUS_WORD_RE.search(text[max(0, position - 60):position])
    if not before:
        return False
    word = before.group(1).lower()
    return is_plural_form(word) and word not in NP_TERMINATORS


def _clean_word(word: str) -> str:
    return re.sub(r"[^\w\-/']", "", word).lower()


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

    # A force-group override settles the boundary outright: the listed phrase is the
    # term, whatever the rules below would have made of it.
    forced = _overrides.active().forced_length([c[0] for c in candidates])
    if forced:
        taken = candidates[:forced]
        return ([c[0] for c in taken], taken[0][1], taken[-1][2], False, [], [])

    words, spans = [], []
    stopped_at_determiner = False
    has_head_noun = False
    alternative_cuts: List[int] = []
    object_starts: List[int] = []      # first word after an ambiguous participle

    def clause_follows(idx: int, w_end: int) -> bool:
        """True when what follows word ``idx`` cannot continue a noun phrase."""
        following = candidates[idx + 1] if idx + 1 < len(candidates) else None
        if following is None or re.match(r"\s*[.,;:)\]]", text[w_end:w_end + 2] or " "):
            return True
        follower = _clean_word(following[0])
        return bool(_DETERMINER_RE.match(text, following[1])) \
            or follower in NP_TERMINATORS or is_adverb(follower) \
            or follower in _lexicon.TRAILING_MODIFIERS

    for idx, (word, w_start, w_end) in enumerate(candidates):
        bare = re.sub(r"[^\w\-/']", "", word).lower()
        if not bare:
            break
        if not words and bare in _lexicon.NON_BREAKING_PREPOSITIONS:
            return None     # "out of fibres of plastic": the phrase starts after "of"

        # Another determiner starts a new phrase -- unless it is a quantifier
        # floating after a plural head, which ends this phrase without being the
        # determiner of the next one.
        det_here = _DETERMINER_RE.match(text, w_start)
        if det_here and det_here.end() > w_start:
            determiner = re.sub(r"\s+", " ", det_here.group(0)).lower()
            if words and _is_floating_quantifier(text, w_start, determiner):
                break
            stopped_at_determiner = True
            break

        # Closed-class function word: hard boundary.  A binding preposition is the
        # exception: "of" holds "a level of understanding" together.
        # "configured", "arranged", "adapted" end a phrase as "configured to ..." -- but
        # before the head noun, followed by a noun, they are modifiers ("two oppositely
        # arranged triangular plates", "a specially configured processor").
        if bare in NP_TERMINATORS and bare not in _lexicon.NON_BREAKING_PREPOSITIONS \
                and not (not has_head_noun and is_participle(bare)
                         and not clause_follows(idx, w_end)):
            break

        # "a mixing of individual components": the phrase stays whole, but what "of"
        # governs is the thing the act is performed on, which the claim has now
        # recited, so it is also offered as an introduction of its own.  Without this,
        # the later "the individual components" has only the whole phrase to match,
        # whose head is "mixing", and a properly introduced element reads as
        # unsupported.
        #
        # Not after a bare quantifier: in "a first pair of cameras" or "the number of
        # times", "of" belongs to the counting phrase, and registering its object would
        # introduce a plural "cameras" that the singular "the first camera" recited
        # elsewhere then contradicts.
        if bare in _lexicon.NON_BREAKING_PREPOSITIONS and words \
                and not all(_clean_word(w) in NON_TERMS for w in words):
            object_starts.append(len(words) + 1)

        # Adverbs never belong to a noun phrase ("the slider diagonally
        # extended toward ..." -> "the slider").
        # Before the head noun an adverb modifies the next word ("two oppositely
        # arranged triangular plates", "a substantially planar surface"); it is skipped.
        if is_adverb(bare):
            if has_head_noun:
                break
            continue

        # A finite verb after the head ends the phrase: "the solid axle connects
        # rear wheels" -> "the solid axle".  The trim below only ever looked at the
        # last word, so a verb in the middle carried its whole object into the term.
        if has_head_noun and is_finite_verb_s(bare):
            break
        # A plural head followed by a base-form verb: "the contact beams define ...".
        if has_head_noun and bare in _lexicon.BASE_VERBS \
                and is_plural_form(_clean_word(words[-1])):
            break

        # A predicative -able adjective sits outside the noun phrase -- but
        # only once a head noun has actually been collected.  In "a first
        # movable rail" the -able word is still attributive, because
        # everything before it is just an ordinal.
        # Followed by a noun it is attributive after all ("the strongest available
        # cellular signal"); then the reading that stops here is kept as an alternative.
        if has_head_noun and is_predicative_adjective(bare):
            if clause_follows(idx, w_end):
                break
            alternative_cuts.append(len(words))
            words.append(word)
            spans.append((w_start, w_end))
            continue

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
        # A participle before any noun is kept, as the -able rule above does: in
        # "a rolling part" and "a first rotating member" nothing but an ordinal
        # precedes it, so it is attributive.  (Cutting there left "a first" -- no
        # term at all -- and "the first and second rotating members" unsupported.)
        # The object of a binding preposition is a noun even when it ends in -ing
        # ("a level of understanding"), so there it does not end the phrase.
        #
        # After a noun, a participle is only certainly a verb when what follows cannot
        # continue a noun phrase: a determiner, a function word, an adverb, punctuation
        # ("a line connecting the centers", "a sensor mounted to", "a guide sliding,").
        # Followed by a bare word it is ambiguous -- "a rear locking collar" (modifier)
        # against "a line connecting centers" (verb).  Then the phrase continues and
        # the reading that stops here is kept as an alternative, so neither guess can
        # produce a false error.
        if has_head_noun and is_participle(bare) \
                and _clean_word(words[-1]) not in _lexicon.NON_BREAKING_PREPOSITIONS:
            if clause_follows(idx, w_end):
                break
            alternative_cuts.append(len(words))
            object_starts.append(len(words) + 1)

        words.append(word)
        spans.append((w_start, w_end))
        # "respective", "corresponding": they qualify a noun, they are not one.
        # A participle is never the head either: "the modified mapping".
        if bare not in NON_TERMS and not is_predicative_adjective(bare) \
                and bare not in _lexicon.DEICTIC_MODIFIERS and not is_participle(bare):
            has_head_noun = True

        # Punctuation immediately after the word closes the phrase.
        if re.match(r"\s*[.,;:)\]]", text[w_end:w_end + 2] or " "):
            break

    if not words:
        return None
    collected = list(words)
    collected_spans = list(spans)
    alternatives = [collected[:cut] for cut in alternative_cuts]

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
        # Usually right ("the memory stores a map"), but a noun can stand before a
        # determiner too ("the outer ply and the inner ply each bearing ..."), so the
        # untrimmed reading is kept as an alternative.
        alternatives.append(list(words))
        words.pop()
        spans.pop()

    # Elsewhere (end of phrase, a preposition, punctuation) there is no such
    # structural proof, so fall back to the small list of verbs that are
    # unambiguous in claim prose regardless of what follows them.
    while len(words) > 1 and is_finite_verb_s(re.sub(r"[^\w]", "", words[-1])):
        words.pop()
        spans.pop()

    # Neither a binding preposition nor a trailing modifier can end a noun phrase:
    # "the processor of claim 1" -> "processor", "the wheels of the vehicle together"
    # -> "vehicle", "holding the vehicle stationary" -> "vehicle".
    trailing = _lexicon.NON_BREAKING_PREPOSITIONS | _lexicon.TRAILING_MODIFIERS
    while len(words) > 1 and _clean_word(words[-1]) in trailing:
        words.pop()
        spans.pop()

    # Nor can a participle: "instructions stored thereon", "the features claimed here".
    # The object of a binding preposition is a noun even in -ing ("a level of
    # understanding"), so a word straight after "of" is never dropped.
    # Only the -ed form: a final -ing word is a noun more often than not ("the modified
    # mapping", "a lining").
    while len(words) > 1 and _clean_word(words[-1]).endswith("ed") \
            and is_participle(_clean_word(words[-1])) \
            and _clean_word(words[-1]) not in NOMINAL_ING_ED \
            and _clean_word(words[-2]) not in _lexicon.NON_BREAKING_PREPOSITIONS:
        words.pop()
        spans.pop()

    # A phrase that is nothing but an ordinal or quantifier is not a term.
    cleaned = [re.sub(r"[^\w\-/']", "", w).lower() for w in words]
    if all(c in NON_TERMS for c in cleaned):
        return None

    # A truncate override cuts an over-grouped phrase back to the words that name the
    # element: "server system controls" is the server system, not a "system controls".
    keep = _overrides.active().truncated_length([_clean_word(w) for w in words])
    if keep:
        words = words[:keep]
        spans = spans[:keep]
        alternatives = [a for a in alternatives if len(a) <= keep]
        object_starts = [start for start in object_starts if start < keep]

    alternatives = [
        a for a in alternatives
        if a and a != words and not all(_clean_word(w) in NON_TERMS for w in a)
    ]
    # The words after an ambiguous participle are a bare noun phrase either way -- the
    # participle's object ("the system receiving lubricant") or the rest of a compound --
    # so they are returned for registration as an introduction of their own.
    objects = []
    for first in object_starts:
        last = min(len(words), len(collected)) - 1
        if first <= last and not all(_clean_word(w) in NON_TERMS for w in collected[first:last + 1]):
            objects.append((collected[first:last + 1], collected_spans[first][0],
                            collected_spans[last][1]))
    return words, spans[0][0], spans[-1][1], stopped_at_determiner, alternatives, objects


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
        determiner = (m.group(1) or "").lower()
        is_reference = determiner in ("the", "said")
        ordinals = [o.lower() for o in re.findall(_ORDINAL_ALT, m.group(2), re.IGNORECASE)]
        phrase = _collect_phrase(text, m.end())
        if not phrase or not ordinals:
            continue

        words, noun_start, noun_end, _, alternatives, _objects = phrase
        noun_text = " ".join(words)
        head = re.sub(r"[^\w]", "", words[-1])

        for ordinal in ordinals:
            surface = f"{determiner} {ordinal} {noun_text}".strip()
            normalized = normalize_term(f"{ordinal} {noun_text}")
            if not normalized:
                continue
            ordinal_alternatives = [
                normalize_term(f"{ordinal} {' '.join(a)}") for a in alternatives
            ]
            terms.append(ExtractedTerm(
                surface_form=surface,
                normalized_term=normalized,
                determiner=determiner,
                # "the first and second tracks" refers to two singular
                # elements; the plural is agreement, not a number mismatch.
                number="singular",
                start_index=m.start(),
                end_index=noun_end,
                is_reference=is_reference,
                is_implicit=not determiner,
                alternatives=ordinal_alternatives,
                highlight_spans=[(m.start(), noun_end)],
            ))

        covered.append((m.start(), noun_end))

    return terms


_SUPERLATIVES = {"best", "worst", "most", "least", "last"}
_NOT_SUPERLATIVE = {
    "interest", "test", "forest", "chest", "nest", "rest", "west", "request", "contest",
    "protest", "guest", "crest", "quest", "digest", "manifest", "harvest", "inquest",
    "vest", "zest", "pest", "arrest",
}


def _is_superlative(word: str) -> bool:
    """"strongest", "highest", "best"; not "interest", "request", "test"."""
    return word in _SUPERLATIVES or (
        len(word) > 5 and word.endswith("est") and word not in _NOT_SUPERLATIVE
    )


def _extract_determiner_terms(text: str, covered: List[tuple]) -> List[ExtractedTerm]:
    terms: List[ExtractedTerm] = []

    for m in _DETERMINER_RE.finditer(text):
        if any(s <= m.start() < e for s, e in covered):
            continue

        determiner = re.sub(r"\s+", " ", m.group(0)).lower()
        if _is_floating_quantifier(text, m.start(), determiner):
            continue  # "the sensors each generate ...": not a determiner here

        phrase = _collect_phrase(text, m.end())
        if not phrase:
            continue

        words, noun_start, noun_end, _, alternatives, objects = phrase
        normalized = normalize_term(" ".join(words))
        if not normalized:
            continue

        head = re.sub(r"[^\w]", "", words[-1])
        is_reference = determiner in _REFERENTIAL_SET
        # "the strongest available signal", "the highest value": a superlative singles
        # out one member, so the phrase introduces its element rather than pointing back.
        introduces_itself = determiner == "the" and _is_superlative(_clean_word(words[0]))
        if introduces_itself:
            is_reference = False

        terms.append(ExtractedTerm(
            surface_form=text[m.start():noun_end],
            normalized_term=normalized,
            determiner=determiner,
            number=_number_for(determiner, head),
            start_index=m.start(),
            end_index=noun_end,
            is_reference=is_reference,
            is_implicit=introduces_itself,
            alternatives=[normalize_term(" ".join(a)) for a in alternatives],
            highlight_spans=[(m.start(), noun_end)],
        ))
        for object_words, object_start, object_end in objects:
            bare = _bare_term(text, object_words, object_start, object_end)
            # "the group of PbF2" already normalizes to "pbf2": registering the object
            # again would introduce the very term the phrase refers to, a beat after the
            # reference, and read as a reverse antecedent.
            if bare and bare.normalized_term != normalized:
                terms.append(bare)
        covered.append((m.start(), noun_end))

    return terms


# -- determiner-less introductions ------------------------------------------
#
# Spec section 2: an element is introduced whenever it appears WITHOUT "the" or
# "said"; an indefinite article is not required.  The previous rule accepted a
# bare phrase only when its head was plural, so "receive telecommunication
# data", "provide first content", "identify mitigation information" and
# "..., or third content" introduced nothing, and every later "the ..." was
# reported as a missing antecedent.
#
# A bare noun phrase is looked for wherever one can begin:
#
#   noun positions -- after a clause break, a conjunction, a composition
#       connector ("comprising"), a preposition, or a gerund (its object);
#   verb positions -- at the start of a limitation and after the infinitive
#       "to", where the first word is normally the limitation's verb
#       ("provide first content").  There the phrase is registered both whole
#       and without its first word: which one is the element cannot be told
#       without a parser, and registering both only ever adds support.
#
# "of" is a phrase start as well: "composed out of fibres of plastic" introduces the
# fibres.  Where "of" binds a phrase that is already being read ("a level of
# understanding"), the position after it is inside that phrase's span and is skipped.

NOUN_POSITION = "noun"
VERB_POSITION = "verb"

# Every preposition can govern a bare noun phrase ("carry out fluid transfer
# operation", "extending through bores"), except those that head a comparison or a
# fixed phrase rather than an element.  "to" is a verb position (below).
_ANCHOR_PREPOSITIONS = sorted(
    (_lexicon.PREPOSITIONS | {"using"})
    - {"to", "than", "as", "like", "unlike", "except", "such", "relative", "respect",
       "respectively", "including", "per"},
    key=len, reverse=True,
)
# "a memory having stored thereon instructions", "a medium having encoded therein a
# program": the bare phrase after the there-word is the element.
_NOUN_ANCHOR_RE = re.compile(
    r"\.\s+|,\s+|(?<![\w-])(?:and|or|nor)\s+"
    r"|(?<![\w-])(?:" + "|".join(map(re.escape, _ANCHOR_PREPOSITIONS)) + r")\s+"
    r"|(?<![\w-])there(?:on|in|with|to|upon|at|through|from|under)\s+",
    re.IGNORECASE,
)
_VERB_ANCHOR_RE = re.compile(
    r"[;:]\s+(?:(?:and|or)\s+)?|(?<![\w-])to\s+",
    re.IGNORECASE,
)
_GERUND_RE = re.compile(r"(?<![\w-])([A-Za-z]+ing)(?![\w-])")


def _is_gerund(word: str) -> bool:
    """
    A verbal -ing form: not a noun like "housing", not "comprising"/"being", and
    not a non-term such as the list pointer "following".
    """
    w = word.lower()
    return (
        len(w) > 4 and w.endswith("ing")
        and w not in NOMINAL_ING_ED and w not in NP_TERMINATORS and w not in NON_TERMS
    )


def _implicit_anchor_positions(text: str) -> Dict[int, str]:
    """
    Offsets at which a determiner-less noun phrase may begin, each tagged as a
    noun or a verb position.  A verb position wins when both apply, because its
    handling is a superset of the noun handling.
    """
    anchors: Dict[int, str] = {0: VERB_POSITION}

    def mark(position: int, kind: str) -> None:
        if anchors.get(position) != VERB_POSITION:
            anchors[position] = kind

    for m in _VERB_ANCHOR_RE.finditer(text):
        mark(m.end(), VERB_POSITION)
    for m in _NOUN_ANCHOR_RE.finditer(text):
        mark(m.end(), NOUN_POSITION)
    for m in _COMPOSITION_CONNECTOR_RE.finditer(text):
        mark(m.end(), NOUN_POSITION)
    # After a floating quantifier comes the verb: "the sensors each | generate ...".
    for m in _FLOATING_RE.finditer(text):
        if _is_floating_quantifier(text, m.start(), m.group(1).lower()):
            mark(m.end(), VERB_POSITION)
    for m in _GERUND_RE.finditer(text):
        if _is_gerund(m.group(1)):
            gap = re.match(r"\s+", text[m.end():])
            if gap:
                mark(m.end() + gap.end(), NOUN_POSITION)
    return anchors


def _bare_term(text: str, words: List[str], start: int, end: int) -> Optional[ExtractedTerm]:
    """An implicit introduction for ``words``, or None when they are not a noun phrase."""
    cleaned = [re.sub(r"[^\w\-/']", "", w).lower() for w in words]
    if all(c in NON_TERMS for c in cleaned):
        return None

    head = re.sub(r"[^\w]", "", words[-1])
    # "presented", "based": a participle standing alone is a verb, not an element.
    if is_participle(head):
        return None

    normalized = normalize_term(" ".join(words))
    if not normalized:
        return None

    return ExtractedTerm(
        surface_form=text[start:end],
        normalized_term=normalized,
        determiner="",
        number="plurality" if is_plural_form(head) else "singular",
        start_index=start,
        end_index=end,
        is_reference=False,
        is_implicit=True,
        highlight_spans=[(start, end)],
    )


def _extract_implicit_terms(text: str, covered: List[tuple]) -> List[ExtractedTerm]:
    """Determiner-less noun phrases, which introduce their element (spec section 2)."""
    terms: List[ExtractedTerm] = []

    for anchor, kind in sorted(_implicit_anchor_positions(text).items()):
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

        words, start, end, stopped_at_determiner, alternatives, _objects = phrase
        leads_with_gerund = _is_gerund(re.sub(r"[^\w]", "", words[0]))
        tail_start = (
            _WORD_RE.search(text, start + len(words[0])).start() if len(words) > 1 else start
        )

        if len(words) == 1:
            # A lone word directly before a determiner is a verb ("identify a
            # category"); a lone gerund is left to the gerund pass.
            if stopped_at_determiner or leads_with_gerund:
                continue
            candidates = [(start, words)]
        else:
            # A gerund leads a verb phrase, never a noun phrase: only its object
            # is an element.  At a verb position the first word may be the verb,
            # so the object is registered alongside the whole phrase.
            candidates = [] if leads_with_gerund else [(start, words)]
            if leads_with_gerund or kind == VERB_POSITION:
                candidates.append((tail_start, words[1:]))

        for phrase_start, phrase_words in candidates:
            term = _bare_term(text, phrase_words, phrase_start, end)
            if term:
                drop = len(words) - len(phrase_words)      # 1 for the tail reading
                term.alternatives = [
                    normalize_term(" ".join(a[drop:])) for a in alternatives if len(a) > drop
                ]
                terms.append(term)

        # A leading gerund stays uncovered so the gerund pass can register it.
        covered.append((tail_start if leads_with_gerund else start, end))

    return terms


def _extract_gerund_terms(text: str, covered: List[tuple]) -> List[ExtractedTerm]:
    """
    The gerund of a recited act introduces that act: "automatically adjusting a
    parameter" gives antecedent basis to a later "the adjusting" (spec section 2).
    """
    terms: List[ExtractedTerm] = []

    for m in _GERUND_RE.finditer(text):
        word = m.group(1)
        if not _is_gerund(word):
            continue
        if any(s <= m.start() < e for s, e in covered):
            continue
        normalized = normalize_term(word)
        if not normalized:
            continue

        terms.append(ExtractedTerm(
            surface_form=word,
            normalized_term=normalized,
            determiner="",
            number="singular",
            start_index=m.start(),
            end_index=m.end(),
            is_reference=False,
            is_implicit=True,
            is_gerund=True,
            highlight_spans=[(m.start(), m.end())],
        ))
        covered.append((m.start(), m.end()))

    return terms


def extract_terms_from_text(text: str) -> List[ExtractedTerm]:
    """
    Extracts every candidate claim term from a block of text, in reading order.
    """
    if not text or not text.strip():
        return []

    covered: List[tuple] = []

    # Compounds first: they consume spans that the plain determiner scan would
    # otherwise mis-split at the "and".  Gerunds last, so a gerund that belongs
    # to a noun phrase ("a sliding part") is already covered by it.
    terms = _expand_compounds(text, covered)
    terms += _extract_determiner_terms(text, covered)
    terms += _extract_implicit_terms(text, covered)
    terms += _extract_gerund_terms(text, covered)
    _attach_acronyms(text, terms)

    active = _overrides.active()
    if active.ignore:
        terms = [t for t in terms if not active.is_ignored(t.surface_form.split())]

    terms.sort(key=lambda t: (t.start_index, t.end_index))
    return terms


# "an analog-to-digital converter (ADC)", "a first field of view (FOV)", "a radio
# resource control (RRC) reconfiguration message".  Two capitals at least, so list
# markers such as "(a)" and "(i)" are not taken for acronyms.
_ACRONYM_RE = re.compile(r"\s*\(\s*([A-Za-z0-9&/\-]{2,16})\s*\)")


def _attach_acronyms(text: str, terms: List[ExtractedTerm]) -> None:
    """
    An acronym defined in parentheses names the term before it, so it is another
    reading of that term -- with the term's ordinal ("the first FOV") and with any
    words that follow it ("the RRC reconfiguration message").
    """
    for term in terms:
        m = _ACRONYM_RE.match(text, term.end_index)
        if not m or sum(c.isupper() for c in m.group(1)) < 2:
            continue
        acronym = m.group(1)
        ordinals = []
        for word in term.normalized_term.split():
            if word not in ORDINALS:
                break
            ordinals.append(word)

        readings = [normalize_term(" ".join(ordinals + [acronym]))]
        gap = re.match(r"\s+(?=[A-Za-z])", text[m.end():])
        if gap and not _DETERMINER_RE.match(text, m.end() + gap.end()):
            phrase = _collect_phrase(text, m.end() + gap.end())
            if phrase:
                rest = " ".join(phrase[0])
                readings.append(normalize_term(" ".join(ordinals + [acronym, rest])))
                readings.append(normalize_term(f"{term.normalized_term} {rest}"))
                # "a physical layer (PHY) protocol data unit (PPDU)": the acronym after
                # the continuation names the whole phrase.
                chained = _ACRONYM_RE.match(text, phrase[2])
                if chained and sum(c.isupper() for c in chained.group(1)) >= 2:
                    readings.append(normalize_term(" ".join(ordinals + [chained.group(1)])))
        term.alternatives.extend(r for r in readings if r)
