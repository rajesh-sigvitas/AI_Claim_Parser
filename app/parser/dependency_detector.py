"""
Dependency Detector.
Determines whether a claim is independent or dependent, and resolves parent claims.
"""
import re
from typing import List, Optional
from app.parser.patterns import (
    DEPENDENCY_PATTERN,
    SINGLE_CLAIM_REF,
    RANGE_CLAIM_REF,
    LIST_CLAIM_REF,
)


class DependencyResult:
    """Result of dependency detection for a single claim."""
    __slots__ = ("is_independent", "parent_claims")

    def __init__(self, is_independent: bool, parent_claims: List[int]):
        self.is_independent = is_independent
        self.parent_claims = parent_claims


class DependencyDetector:
    """
    Determines whether a claim is independent or dependent.
    Extracts parent claim references supporting single, range, and list formats.
    """

    def detect(self, claim_text: str) -> DependencyResult:
        """
        Analyzes claim text and returns a DependencyResult.
        """
        parents: List[int] = []

        # 1. Check for range references first (e.g., "claims 1-5", "claims 1 through 5")
        range_match = RANGE_CLAIM_REF.search(claim_text)
        if range_match:
            start_num = int(range_match.group(1))
            end_num = int(range_match.group(2))
            parents.extend(range(start_num, end_num + 1))
            return DependencyResult(is_independent=False, parent_claims=parents)

        # 2. Check for explicit dependency patterns ("of claim 1", "according to claim 3")
        dep_match = DEPENDENCY_PATTERN.search(claim_text)
        if dep_match:
            parents.append(int(dep_match.group(1)))
            # Also check if there are additional claim refs in list form
            # e.g., "The method of claim 1 or claim 3"
            all_refs = SINGLE_CLAIM_REF.findall(claim_text)
            for ref_num in all_refs:
                num = int(ref_num)
                if num not in parents:
                    parents.append(num)
            return DependencyResult(is_independent=False, parent_claims=sorted(set(parents)))

        # 3. Check for any "claim N" reference (covers "The system of claim 1, ...")
        all_single = SINGLE_CLAIM_REF.findall(claim_text)
        if all_single:
            parents = sorted(set(int(n) for n in all_single))
            return DependencyResult(is_independent=False, parent_claims=parents)

        # No references found → independent
        return DependencyResult(is_independent=True, parent_claims=[])
