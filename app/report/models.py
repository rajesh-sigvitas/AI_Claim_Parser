"""
The Claim Master report as data.

The report has eight numbered sections and they are built over several releases, so the
container holds each one optionally.  A section whose analyser has not run is *pending*
and says so in the table of contents -- it is never silently omitted, because a reader
comparing two reports has to be able to tell "nothing found" from "not checked".
"""
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.analysis.claim_errors.models import ClaimErrorResult
from app.analysis.hierarchy.models import HierarchyResult
from app.analysis.models import AntecedentAnalysisResult
from app.models.document import ClaimDocument


class ReportSection(str, Enum):
    """The eight sections, in the order they are printed."""

    CLAIMS_HIERARCHY = "I"
    CLAIM_ERRORS = "II"
    ANTECEDENTS = "III"
    SPECIFICATION_SUPPORT = "IV"
    PART_NAMES = "V"
    FIGURE_PARTS = "VI"
    ACRONYMS = "VII"
    LANGUAGE = "VIII"

    @property
    def title(self) -> str:
        return _TITLES[self]


_TITLES = {
    ReportSection.CLAIMS_HIERARCHY: "Claims Hierarchy",
    ReportSection.CLAIM_ERRORS: "Claim Errors and Warnings",
    ReportSection.ANTECEDENTS: "Antecedents Errors/Warnings",
    ReportSection.SPECIFICATION_SUPPORT:
        "Claim Terms and Words Having No or Limited Support in the Specification",
    ReportSection.PART_NAMES: "Inconsistent Part Names and Numbers",
    ReportSection.FIGURE_PARTS: "Inconsistent Part Numbers in Figures",
    ReportSection.ACRONYMS: "Inconsistent Acronyms",
    ReportSection.LANGUAGE: "Document Language Warnings",
}


class CMReport(BaseModel):
    """Everything one report needs to render."""

    document_name: str = ""
    generated: str = ""
    page_count: int = 0
    claim_count: int = 0

    # The parsed claims, so section III can print each claim beside its findings.
    claim_document: Optional[ClaimDocument] = None

    hierarchy: Optional[HierarchyResult] = None
    claim_errors: Optional[ClaimErrorResult] = None
    antecedents: Optional[AntecedentAnalysisResult] = None
    # Sections IV-VIII arrive with the specification modules.

    cancelled_claims: List[int] = Field(default_factory=list)
    notes: Dict[str, str] = Field(default_factory=dict)

    def result_for(self, section: ReportSection):
        return {
            ReportSection.CLAIMS_HIERARCHY: self.hierarchy,
            ReportSection.CLAIM_ERRORS: self.claim_errors,
            ReportSection.ANTECEDENTS: self.antecedents,
        }.get(section)

    def is_pending(self, section: ReportSection) -> bool:
        """True when the section's analyser has not run for this report."""
        return self.result_for(section) is None
