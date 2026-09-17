"""
User-supplied term-grouping overrides (spec section 5).

Where one noun phrase ends and the next begins is the hardest judgement the module
makes, and no rule set gets every drafting style right: "packet receiving device driver"
may come apart into "packet" and "device driver", and "server system controls" may be
grouped as one element when the claim means the server system.  The spec is blunt about
the consequence -- do not try to make the parser perfect without an override mechanism --
so the three overrides it asks for are read from one file and applied at the single point
where a phrase boundary is decided.

    {
      "force_group": ["packet receiving device driver"],
      "truncate":    ["server system"],
      "ignore":      ["the accompanying drawings"]
    }

``force_group``
    Keep the listed phrase whole wherever it starts a noun phrase.
``truncate``
    Where a phrase begins with the listed words and runs on, keep only the listed words.
    The spec writes this "server system // controls": the words after the marker are what
    the parser was wrongly pulling in.
``ignore``
    Drop the term entirely, so it is neither an introduction nor a reference.

Phrases are matched on words, not characters: case, hyphens and surrounding punctuation
do not matter, so "packet-receiving" matches "packet receiving".

The file is named by ``TERM_OVERRIDES_PATH``.  With no file configured every lookup
returns "no override", which is the behaviour the module had before this existed.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from loguru import logger

_SPLIT = re.compile(r"[^\w']+")


def phrase_words(phrase: str) -> Tuple[str, ...]:
    """A phrase as comparable words: lowercase, hyphens split, punctuation dropped."""
    return tuple(w for w in _SPLIT.split(phrase.lower().replace("-", " ")) if w)


@dataclass(frozen=True)
class TermOverrides:
    """The three spec section 5 overrides, as word tuples ready to match."""

    force_group: Tuple[Tuple[str, ...], ...] = ()
    truncate: Tuple[Tuple[str, ...], ...] = ()
    ignore: frozenset = field(default_factory=frozenset)

    @classmethod
    def empty(cls) -> "TermOverrides":
        return cls()

    @classmethod
    def from_dict(cls, data: Dict) -> "TermOverrides":
        def phrases(key: str) -> Tuple[Tuple[str, ...], ...]:
            listed = data.get(key) or []
            if isinstance(listed, str):
                listed = [listed]
            found = [phrase_words(p) for p in listed]
            # Longest first, so "server system controller" wins over "server system".
            return tuple(sorted({p for p in found if p}, key=len, reverse=True))

        return cls(
            force_group=phrases("force_group"),
            truncate=phrases("truncate"),
            ignore=frozenset(phrases("ignore")),
        )

    @classmethod
    def load(cls, path: Optional[Path]) -> "TermOverrides":
        if not path:
            return cls.empty()
        try:
            data = json.loads(Path(path).read_text())
        except Exception as error:
            # An unreadable override file must not take the analysis down with it.
            logger.warning(f"Term overrides at {path} could not be read ({error}); ignoring.")
            return cls.empty()
        overrides = cls.from_dict(data)
        logger.info(
            f"Term overrides loaded from {path}: {len(overrides.force_group)} force-group, "
            f"{len(overrides.truncate)} truncate, {len(overrides.ignore)} ignore."
        )
        return overrides

    @property
    def is_empty(self) -> bool:
        return not (self.force_group or self.truncate or self.ignore)

    # -- lookups -----------------------------------------------------------

    def forced_length(self, candidate_words: Sequence[str]) -> Optional[int]:
        """How many candidate words a force-group phrase claims here, if any."""
        return self._match(self.force_group, candidate_words)

    def truncated_length(self, candidate_words: Sequence[str]) -> Optional[int]:
        """How many candidate words to keep, where a truncate phrase starts here."""
        length = self._match(self.truncate, candidate_words)
        return length if length is not None and length < len(candidate_words) else None

    def is_ignored(self, words: Sequence[str]) -> bool:
        return bool(self.ignore) and phrase_words(" ".join(words)) in self.ignore

    @staticmethod
    def _match(
        phrases: Tuple[Tuple[str, ...], ...], candidate_words: Sequence[str]
    ) -> Optional[int]:
        """
        The number of *candidate words* a listed phrase covers from the start, or None.

        Matching runs over a flattened token stream so a hyphenated candidate can satisfy
        two phrase words, and only a match ending on a candidate boundary counts -- half
        of "packet-receiving" is not a phrase.
        """
        if not phrases:
            return None
        tokens: List[str] = []
        boundary: Dict[int, int] = {}
        for index, word in enumerate(candidate_words):
            tokens.extend(phrase_words(word))
            boundary[len(tokens)] = index + 1
        for phrase in phrases:
            if len(phrase) <= len(tokens) and tuple(tokens[:len(phrase)]) == phrase:
                covered = boundary.get(len(phrase))
                if covered:
                    return covered
        return None


# None until first use, so the file is read once, on whichever entry point runs first --
# the API, the report service, a test or a script -- with no startup wiring to forget.
_overrides: Optional[TermOverrides] = None


def active() -> TermOverrides:
    global _overrides
    if _overrides is None:
        _overrides = load_from_settings()
    return _overrides


def set_overrides(overrides: Optional[TermOverrides]) -> None:
    """Replaces the active overrides; None makes the next lookup reload from settings."""
    global _overrides
    _overrides = overrides


def load_from_settings() -> TermOverrides:
    from app.core.config import settings

    return TermOverrides.load(getattr(settings, "TERM_OVERRIDES_PATH", None))
