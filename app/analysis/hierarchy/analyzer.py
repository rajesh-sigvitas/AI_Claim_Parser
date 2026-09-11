"""
Section I: builds the claim trees.

A claim's parents come from the parser (``metadata["parent_claims"]``, else
``parent_claim``).  This module decides which of those parents are *legal* -- 37 CFR
1.75(c) allows a dependent claim to refer only to a preceding claim -- and lays the
survivors out as trees, one per independent claim.

A claim with no valid parent still has to appear somewhere, so it roots a tree of its own
and is listed as an orphan.  Dropping it would hide exactly the claim the reader most
needs to see.
"""
from collections import deque
from typing import Dict, List, Optional

from app.analysis.hierarchy.classifier import classify, split_status_marker
from app.analysis.hierarchy.models import (
    ClaimCategory,
    ClaimNode,
    ClaimStatus,
    ClaimTree,
    HierarchyResult,
    ParentIssue,
)
from app.core.constants import ClaimType
from app.models.claim import Claim
from app.models.document import ClaimDocument


class HierarchyAnalyzer:
    """Produces the claim-tree data the report draws."""

    def analyze(self, document: Optional[ClaimDocument]) -> HierarchyResult:
        if document is None or not document.claims:
            return HierarchyResult()

        nodes = {claim.number: self._build_node(claim) for claim in document.claims}
        self._validate_parents(nodes)
        self._link_children(nodes)

        trees = self._build_trees(nodes)
        orphans = [
            number for number, node in sorted(nodes.items())
            if not node.is_independent and not self._valid_parents(node)
        ]

        return HierarchyResult(
            claim_count=len(nodes),
            independent_claims=sorted(n.number for n in nodes.values() if n.is_independent),
            dependent_claims=sorted(n.number for n in nodes.values() if not n.is_independent),
            nodes=nodes,
            trees=trees,
            orphans=orphans,
            categories_used=self._ordered_categories(nodes),
            statuses_used=self._ordered_statuses(nodes),
        )

    # -- nodes --------------------------------------------------------------

    def _build_node(self, claim: Claim) -> ClaimNode:
        status, preamble = split_status_marker(claim.header or "")
        if status is None:
            status, _ = split_status_marker(claim.claim_text or "")

        parents = self._declared_parents(claim)
        return ClaimNode(
            number=claim.number,
            category=classify(preamble, claim.claim_text or preamble),
            status=status,
            is_independent=claim.claim_type == ClaimType.INDEPENDENT and not parents,
            parents=parents,
            is_multiple_dependent=len(parents) > 1,
            preamble=preamble.strip(),
            page=claim.metadata.get("page") if claim.metadata else None,
            line=claim.metadata.get("line") if claim.metadata else None,
        )

    @staticmethod
    def _declared_parents(claim: Claim) -> List[int]:
        if claim.metadata and claim.metadata.get("parent_claims"):
            return sorted({int(p) for p in claim.metadata["parent_claims"]})
        if claim.parent_claim is not None:
            return [int(claim.parent_claim)]
        return []

    # -- validation ---------------------------------------------------------

    def _validate_parents(self, nodes: Dict[int, ClaimNode]) -> None:
        for number, node in nodes.items():
            for parent in node.parents:
                if parent == number:
                    node.parent_issues[parent] = ParentIssue.SELF_REFERENCE
                elif parent not in nodes:
                    node.parent_issues[parent] = ParentIssue.MISSING_CLAIM
                elif parent > number:
                    node.parent_issues[parent] = ParentIssue.FORWARD_REFERENCE

        # A cycle can survive the checks above only through a forward reference, but a
        # renumbered amendment can still produce one, and it would hang the layout.
        for number, node in nodes.items():
            if self._reaches_itself(number, nodes):
                for parent in self._valid_parents(node):
                    node.parent_issues[parent] = ParentIssue.CIRCULAR

    @staticmethod
    def _valid_parents(node: ClaimNode) -> List[int]:
        return [p for p in node.parents if p not in node.parent_issues]

    def _reaches_itself(self, start: int, nodes: Dict[int, ClaimNode]) -> bool:
        seen = set()
        queue = deque(self._valid_parents(nodes[start]))
        while queue:
            current = queue.popleft()
            if current == start:
                return True
            if current in seen or current not in nodes:
                continue
            seen.add(current)
            queue.extend(self._valid_parents(nodes[current]))
        return False

    # -- structure ----------------------------------------------------------

    def _link_children(self, nodes: Dict[int, ClaimNode]) -> None:
        for number, node in sorted(nodes.items()):
            for parent in self._valid_parents(node):
                nodes[parent].children.append(number)

    def _build_trees(self, nodes: Dict[int, ClaimNode]) -> List[ClaimTree]:
        roots = [
            number for number, node in sorted(nodes.items())
            if node.is_independent or not self._valid_parents(node)
        ]

        trees: List[ClaimTree] = []
        for root in roots:
            members: List[int] = []
            max_depth = 0
            queue = deque([(root, 0)])
            seen = {root}

            while queue:
                number, depth = queue.popleft()
                members.append(number)
                max_depth = max(max_depth, depth)
                nodes[number].depth = max(nodes[number].depth, depth)

                for child in nodes[number].children:
                    # A multiple dependent claim hangs under each of its parents; it is
                    # drawn in every tree it belongs to, but never twice in one.
                    if child not in seen:
                        seen.add(child)
                        queue.append((child, depth + 1))

            trees.append(ClaimTree(root=root, nodes=members, max_depth=max_depth))
        return trees

    # -- legend -------------------------------------------------------------

    @staticmethod
    def _ordered_categories(nodes: Dict[int, ClaimNode]) -> List[ClaimCategory]:
        order = list(ClaimCategory)
        used = {node.category for node in nodes.values()}
        return [category for category in order if category in used]

    @staticmethod
    def _ordered_statuses(nodes: Dict[int, ClaimNode]) -> List[ClaimStatus]:
        order = list(ClaimStatus)
        used = {node.status for node in nodes.values() if node.status}
        return [status for status in order if status in used]
