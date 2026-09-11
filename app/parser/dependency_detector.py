"""
Dependency Detector.
Determines whether a claim is independent or dependent, and resolves parent claims.
"""
import re
from typing import List, Set

from app.parser.patterns import (
    CLAIM_REF_GROUP,
    CLAIM_REF_RANGE,
    DEPENDENCY_PATTERN,
)


class DependencyResult:
    """Result of dependency detection for a single claim."""
    __slots__ = ("is_independent", "parent_claims", "is_multiple_dependent", "conjunction")

    def __init__(
        self,
        is_independent: bool,
        parent_claims: List[int],
        is_multiple_dependent: bool = False,
        conjunction: str = "",
    ):
        self.is_independent = is_independent
        self.parent_claims = parent_claims
        self.is_multiple_dependent = is_multiple_dependent
        # "and" or "or" -- 35 U.S.C. 112(e) requires the alternative form.
        self.conjunction = conjunction


class DependencyDetector:
    """
    Determines whether a claim is independent or dependent.
    Extracts parent claim references supporting single, range, and list formats.
    """

    def detect(self, claim_text: str) -> DependencyResult:
        """
        Analyzes claim text and returns a DependencyResult.

        Every claim reference in the text contributes its numbers, so "claims 1 and 2",
        "claims 1-5" and "claim 1 or claim 3" all resolve to the full parent list rather
        than to whichever number happened to be matched first.
        """
        parents: Set[int] = set()
        conjunction = ""

        for match in CLAIM_REF_GROUP.finditer(claim_text):
            group = match.group(1)
            parents.update(self._expand(group))
            if not conjunction:
                if re.search(r"\bor\b", group, re.IGNORECASE):
                    conjunction = "or"
                elif re.search(r"\band\b", group, re.IGNORECASE):
                    conjunction = "and"

        if not parents:
            return DependencyResult(is_independent=True, parent_claims=[])

        ordered = sorted(parents)
        return DependencyResult(
            is_independent=False,
            parent_claims=ordered,
            is_multiple_dependent=len(ordered) > 1,
            conjunction=conjunction,
        )

    @staticmethod
    def _expand(group: str) -> Set[int]:
        """Turns "1, 3 and 5" or "1-4" into the set of claim numbers it names."""
        numbers: Set[int] = set()

        remainder = group
        for match in CLAIM_REF_RANGE.finditer(group):
            start, end = int(match.group(1)), int(match.group(2))
            if start <= end and end - start < 100:      # a sane range, not a typo
                numbers.update(range(start, end + 1))
                remainder = remainder.replace(match.group(0), " ")

        numbers.update(int(value) for value in re.findall(r"\d+", remainder))
        return numbers

    @staticmethod
    def has_explicit_dependency_phrase(claim_text: str) -> bool:
        """True for "of claim 1", "according to claim 3" and the like."""
        return bool(DEPENDENCY_PATTERN.search(claim_text))
