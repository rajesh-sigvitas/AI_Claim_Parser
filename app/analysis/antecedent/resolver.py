"""
Missing and reverse antecedent detection.

For every referential noun phrase ("the X", "said X") the resolver asks a
single question: is there an introduction of X that this reference can legally
rely on?  An introduction qualifies when it is

  * in an ancestor claim (a dependent claim incorporates every limitation of
    the claims it depends from), or
  * earlier in the same claim, by ``(block_index, char_start)``.

An introduction need not be worded identically: it qualifies when it names the same
element, possibly more specifically ("a flat top surface" for "the top surface"; see
:mod:`app.analysis.antecedent.term_match`).  A verb read into either term ("a second
software component points to ...") is set aside first; see
:mod:`app.analysis.antecedent.swallowed_verbs`.  Where the extractor had to guess a
phrase boundary it records the other readings too, and any reading may match.

If no introduction qualifies but one exists *later* in the same claim, the
reference is a reverse antecedent -- the element is used before it is defined.

Otherwise the verdict is tiered, as ClaimMaster's is ("antecedent basis errors" versus
"possibly missing AB ... flagged to be double-checked"; spec 3.1/3.2):

  * POSSIBLY_MISSING_ANTECEDENT (warning) when something in scope plausibly names the
    same element -- the same head noun worded differently, the word used only as a
    modifier ("the collection" / "a collection opening"), the act recited as a verb
    ("the change" / "changing the ownership"), a part of an element that is itself
    introduced ("the end segments of the outer ply", MPEP 2173.05(e)), or the
    reference without its last word;
  * MISSING_ANTECEDENT (error) only when there is no such candidate at all.  A
    different ordinal ("the second wheel" after "a first wheel") is never a candidate:
    ordinals name distinct elements.
"""
import re
from typing import Dict, List, Optional, Tuple

from app.analysis.antecedent.lexicon import (
    ABSTRACT_NOUNS,
    NON_TERMS,
    ORDINALS,
    RELATIONAL_NOUNS,
)
from app.analysis.antecedent.swallowed_verbs import SwallowedVerbs
from app.analysis.antecedent.term_match import supports, term_key
from app.analysis.antecedent.term_normalizer import singularize
from app.analysis.antecedent.term_registry import (
    INTRODUCTION,
    REFERENCE,
    Occurrence,
    TermRegistry,
)
from app.analysis.models import (
    DEFAULT_SEVERITY,
    AntecedentFinding,
    FindingLocation,
    FindingType,
)

_ORDINALS = set(ORDINALS)
_OF_THE = re.compile(r"\s+of\s+(?:the|said)\s+", re.IGNORECASE)

# Why a candidate makes a reference only "possibly" missing.
WORDING, MODIFIER, ACT, PART, TRAILING, NOMINAL = (
    "wording", "modifier", "act", "part", "trailing", "nominal",
)

_REASONS = {
    WORDING: "An introduction has the same head noun but different wording; confirm the "
             "reference means that element (a reference more specific than its "
             "introduction is indefinite, MPEP 2173.05(e)).",
    MODIFIER: "The word only describes the introduced element; a word may be missing "
              "from the reference.",
    ACT: "The act is recited, but the element is never introduced as a noun.",
    PART: "It may be an inherent part of the element it belongs to, which needs no "
          "introduction (MPEP 2173.05(e)); confirm.",
    TRAILING: "Without its last words the reference is introduced; they may not belong "
              "to the term.",
    NOMINAL: "It names an act on, or a property of, what follows \"of\", which may need "
             "no introduction; confirm.",
}

_NOMINAL_SUFFIXES = ("ment", "tion", "sion", "ance", "ence", "ure", "al", "ing", "ity")


def _is_inherent(term: str) -> bool:
    """
    True for inherent structural nouns that need no explicit introduction.

    MPEP 2173.05(e) accepts inherent antecedent basis for a thing's own parts,
    so "the bottom of the housing" is fine.  The test is on the *whole*
    normalised term, so a qualified phrase such as "the open bottom" is still
    reported -- "open bottom" is a specific feature, not an inherent part.
    """
    return term in RELATIONAL_NOUNS


