"""
Orchestrates antecedent analysis over a parsed ClaimDocument.
"""
from collections import Counter
from typing import Dict, List, Tuple

from app.analysis.antecedent.claim_walker import iter_claim_blocks
from app.analysis.antecedent.plural_checker import check_number_agreement
from app.analysis.antecedent.preamble_checker import check_limiting_preamble
from app.analysis.antecedent.resolver import resolve_antecedents
from app.analysis.antecedent.term_extractor import extract_terms_from_text
from app.analysis.antecedent.term_registry import (
    INTRODUCTION,
    REFERENCE,
    Occurrence,
    TermRegistry,
)
from app.analysis.models import AntecedentAnalysisResult, AntecedentFinding, FindingType
from app.models.document import ClaimDocument

# Section III of the Claim Master report covers four checks.  Two are defects in
# the strict sense -- a reference with no antecedent basis, and a reference that
# precedes its own introduction -- and two are questions put to the drafter about
# preamble weight and number agreement.  The order here is the order they appear
# against a claim in the report.
_TYPE_ORDER = {
    FindingType.MISSING_ANTECEDENT: 0,
    FindingType.REVERSE_ANTECEDENT: 1,
    FindingType.LIMITING_PREAMBLE: 2,
    FindingType.SINGULAR_PLURAL: 3,
}

# The antecedent defects proper.  The standalone antecedent route reports only these;
# the Claim Master report adds the two advisory checks alongside them.
ANTECEDENT_ERROR_TYPES = (FindingType.MISSING_ANTECEDENT, FindingType.REVERSE_ANTECEDENT)


class AntecedentAnalyzer:
    """
    Builds the term registry for a document and resolves antecedent basis.

    Reports four finding types:

    ``MISSING_ANTECEDENT``
        "the X" / "said X" where X was never introduced in this claim or any
        claim it depends from.
    ``REVERSE_ANTECEDENT``
        "the X" appears earlier in the claim than the "a X" that introduces it.
    ``LIMITING_PREAMBLE``
        an element introduced in an independent claim's preamble, which may be
        given patentable weight (MPEP 2111.02).
    ``SINGULAR_PLURAL``
        one element recited in both the singular and the plural.
    """

    def build_registry(
        self, document: ClaimDocument
    ) -> Tuple[TermRegistry, Dict[Tuple[int, int], str]]:
        registry = TermRegistry(document)
        block_text: Dict[Tuple[int, int], str] = {}

        for claim in document.claims:
            for block in iter_claim_blocks(claim):
                block_text[(claim.number, block.index)] = block.text
                if not block.text:
                    continue

                for term in extract_terms_from_text(block.text):
                    registry.add(Occurrence(
                        normalized_term=term.normalized_term,
                        surface_form=term.surface_form,
                        determiner=term.determiner,
                        number=term.number,
                        claim_number=claim.number,
                        source=block.source,
                        kind=REFERENCE if term.is_reference else INTRODUCTION,
                        block_index=block.index,
                        char_start=term.start_index,
                        char_end=term.end_index,
                        is_implicit=term.is_implicit,
                        is_gerund=term.is_gerund,
                        spans=list(term.highlight_spans),
                    ))

        registry.finalize()
        return registry, block_text

    def analyze(
        self, document: ClaimDocument, errors_only: bool = False
    ) -> AntecedentAnalysisResult:
        """
        Resolves antecedent basis for every claim in ``document``.

        ``errors_only`` limits the result to the two antecedent defects.  The limiting
        preamble and number-agreement checks are questions for the drafter rather than
        antecedent errors, so the standalone antecedent analysis leaves them to the full
        Claim Master report.
        """
        if not document.claims:
            return AntecedentAnalysisResult(
                claim_count=0, total_findings=0, findings=[], summary={},
            )

        registry, block_text = self.build_registry(document)

        findings: List[AntecedentFinding] = resolve_antecedents(registry, block_text)
        if not errors_only:
            findings.extend(check_limiting_preamble(registry, block_text))
            findings.extend(check_number_agreement(registry, block_text))

        findings.sort(key=lambda f: (
            f.claim_number,
            _TYPE_ORDER.get(f.type, 99),
            f.location.element_index if f.location and f.location.element_index is not None else 0,
            f.location.char_start if f.location and f.location.char_start is not None else 0,
        ))

        summary = Counter(f.type.value for f in findings)

        return AntecedentAnalysisResult(
            status="success",
            analysis="antecedents",
            claim_count=document.claim_count,
            total_findings=len(findings),
            findings=findings,
            summary=dict(summary),
        )
