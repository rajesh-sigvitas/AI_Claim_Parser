from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FindingType(str, Enum):
    MISSING_ANTECEDENT = "MISSING_ANTECEDENT"
    # ClaimMaster's "possibly missing AB" (spec 3.2): no introduction supports the
    # reference, but one plausibly names the same element.  A warning to double-check.
    POSSIBLY_MISSING_ANTECEDENT = "POSSIBLY_MISSING_ANTECEDENT"
    REVERSE_ANTECEDENT = "REVERSE_ANTECEDENT"
    # ClaimMaster's "ambiguous AB" (spec 3.3): more than one recited element answers to
    # the reference, so it does not say which is meant.
    AMBIGUOUS_ANTECEDENT = "AMBIGUOUS_ANTECEDENT"
    SINGULAR_PLURAL = "SINGULAR_PLURAL"
    LIMITING_PREAMBLE = "LIMITING_PREAMBLE"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


# The tier each section III finding is reported at (spec section 3).
#
# A finding's type decides its tier, so the tier is looked up here rather than chosen at
# each construction site -- three checkers were hardcoding WARNING, which is how a
# limiting preamble came to be counted in the same breath as a missing antecedent.
#
# LIMITING_PREAMBLE is INFO, and is still raised for every preamble introduction.  Those
# are two separate questions, and the sources disagree on only one of them: the spec
# rates the finding INFO and would raise it only where the preamble term is re-used in
# the body, while both ClaimMaster ground truths flag every introduction.  The ground
# truth decides what is raised, the spec decides what it is worth, so "11 notes" no
# longer reads as eleven problems.
DEFAULT_SEVERITY: Dict["FindingType", "Severity"] = {}


DEFAULT_SEVERITY.update({
    FindingType.MISSING_ANTECEDENT: Severity.ERROR,
    FindingType.REVERSE_ANTECEDENT: Severity.ERROR,
    FindingType.AMBIGUOUS_ANTECEDENT: Severity.ERROR,
    FindingType.POSSIBLY_MISSING_ANTECEDENT: Severity.WARNING,
    FindingType.SINGULAR_PLURAL: Severity.WARNING,
    FindingType.LIMITING_PREAMBLE: Severity.INFO,
})


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
    severity_summary: Dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Finding counts keyed by Severity value, always carrying all three tiers. "
            "Kept separate from the total so that errors, warnings and notes are never "
            "added together into one headline (spec section 4)."
        ),
    )
    report_path: Optional[str] = Field(
        None, description="Path of the generated annotated report, when one was produced."
    )