_NEXT_WORD = re.compile(r"\s*([A-Za-z]+|:)")
_PROPERTY_FOLLOWERS = {"of", "that", "where", "when", "which", "whereby", "wherein",
                       "between", "among"}
_OF_NEW = re.compile(r"\s+of\s+(?!the\b|said\b|this\b|that\b|these\b|those\b)", re.IGNORECASE)
_SEQUENCE_LISTING = re.compile(r"\s*(?:set\s+forth\s+in|of|in|as\s+shown\s+in)?\s*SEQ\s+ID",
                               re.IGNORECASE)


def _needs_no_antecedent(occurrence: Occurrence, block_text: Dict[Tuple[int, int], str]) -> bool:
    """
    References that do not point back at a claimed element:

    * the text itself -- "the following steps", "the foregoing", "the steps of:";
    * a proper name -- "the Internet";
    * a property or circumstance of something -- "the time of the interruption", "the
      presence of the ransomware", "the size of historical transaction data".  MPEP
      2173.05(e): an inherent characteristic needs no introduction.  Only the bare noun
      qualifies; "the open bottom of the housing" names a feature and is still checked.
    """
    words = occurrence.surface_form.split()
    lower = [w.lower() for w in words]
    if any(w in ("following", "foregoing") for w in lower):
        return True

    text = block_text.get((occurrence.claim_number, occurrence.block_index), "")
    following = _NEXT_WORD.match(text, occurrence.char_end)
    next_word = following.group(1).lower() if following else ""
    term = occurrence.normalized_term

    if (term == "step" and next_word in ("of", ":")) or term.startswith("step of"):
        return True
    # Markush groups: "selected from the group consisting of A, B and C".
    if term.startswith("group") and (next_word in ("consisting", "of") or " of " in term):
        return True
    # Sequence listings: "the amino acid sequence of SEQ ID NO: 1", "... set forth in".
    if "seq id" in occurrence.surface_form.lower() \
            or _SEQUENCE_LISTING.match(text, occurrence.char_end):
        return True

    body = words[1:] if lower and lower[0] in ("the", "said") else words
    if any(len(w) > 1 and w[0].isupper() and w[1:].islower() for w in body):
        return True

    before_of = term.split(" of ")[0].split()
    if len(before_of) == 1 and before_of[0] in ABSTRACT_NOUNS \
            and (" of " in term or next_word in _PROPERTY_FOLLOWERS):
        return True
    # A property of something introduced right there: "the operational status of a
    # second PV module".  ("the open bottom of the housing" points back, and is checked.)
    if before_of and before_of[-1] in ABSTRACT_NOUNS and _OF_NEW.match(text, occurrence.char_end):
        return True
    return False


def _support(
    registry: TermRegistry, verbs: SwallowedVerbs, occurrence: Occurrence, term: str
) -> Tuple[List[Occurrence], List[Occurrence]]:
    """
    (same-claim, inherited) introductions that support ``term``.

    An introduction that swallowed its clause's verb ("a second software component
    points to ...") is also read without it, so it supports "the second software
    component".
    """
    claim_number = occurrence.claim_number
    same, inherited = registry.supporting_introductions(claim_number, term)
    for scope in [claim_number] + registry.claim_ancestors.get(claim_number, []):
        for intro in registry.claim_occurrences(scope):
            if intro.kind != INTRODUCTION or intro.is_gerund:
                continue
            trimmed = verbs.trimmed(intro)
            if trimmed and supports(trimmed, term):
                (same if scope == claim_number else inherited).append(intro)
    return same, inherited


def _reference_readings(occurrence: Occurrence) -> List[str]:
    """
    The readings a reference may be matched by.  A shortened reading ("image" for "the
    image processing device") is left out: matching it would let an unrelated "an image"
    hide a real error.  Introductions keep every reading -- "a first extension line
    connecting centers" must still introduce the extension line.
    """
    primary = occurrence.normalized_term
    return [r for r in occurrence.readings if r == primary or not primary.startswith(r + " ")]


