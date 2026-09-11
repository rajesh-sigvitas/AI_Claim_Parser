from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FindingType(str, Enum):
    MISSING_ANTECEDENT = "MISSING_ANTECEDENT"
    REVERSE_ANTECEDENT = "REVERSE_ANTECEDENT"
    SINGULAR_PLURAL = "SINGULAR_PLURAL"
    LIMITING_PREAMBLE = "LIMITING_PREAMBLE"


class Severity(str, Enum):
    WARNING = "WARNING"
    ERROR = "ERROR"


class FindingLocation(BaseModel):
    """
    Where a finding sits.

    ``element_index`` is the depth-first block index produced by
    :func:`app.analysis.antecedent.claim_walker.iter_claim_blocks` (-1 is the
    claim header).  ``char_start``/``char_end`` are offsets into that block's
    text, which is what lets the report highlight the exact words rather than
    string-replacing the first lookalike substring.
    """
    element_index: Optional[int] = None
    element_text: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    source: Optional[str] = None


class AntecedentFinding(BaseModel):
    type: FindingType
    severity: Severity = Severity.WARNING
    claim_number: int
    term: str
    message: str
    suggestion: Optional[str] = None
    # First occurrence, kept as a scalar for backwards compatibility.
    location: Optional[FindingLocation] = None
    # Every occurrence of the problem term, so all of them can be highlighted.
    locations: List[FindingLocation] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)


class AntecedentAnalysisResult(BaseModel):
    status: str = "success"
    analysis: str = "antecedents"
    claim_count: int
    total_findings: int
    findings: List[AntecedentFinding]
    summary: Dict[str, int] = Field(
        default_factory=dict,
        description="Finding counts keyed by FindingType value.",
    )
    report_path: Optional[str] = Field(
        None, description="Path of the generated annotated report, when one was produced."
    )
