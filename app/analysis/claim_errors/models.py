"""
Types for section II of the report: claim errors and warnings.

An issue carries the authority it rests on (a CFR rule or an MPEP section) because that is
what makes the report actionable -- an attorney reading "claim 5 depends on claim 9, which
does not exist" wants the rule to quote back in a response.

Locations reuse :class:`~app.analysis.models.FindingLocation`, the same block/offset pair
the antecedent module produces, so one renderer can highlight both kinds of finding.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.analysis.models import FindingLocation, Severity


class ClaimIssueType(str, Enum):
    """Every defect section II reports."""

    # Dependency
    MISSING_PARENT = "MISSING_PARENT"
    SELF_DEPENDENT = "SELF_DEPENDENT"
    FORWARD_DEPENDENCY = "FORWARD_DEPENDENCY"
    DEPENDS_ON_CANCELLED = "DEPENDS_ON_CANCELLED"
    IMPROPER_MULTIPLE_DEPENDENT = "IMPROPER_MULTIPLE_DEPENDENT"
    MULTIPLE_DEPENDENT_CONJUNCTION = "MULTIPLE_DEPENDENT_CONJUNCTION"

    # Numbering
    DUPLICATE_CLAIM_NUMBER = "DUPLICATE_CLAIM_NUMBER"
    NON_SEQUENTIAL_NUMBERING = "NON_SEQUENTIAL_NUMBERING"
    NO_INDEPENDENT_CLAIM = "NO_INDEPENDENT_CLAIM"

    # Amendment
    AMENDED_WITHOUT_STATUS = "AMENDED_WITHOUT_STATUS"

    # Form
    MISSING_TRANSITION = "MISSING_TRANSITION"
    NO_TERMINAL_PERIOD = "NO_TERMINAL_PERIOD"
    INTERNAL_PERIOD = "INTERNAL_PERIOD"
    LOWERCASE_START = "LOWERCASE_START"
    REFERENCE_NUMERAL = "REFERENCE_NUMERAL"

    # Definiteness
    INDEFINITE_TERM = "INDEFINITE_TERM"
    OPTIONAL_LANGUAGE = "OPTIONAL_LANGUAGE"
    EXEMPLARY_LANGUAGE = "EXEMPLARY_LANGUAGE"
    TRADEMARK = "TRADEMARK"

    # Fees
    EXCESS_CLAIMS = "EXCESS_CLAIMS"
    EXCESS_INDEPENDENT_CLAIMS = "EXCESS_INDEPENDENT_CLAIMS"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def authority(self) -> str:
        """The rule the issue is grounded in, quoted in the report."""
        return _AUTHORITIES.get(self, "")


_LABELS = {
    ClaimIssueType.MISSING_PARENT: "Missing parent claim",
    ClaimIssueType.SELF_DEPENDENT: "Claim depends on itself",
    ClaimIssueType.FORWARD_DEPENDENCY: "Forward dependency",
    ClaimIssueType.DEPENDS_ON_CANCELLED: "Depends on a cancelled claim",
    ClaimIssueType.IMPROPER_MULTIPLE_DEPENDENT: "Improper multiple dependent claim",
    ClaimIssueType.MULTIPLE_DEPENDENT_CONJUNCTION: "Multiple dependency not in the alternative",
    ClaimIssueType.DUPLICATE_CLAIM_NUMBER: "Duplicate claim number",
    ClaimIssueType.NON_SEQUENTIAL_NUMBERING: "Claim numbering is not sequential",
    ClaimIssueType.NO_INDEPENDENT_CLAIM: "No independent claim",
    ClaimIssueType.AMENDED_WITHOUT_STATUS: "Amended claim without a matching status identifier",
    ClaimIssueType.MISSING_TRANSITION: "No transitional phrase",
    ClaimIssueType.NO_TERMINAL_PERIOD: "Claim does not end with a period",
    ClaimIssueType.INTERNAL_PERIOD: "Claim contains more than one sentence",
    ClaimIssueType.LOWERCASE_START: "Claim does not start with a capital letter",
    ClaimIssueType.REFERENCE_NUMERAL: "Reference numeral not in parentheses",
    ClaimIssueType.INDEFINITE_TERM: "Term of degree",
    ClaimIssueType.OPTIONAL_LANGUAGE: "Optional language",
    ClaimIssueType.EXEMPLARY_LANGUAGE: "Exemplary language",
    ClaimIssueType.TRADEMARK: "Trademark in a claim",
    ClaimIssueType.EXCESS_CLAIMS: "Excess claims fee",
    ClaimIssueType.EXCESS_INDEPENDENT_CLAIMS: "Excess independent claims fee",
}

_AUTHORITIES = {
    ClaimIssueType.MISSING_PARENT: "37 CFR 1.75(c)",
    ClaimIssueType.SELF_DEPENDENT: "37 CFR 1.75(c)",
    ClaimIssueType.FORWARD_DEPENDENCY: "37 CFR 1.75(c); MPEP 608.01(n)",
    ClaimIssueType.DEPENDS_ON_CANCELLED: "37 CFR 1.75(c)",
    ClaimIssueType.IMPROPER_MULTIPLE_DEPENDENT: "35 U.S.C. 112(e); MPEP 608.01(n)",
    ClaimIssueType.MULTIPLE_DEPENDENT_CONJUNCTION: "35 U.S.C. 112(e); MPEP 608.01(n)",
    ClaimIssueType.DUPLICATE_CLAIM_NUMBER: "37 CFR 1.126",
    ClaimIssueType.NON_SEQUENTIAL_NUMBERING: "37 CFR 1.126",
    ClaimIssueType.NO_INDEPENDENT_CLAIM: "35 U.S.C. 112(b)",
    ClaimIssueType.AMENDED_WITHOUT_STATUS: "37 CFR 1.121(c)",
    ClaimIssueType.MISSING_TRANSITION: "MPEP 2111.03",
    ClaimIssueType.NO_TERMINAL_PERIOD: "37 CFR 1.75(i); MPEP 608.01(m)",
    ClaimIssueType.INTERNAL_PERIOD: "MPEP 608.01(m)",
    ClaimIssueType.LOWERCASE_START: "MPEP 608.01(m)",
    ClaimIssueType.REFERENCE_NUMERAL: "37 CFR 1.75(d)(1); MPEP 608.01(m)",
    ClaimIssueType.INDEFINITE_TERM: "35 U.S.C. 112(b); MPEP 2173.05(b)",
    ClaimIssueType.OPTIONAL_LANGUAGE: "35 U.S.C. 112(b); MPEP 2173.05(h)",
    ClaimIssueType.EXEMPLARY_LANGUAGE: "35 U.S.C. 112(b); MPEP 2173.05(d)",
    ClaimIssueType.TRADEMARK: "MPEP 2173.05(u)",
    ClaimIssueType.EXCESS_CLAIMS: "37 CFR 1.16(i)",
    ClaimIssueType.EXCESS_INDEPENDENT_CLAIMS: "37 CFR 1.16(h)",
}


class ClaimIssue(BaseModel):
    """One error or warning against one claim (or against the claim set)."""

    type: ClaimIssueType
    severity: Severity = Severity.WARNING
    claim_number: Optional[int] = None       # None for claim-set-wide issues
    message: str
    suggestion: Optional[str] = None
    term: str = ""                           # the words the issue is about, when it has any
    location: Optional[FindingLocation] = None
    locations: List[FindingLocation] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return self.type.label

    @property
    def authority(self) -> str:
        return self.type.authority


class ClaimErrorResult(BaseModel):
    """Section II of the report."""

    claim_count: int = 0
    total_issues: int = 0
    errors: int = 0
    warnings: int = 0
    issues: List[ClaimIssue] = Field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.issues