def _support_any_reading(
    registry: TermRegistry, verbs: SwallowedVerbs, occurrence: Occurrence
) -> Tuple[List[Occurrence], List[Occurrence]]:
    same: List[Occurrence] = []
    inherited: List[Occurrence] = []
    for reading in _reference_readings(occurrence):
        s, i = _support(registry, verbs, occurrence, reading)
        same.extend(s)
        inherited.extend(i)
    return same, inherited


def _is_supported(registry: TermRegistry, verbs: SwallowedVerbs,
                  occurrence: Occurrence, term: str, nouns_only: bool = False) -> bool:
    same, inherited = _support(registry, verbs, occurrence, term)
    ok = (lambda i: not i.is_gerund) if nouns_only else (lambda i: True)
    return any(ok(i) for i in inherited) or any(
        ok(i) and i.sort_key < occurrence.sort_key for i in same
    )


def _supported_without_verb(
    registry: TermRegistry, verbs: SwallowedVerbs, occurrence: Occurrence
) -> bool:
    """
    True when a reference that swallowed its verb ("the buoyant body floats on ...")
    resolves without it.  Only a noun introduction counts: a gerund ("cooling") must not
    turn "the cooling ribs on ..." into a supported "the cooling".
    """
    trimmed = verbs.trimmed(occurrence)
    return bool(trimmed) and _is_supported(registry, verbs, occurrence, trimmed, nouns_only=True)


# -- possible antecedents ----------------------------------------------------------------


# Endings stripped to find a root, longest first.  Most simply fall away, but a few
# Latinate noun endings do not: the verb keeps a consonant the noun dropped
# ("extrude"/"extrusion", "transmit"/"transmission"), so those put candidates back.
_ROOT_SUFFIXES = (
    ("ications", ("ic",)), ("ication", ("ic",)),   # "application" <- "apply"
    ("ations", ()), ("ation", ()),                 # "determination" <- "determine"
    ("ssions", ("t", "s", "d")), ("ssion", ("t", "s", "d")),  # "transmission" <- "transmit"
    ("sions", ("d", "t", "s")), ("sion", ("d", "t", "s")),    # "extrusion" <- "extrude"
    ("tions", ()), ("tion", ()),                   # "production" <- "produce"
    ("ions", ()), ("ion", ()),                     # "action" <- "act"
    ("ments", ()), ("ment", ()),                   # "placement" <- "place"
    ("ances", ()), ("ance", ()),
    ("ences", ()), ("ence", ()),
    ("ings", ()), ("ing", ()),
    ("ally", ()), ("ly", ()),                      # "initially" -> "initial"
    ("ed", ()), ("es", ()), ("s", ()), ("e", ()),
)

# Past participles no suffix rule reaches.  Only verbs whose participle is not itself an
# ordinary claim noun: "ground" (a terminal), "cast" and "set" are left out, because
# there the participle reading is the less likely one.
_IRREGULAR_PARTICIPLES = {
    "wound": "wind", "bound": "bind", "bent": "bend", "held": "hold",
    "made": "make", "sent": "send", "built": "build", "spun": "spin",
    "woven": "weave", "drawn": "draw", "grown": "grow", "blown": "blow",
    "driven": "drive", "given": "give", "taken": "take", "frozen": "freeze",
}


