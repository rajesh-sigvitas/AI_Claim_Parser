from typing import Optional

from app.analysis.antecedent.analyzer import AntecedentAnalyzer
from app.analysis.models import AntecedentAnalysisResult
from app.models.document import ClaimDocument


class AnalysisService:
    def __init__(self):
        self.antecedent_analyzer = AntecedentAnalyzer()

    def analyze_antecedents(
        self, document: ClaimDocument, errors_only: bool = False
    ) -> AntecedentAnalysisResult:
        """
        Section III findings for a parsed document.

        By default this is the Claim Master scope: antecedent errors plus the limiting
        preamble and singular/plural questions.  ``errors_only`` narrows it to missing and
        reverse antecedents.
        """
        return self.antecedent_analyzer.analyze(document, errors_only=errors_only)

    def analyze_antecedent_errors(self, document: ClaimDocument) -> AntecedentAnalysisResult:
        """Missing and reverse antecedent errors only -- the standalone antecedent scope."""
        return self.analyze_antecedents(document, errors_only=True)

    def analyze_antecedents_with_report(
        self, document: ClaimDocument, output_dir: Optional[str] = None
    ) -> AntecedentAnalysisResult:
        """Antecedent errors, plus the standalone antecedent PDF recorded on ``report_path``."""
        from app.report.service import report_service

        report = report_service.antecedent_report_from_claims(document)
        report.antecedents.report_path = report_service.generate_antecedent_pdf(
            report, output_dir=output_dir
        )
        return report.antecedents


analysis_service = AnalysisService()
