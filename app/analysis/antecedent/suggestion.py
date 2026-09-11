"""
Human-readable remediation text for a finding.

Checkers now build a specific suggestion while they still have the surrounding
occurrences in hand; this module supplies the generic wording used when a
finding carries none.
"""
from typing import Optional

from app.analysis.models import AntecedentFinding, FindingType

_FALLBACKS = {
    FindingType.MISSING_ANTECEDENT:
        "Introduce this element with an indefinite article before referring to it.",
    FindingType.REVERSE_ANTECEDENT:
        "Reorder the limitations so the element is introduced before it is referenced.",
    FindingType.SINGULAR_PLURAL:
        "Align the grammatical number of the reference with its introduction.",
    FindingType.LIMITING_PREAMBLE:
        "Review whether the preamble term is intended to limit the claim.",
}


class SuggestionGenerator:
    @staticmethod
    def generate(finding: AntecedentFinding) -> Optional[str]:
        if finding.suggestion:
            return finding.suggestion
        return _FALLBACKS.get(finding.type)