def _stems(word: str) -> set:
    """
    Every plausible root of one word.

    A set, not one string, because the same ending is ambiguous: "action" is "act"+"ion"
    but "production" is "produc"+"tion", and only one of the two readings lines up with
    the verb the claim recites.  Two forms of one verb then share a member -- "applied"
    and "applying" both yield "appl", "extrusion" and "extruding" both yield "extrud" --
    which a single stem string could not do without picking the wrong reading for one of
    the pair and silently failing to relate them.
    """
    w = word.lower()
    bases = {w}
    if w in _IRREGULAR_PARTICIPLES:
        bases.add(_IRREGULAR_PARTICIPLES[w])
    for suffix, additions in _ROOT_SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            cut = w[: -len(suffix)]
            bases.add(cut)
            bases.update(cut + a for a in additions)

    roots = set()
    for base in bases:
        roots.add(base)
        if len(base) < 4:
            continue
        if base[-1] in "iy":      # "applied" -> "appli", "apply" -> "appl"
            roots.add(base[:-1])
        if base.endswith("e"):    # "change" -> "chang", which "changing" also reaches
            roots.add(base[:-1])
        if len(base) > 4 and base[-1] == base[-2] and base[-1] not in "aeiou":
            roots.add(base[:-1])  # "stopped"/"stopping" -> "stopp" -> "stop"
    return roots


def _related(word: str, other: str) -> bool:
    """
    Two forms of one verb: "determination"/"determining", "interruption"/"interrupted",
    "selected"/"selecting".  Plural and singular of one noun are not two forms of a verb.
    """
    if word == other or singularize(word) == singularize(other):
        return False
    return bool(_stems(word) & _stems(other))


def _names_recited_act(term: str, scope_words: set) -> Optional[str]:
    """
    The verb form an act noun stands for: "the change" <- "changing", "the
    determination" <- "determining", "the interruption" <- "interrupted", "the initial
    production" <- "initially producing".

    Deliberately narrow, because a looser match hides real errors ("the base station" is
    not "based", "the controller" is not "controlling"): the act noun is the head, it is
    an act noun (a nominal suffix, or the bare base of the verb), it is not an ordinary
    property noun ("the position" / "positioned"), and the claim uses the verb itself
    (-ing / -ed) with the same stem.

    A word in front of the head is allowed only when it is another form of a word the
    claim recites, so "initially producing" supports "the initial production" while "a
    station" is still not "the base station".
    """
    words = term.split()
    if not words or words[-1] in ABSTRACT_NOUNS:
        return None
    noun = words[-1]
    for qualifier in words[:-1]:
        if not any(_related(qualifier, w) for w in scope_words):
            return None
    for verb in scope_words:
        if not verb.endswith(("ing", "ed")) or not _related(noun, verb):
            continue
        if noun.endswith(_NOMINAL_SUFFIXES) or verb in (noun + "ing", noun + "ed",
                                                         noun + "d", noun[:-1] + "ing"):
            return verb
    return None


def _scope_words(registry: TermRegistry, occurrence: Occurrence,
                 block_text: Dict[Tuple[int, int], str]) -> set:
    """Every word of the claim and the claims it depends from."""
    claims = {occurrence.claim_number, *registry.claim_ancestors.get(occurrence.claim_number, [])}
    words = set()
    for (claim_number, _block), text in block_text.items():
        if claim_number in claims and text:
            words.update(re.findall(r"[a-z]{4,}", text.lower()))
    return words


def _is_participle(word: str) -> bool:
    """A past participle, so that it can say what a recited act did to an element."""
    return word.endswith("ed") or word in _IRREGULAR_PARTICIPLES


def _described_by_recited_act(
    registry: TermRegistry, verbs: SwallowedVerbs, occurrence: Occurrence,
    block_text: Dict[Tuple[int, int], str],
) -> bool:
    """
    "selecting a payment gateway ... the selected payment gateway": the extra words are
    past participles of acts the claim recites, so they say what happened to the element
    rather than naming another one.
    """
    scope = None
    for reading in _reference_readings(occurrence):
        head, qualifiers = term_key(reading)
        if not head:
            continue
        for intro in _scope(registry, occurrence):
            intro_head, intro_qualifiers = term_key(intro.normalized_term)
            extra = qualifiers - intro_qualifiers
            if intro_head != head or not extra or not all(_is_participle(q) for q in extra):
                continue
            if scope is None:
                scope = _scope_words(registry, occurrence, block_text)
            if all(any(_related(q, w) for w in scope) for q in extra):
                return True
    return False


