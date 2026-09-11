"""
Types for section I of the report: the claim trees.

The report draws a claim tree per independent claim and colours each node by what kind of
claim it is, so both facts -- the shape of the dependency graph and the statutory type of
every claim -- belong to this module.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ClaimCategory(str, Enum):
    """
    The statutory claim types the report legend distinguishes, plus the two special
    drafting forms that get their own colour.
    """

    METHOD = "METHOD"                       # method / process
    APPARATUS = "APPARATUS"                 # apparatus / device / system
    COMPOSITION = "COMPOSITION"             # composition of matter
    ARTICLE = "ARTICLE"                     # article of manufacture, CRM, kit
    MEANS_PLUS_FUNCTION = "MEANS_PLUS_FUNCTION"   # 35 U.S.C. 112(f), pre-AIA 112(6)
    PRODUCT_BY_PROCESS = "PRODUCT_BY_PROCESS"
    JEPSON = "JEPSON"
    UNKNOWN = "UNKNOWN"

    @property
    def label(self) -> str:
        return _CATEGORY_LABELS[self]

    @property
    def color(self) -> str:
        """Node fill used in the tree drawing."""
        return _CATEGORY_COLORS[self]


_CATEGORY_LABELS = {
    ClaimCategory.METHOD: "Method/process",
    ClaimCategory.APPARATUS: "Apparatus/device",
    ClaimCategory.COMPOSITION: "Composition",
    ClaimCategory.ARTICLE: "Article of manufacture",
    ClaimCategory.MEANS_PLUS_FUNCTION: "112(6)",
    ClaimCategory.PRODUCT_BY_PROCESS: "Product by process",
    ClaimCategory.JEPSON: "Jepson",
    ClaimCategory.UNKNOWN: "Unclassified",
}

# The colour is drawn as the node's outline, not its fill: the fill carries the
# independent/dependent distinction (grey vs white), so the type has to live in the
# stroke.  Saturated values, because a hairline ellipse in a pastel is invisible in print.
_CATEGORY_COLORS = {
    ClaimCategory.METHOD: "#1E9E4A",              # green
    ClaimCategory.APPARATUS: "#E58A1F",           # orange
    ClaimCategory.COMPOSITION: "#E8607A",         # rose
    ClaimCategory.ARTICLE: "#B0202F",             # dark red
    ClaimCategory.MEANS_PLUS_FUNCTION: "#7B4FCF",  # violet
    ClaimCategory.PRODUCT_BY_PROCESS: "#17A2A2",  # teal
    ClaimCategory.JEPSON: "#E79BC0",              # light pink
    ClaimCategory.UNKNOWN: "#8C8C8C",
}


class ClaimStatus(str, Enum):
    """
    Amendment status of a claim, as marked in an amendment paper.

    The bracket codes are the ones printed beside the claim numbers in the tree.
    """

    ORIGINAL = "O"
    PREVIOUSLY_PRESENTED = "PP"
    CURRENTLY_AMENDED = "CA"
    NEW = "N"
    CANCELLED = "X"
    WITHDRAWN = "W"
    WITHDRAWN_AND_AMENDED = "WA"
    NOT_ENTERED = "NE"

    @property
    def label(self) -> str:
        return _STATUS_LABELS[self]


_STATUS_LABELS = {
    ClaimStatus.ORIGINAL: "Original",
    ClaimStatus.PREVIOUSLY_PRESENTED: "Previously Presented",
    ClaimStatus.CURRENTLY_AMENDED: "Currently Amended",
    ClaimStatus.NEW: "New",
    ClaimStatus.CANCELLED: "Cancelled",
    ClaimStatus.WITHDRAWN: "Withdrawn",
    ClaimStatus.WITHDRAWN_AND_AMENDED: "Withdrawn and Amended",
    ClaimStatus.NOT_ENTERED: "Not Entered",
}


class ParentIssue(str, Enum):
    """Why a claim's dependency is invalid -- the reason a node is drawn dotted."""

    MISSING_CLAIM = "MISSING_CLAIM"          # depends on a claim that does not exist
    FORWARD_REFERENCE = "FORWARD_REFERENCE"  # depends on a later-numbered claim
    SELF_REFERENCE = "SELF_REFERENCE"
    CIRCULAR = "CIRCULAR"


class ClaimNode(BaseModel):
    """One claim in the tree."""

    number: int
    category: ClaimCategory = ClaimCategory.UNKNOWN
    status: Optional[ClaimStatus] = None
    is_independent: bool = True
    parents: List[int] = Field(default_factory=list)
    children: List[int] = Field(default_factory=list)
    depth: int = 0
    is_multiple_dependent: bool = False
    parent_issues: Dict[int, ParentIssue] = Field(
        default_factory=dict,
        description="Invalid parent claim number -> why it is invalid.",
    )
    preamble: str = ""
    page: Optional[int] = None
    line: Optional[int] = None

    @property
    def has_invalid_parent(self) -> bool:
        return bool(self.parent_issues)

    @property
    def display(self) -> str:
        """"12 [CA]" -- what the tree node prints."""
        return f"{self.number} [{self.status.value}]" if self.status else str(self.number)


class ClaimTree(BaseModel):
    """One independent claim and everything that depends from it."""

    root: int
    nodes: List[int] = Field(default_factory=list, description="Claim numbers, breadth-first.")
    max_depth: int = 0


class HierarchyResult(BaseModel):
    """Section I of the report."""

    claim_count: int = 0
    independent_claims: List[int] = Field(default_factory=list)
    dependent_claims: List[int] = Field(default_factory=list)
    nodes: Dict[int, ClaimNode] = Field(default_factory=dict)
    trees: List[ClaimTree] = Field(default_factory=list)
    orphans: List[int] = Field(
        default_factory=list,
        description="Claims whose parent could not be resolved, so they root their own tree.",
    )
    categories_used: List[ClaimCategory] = Field(default_factory=list)
    statuses_used: List[ClaimStatus] = Field(default_factory=list)

    def node(self, number: int) -> Optional[ClaimNode]:
        return self.nodes.get(number)

    @property
    def invalid_parent_claims(self) -> List[int]:
        return sorted(n.number for n in self.nodes.values() if n.has_invalid_parent)
