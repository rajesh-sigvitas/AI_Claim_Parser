"""
A verb read as the last word of a noun phrase.

"a second software component points to the lowest level page table" is extracted as
the term "second software component points", and "the buoyant body floats on the water
surface" as "buoyant body floats".  An -s verb and a plural noun are spelled alike, so the
term extractor cannot tell them apart from the words alone; this module decides it from
the whole claim set, for introductions and references alike.

The last word is taken as the clause's verb only when both of these hold:

* the next word is one a verb takes but a noun phrase does not end on -- a preposition,
  a determiner or an -ly adverb ("points to", "floats on"; never "pads are");
* the word is not used as a noun anywhere in the claim set.  A use counts unless it is
  itself such a verb-like last word, or the leading word of a determiner-less phrase at
  a verb position ("to indicate ownership").

What happens with the shorter term is the caller's decision: the resolver only uses it
to find support for a reference that has none as written, so a genuinely new element
("the motor pads are ...") is still reported.
"""
import re
from typing import Dict, Optional, Set, Tuple

from app.analysis.antecedent.lexicon import (
    ALL_DETERMINERS,
    NOMINAL_ING_ED,
    PREPOSITIONS,
    is_adverb,
    is_plural_form,
)
from app.analysis.antecedent.term_match import term_key
from app.analysis.antecedent.term_normalizer import singularize
from app.analysis.antecedent.term_registry import Occurrence, TermRegistry

_DETERMINER_WORDS = {determiner.split()[0] for determiner in ALL_DETERMINERS}
_NEXT_WORD = re.compile(r"\s*([A-Za-z][\w-]*)")


class SwallowedVerbs:
    """Which occurrences end in a verb, computed once per claim set."""

    def __init__(self, registry: TermRegistry, block_text: Dict[Tuple[int, int], str]):
        self._block_text = block_text
        occurrences = [
            o for claim_occurrences in registry.occurrences_by_claim.values()
            for o in claim_occurrences
        ]

        self._verb_like: Dict[int, str] = {}
        for occurrence in occurrences:
            word = self._verb_like_last_word(occurrence)
            if word:
                self._verb_like[id(occurrence)] = word

        self._noun_uses: Set[str] = set()
        for occurrence in occurrences:
            words = occurrence.normalized_term.split()
            if id(occurrence) in self._verb_like:
                words = words[:-1]
            if occurrence.is_implicit and len(words) > 1:
                # A bare phrase may open with its verb ("indicate ownership"); its head
                # is still a noun use ("mappings of addresses" -> "mapping").
                head, _ = term_key(" ".join(words))
                words = words[1:] + [head]
            self._noun_uses.update(singularize(w) for w in words if w)

    def trimmed(self, occurrence: Occurrence) -> Optional[str]:
        """The normalized term without its verb, or None when its last word is a noun."""
        word = self._verb_like.get(id(occurrence))
        if word is None or singularize(word) in self._noun_uses:
            return None
        return " ".join(occurrence.normalized_term.split()[:-1])

    def _verb_like_last_word(self, occurrence: Occurrence) -> Optional[str]:
        words = occurrence.normalized_term.split()
        surface = occurrence.surface_form.split()
        if len(words) < 2 or not surface:
            return None

        last = re.sub(r"[^\w]", "", surface[-1]).lower()
        if not last.isalpha() or not is_plural_form(last) or last in NOMINAL_ING_ED:
            return None

        text = self._block_text.get((occurrence.claim_number, occurrence.block_index), "")
        following = _NEXT_WORD.match(text, occurrence.char_end)
        if not following:
            return None
        next_word = following.group(1).lower()
        if next_word in PREPOSITIONS or next_word in _DETERMINER_WORDS or is_adverb(next_word):
            return last
        return None