def _scope(registry: TermRegistry, occurrence: Occurrence) -> List[Occurrence]:
    """Introductions a reference may rely on: earlier in its claim, or in an ancestor."""
    found = [
        o for o in registry.claim_occurrences(occurrence.claim_number)
        if o.kind == INTRODUCTION and o.sort_key < occurrence.sort_key
    ]
    for ancestor in registry.claim_ancestors.get(occurrence.claim_number, []):
        found.extend(o for o in registry.claim_occurrences(ancestor) if o.kind == INTRODUCTION)
    return found


def _possible_antecedent(
    registry: TermRegistry, verbs: SwallowedVerbs, occurrence: Occurrence,
    block_text: Dict[Tuple[int, int], str],
) -> Optional[Tuple[str, str]]:
    """(reason, what might be the antecedent), or None when nothing in scope could be."""
    readings = occurrence.readings
    keys = [term_key(r) for r in readings]
    scope = _scope(registry, occurrence)

    # Every plausible introduction, ranked: the same head noun first, then an element the
    # word directly qualifies ("collection opening" for "the collection"), then one it
    # qualifies from further away ("liquid collection channel").
    ranked: List[Tuple[int, int, int, str, str]] = []
    for position, intro in enumerate(scope):
        if intro.is_gerund:
            continue
        intro_readings = list(intro.readings)
        trimmed = verbs.trimmed(intro)
        if trimmed:
            intro_readings.append(trimmed)
        for intro_reading in intro_readings:
            intro_head, intro_qualifiers = term_key(intro_reading)
            intro_words = intro_reading.split(" of ")[0].split()
            for head, qualifiers in keys:
                if not head or (qualifiers & _ORDINALS) - intro_qualifiers:
                    continue      # "the second wheel" is not "a first wheel"
                # Ties go to the introduction with the fewest extra words: for "the
                # collection", "a collection opening" before "a liquid collection channel".
                extra = len(intro_qualifiers - qualifiers)
                if head == intro_head:
                    ranked.append((0, extra, position, WORDING, intro.surface_form))
                elif head in intro_qualifiers:
                    adjacent = len(intro_words) > 1 and intro_words[-2] == head
                    ranked.append((1 if adjacent else 2, extra, position, MODIFIER,
                                   intro.surface_form))
    best = min(ranked) if ranked else None
    if best and best[0] == 0:
        # Same head noun: nothing explains the reference better.
        return best[-2], best[-1]

    # The act is recited as a verb: "changing the ownership" ... "the change",
    # "determining that ..." ... "the determination".  This is tried before a remaining
    # MODIFIER match, because a word the claim also uses as a verb explains the
    # reference better than one that merely sits inside another element's name: "the
    # extrusion" is "extruding", not the "extrusion-based" of the preamble.
    text = block_text.get((occurrence.claim_number, occurrence.block_index), "")
    scope_words = _scope_words(registry, occurrence, block_text)
    for reading in readings:
        verb = _names_recited_act(reading, scope_words)
        if verb:
            return ACT, verb

    # A part of an element that is itself introduced: "the end segments of the outer ply".
    of_the = _OF_THE.match(text, occurrence.char_end)
    if of_the:
        owner_start = occurrence.char_end + len(of_the.group(0)) - len(of_the.group(0).lstrip())
        for owner in registry.claim_occurrences(occurrence.claim_number):
            if owner.kind == REFERENCE and owner.block_index == occurrence.block_index \
                    and owner_start <= owner.char_start <= of_the.end() \
                    and any(_is_supported(registry, verbs, owner, r) for r in owner.readings):
                return PART, owner.surface_form

    if best:
        return best[-2], best[-1]

    # A nominalised act or property of what follows: "the treatment of plants", "the
    # movement of golf clubs".
    head = (readings[0].split(" of ")[0].split() or [""])[-1]
    following = _NEXT_WORD.match(text, occurrence.char_end)
    followed_by_of = bool(following) and following.group(1).lower() == "of"
    if head.endswith(_NOMINAL_SUFFIXES) and (followed_by_of or " of " in readings[0]):
        return NOMINAL, ""

    # The reference without its last words is introduced: "the rack adjacent to ...",
    # "the method facilitates affiliate link generation".
    for reading in readings:
        words = reading.split()
        for cut in range(len(words) - 1, 0, -1):
            prefix_words = words[:cut]
            if all(w in NON_TERMS for w in prefix_words):
                break
            if prefix_words[-1] == "of":
                continue
            prefix = " ".join(prefix_words)
            if _is_supported(registry, verbs, occurrence, prefix, nouns_only=True):
                return TRAILING, prefix

    return None


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
    verbs = SwallowedVerbs(registry, block_text)

    for claim in registry.document.claims:
        claim_number = claim.number
        occurrences = registry.claim_occurrences(claim_number)

        # One finding per (term, problem) per claim; every occurrence of that
        # term is still recorded so the report can highlight them all.
        grouped: Dict[Tuple[str, FindingType], List[Occurrence]] = {}
        first_later_intro: Dict[str, Occurrence] = {}
        possible: Dict[str, Tuple[str, str]] = {}

        for occurrence in occurrences:
            if occurrence.kind != REFERENCE:
                continue

            term = occurrence.normalized_term
            if not term or _is_inherent(term) or _needs_no_antecedent(occurrence, block_text):
                continue

            same_claim, inherited = _support_any_reading(registry, verbs, occurrence)

            earlier = [i for i in same_claim if i.sort_key < occurrence.sort_key]
            later = [i for i in same_claim if i.sort_key > occurrence.sort_key]

            if inherited or earlier:
                continue  # properly supported
            if _supported_without_verb(registry, verbs, occurrence):
                continue  # "the buoyant body floats on ..." is "the buoyant body"
            if _described_by_recited_act(registry, verbs, occurrence, block_text):
                continue  # "selecting a gateway" ... "the selected gateway"

            if later:
                problem = FindingType.REVERSE_ANTECEDENT
                first_later_intro.setdefault(term, later[0])
            else:
                candidate = _possible_antecedent(registry, verbs, occurrence, block_text)
                if candidate:
                    problem = FindingType.POSSIBLY_MISSING_ANTECEDENT
                    possible.setdefault(term, candidate)
                else:
                    problem = FindingType.MISSING_ANTECEDENT

            grouped.setdefault((term, problem), []).append(occurrence)

        for (term, problem), refs in grouped.items():
            first = refs[0]
            locations = [_location(r, block_text) for r in refs]
            severity = DEFAULT_SEVERITY[problem]
            article = "an" if term[:1] in "aeiou" else "a"

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
            elif problem is FindingType.POSSIBLY_MISSING_ANTECEDENT:
                reason, candidate = possible[term]
                pointer = f"; possible antecedent: \"{candidate}\"" if candidate else ""
                message = (
                    f"Possibly missing antecedent basis?: \"{first.surface_form}\" in claim "
                    f"{claim_number} has no exact introduction{pointer}. {_REASONS[reason]}"
                )
                evidence = {
                    "reference": first.surface_form,
                    "normalized_term": term,
                    "possible_antecedent": candidate,
                    "reason": reason,
                    "occurrences": len(refs),
                }
                suggestion = (
                    f"Double-check. If \"{first.surface_form}\" is \"{candidate}\", use the "
                    f"same wording; otherwise introduce it first (e.g. \"{article} {term}\")."
                ) if candidate else (
                    f"Double-check; if it is a claimed element, introduce it first "
                    f"(e.g. \"{article} {term}\")."
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
                suggestion = (
                    f"Introduce the element first (e.g. \"{article} {term}\"), or "
                    f"change \"{first.surface_form}\" to refer to an element that is "
                    f"already recited."
                )

            findings.append(AntecedentFinding(
                type=problem,
                severity=severity,
                claim_number=claim_number,
                term=first.surface_form,
                message=message,
                suggestion=suggestion,
                location=locations[0],
                locations=locations,
                evidence=evidence,
            ))

    return findings
