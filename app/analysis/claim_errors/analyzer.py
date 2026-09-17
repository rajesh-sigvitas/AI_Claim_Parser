"""
Section II: runs every claim check and orders the results.

Ordering is by claim number, then by severity, so a reader working through the report
meets a claim's errors before its warnings and never has to jump back and forth.
"""
from typing import List, Optional, Set

from app.analysis.claim_errors import checks
from app.analysis.claim_errors.models import ClaimErrorResult, ClaimIssue
from app.analysis.models import Severity
from app.models.document import ClaimDocument

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


class ClaimErrorAnalyzer:
    """Produces section II of the report."""

    def analyze(self, document: Optional[ClaimDocument]) -> ClaimErrorResult:
        if document is None or not document.claims:
            return ClaimErrorResult()

        numbers: Set[int] = {claim.number for claim in document.claims}
        cancelled: Set[int] = {
            int(number) for number in (document.metadata or {}).get("cancelled_claims", [])
        }
        multiple_dependents: Set[int] = {
            claim.number for claim in document.claims
            if len(checks._parents(claim)) > 1
        }

        issues: List[ClaimIssue] = list(checks.check_claim_set(document))

        for claim in document.claims:
            issues.extend(checks.check_dependencies(claim, numbers, cancelled, multiple_dependents))
            issues.extend(checks.check_amendment_status(claim))
            issues.extend(checks.check_form(claim))
            issues.extend(checks.check_language(claim))
            issues.extend(checks.check_reference_numerals(claim))

        issues.sort(key=lambda issue: (
            issue.claim_number if issue.claim_number is not None else -1,
            _SEVERITY_ORDER.get(issue.severity, 9),
            issue.type.value,
        ))

        return ClaimErrorResult(
            claim_count=document.claim_count,
            total_issues=len(issues),
            errors=sum(1 for issue in issues if issue.severity == Severity.ERROR),
            warnings=sum(1 for issue in issues if issue.severity == Severity.WARNING),
            issues=issues,
        )
