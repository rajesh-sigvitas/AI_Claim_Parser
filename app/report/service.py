"""
Assembles a Claim Master report from an uploaded document.

One entry point runs the modules that are ready and hands the results to the renderer.
Each analyser is run defensively: a failure in one section is recorded as a note and the
rest of the report is still produced, because a report missing section II is far more
useful than no report at all.

The standalone antecedent analysis is built here too, on the same loading path, so the
antecedent route and section III of the full report read the same claims the same way:
page-aware extraction, the claims section only, amendment markup resolved.
"""
import time
from typing import Optional

from loguru import logger

from app.analysis.antecedent.analyzer import AntecedentAnalyzer
from app.analysis.claim_errors.analyzer import ClaimErrorAnalyzer
from app.analysis.hierarchy.analyzer import HierarchyAnalyzer
from app.analysis.models import AntecedentAnalysisResult
from app.core.config import settings
from app.document.loader import DocumentLoader
from app.document.models import PatentDocument
from app.models.document import ClaimDocument
from app.report.cm_report_generator import CMReportGenerator
from app.report.models import CMReport


class ReportService:
    """Runs the report modules and renders the result."""

    def __init__(self):
        self.hierarchy_analyzer = HierarchyAnalyzer()
        self.claim_error_analyzer = ClaimErrorAnalyzer()
        self.antecedent_analyzer = AntecedentAnalyzer()

    # -- loading ------------------------------------------------------------

    def load(self, raw_input: bytes, filename: str, extract_figures: bool = False) -> PatentDocument:
        """
        The whole-document model for an upload.

        USPTO XML carries its claims already structured and has no pages to lay out, so it
        goes through the XML extractor and arrives as a document with claims but no pages.
        """
        if self._is_xml(raw_input, filename):
            from app.services.parser_service import parser_service

            document = PatentDocument(filename=filename)
            document.claims = parser_service.parse(raw_input, filename, generate_pdf=False)
            return document

        return DocumentLoader(extract_figures=extract_figures).load(raw_input, filename)

    @staticmethod
    def _is_xml(raw_input: bytes, filename: str) -> bool:
        if (filename or "").lower().endswith(".xml"):
            return True
        return raw_input.lstrip()[:5] == b"<?xml"

    # -- Claim Master report ------------------------------------------------

    def build(self, raw_input: bytes, filename: str, extract_figures: bool = False) -> CMReport:
        """Loads the document and runs every module that is available."""
        return self.build_from_document(self.load(raw_input, filename, extract_figures))

    def build_from_document(self, document: PatentDocument) -> CMReport:
        claims = document.claims
        report = self._new_report(document)

        report.hierarchy = self._run("I", lambda: self.hierarchy_analyzer.analyze(claims), report)
        report.claim_errors = self._run(
            "II", lambda: self.claim_error_analyzer.analyze(claims), report
        )
        report.antecedents = self._run(
            "III", lambda: self.antecedent_analyzer.analyze(claims) if claims else None, report
        )
        return report

    def generate_pdf(
        self, report: CMReport, output_dir: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> str:
        generator = CMReportGenerator(output_dir=output_dir or str(settings.OUTPUT_DIR))
        return generator.generate(report, output_path=output_path)

    def build_and_render(
        self, raw_input: bytes, filename: str, output_dir: Optional[str] = None
    ) -> tuple:
        report = self.build(raw_input, filename)
        return report, self.generate_pdf(report, output_dir=output_dir)

    # -- standalone antecedent analysis -------------------------------------

    def build_antecedent_report(self, raw_input: bytes, filename: str) -> CMReport:
        """Antecedent errors only, for the standalone antecedent route."""
        return self.antecedent_report_from_document(self.load(raw_input, filename))

    def antecedent_report_from_document(self, document: PatentDocument) -> CMReport:
        report = self._new_report(document)
        return self._fill_antecedent_report(report, document.claims)

    def antecedent_report_from_claims(self, claims: ClaimDocument, filename: str = "") -> CMReport:
        """The same, for callers that already hold a parsed claim set."""
        document = PatentDocument(filename=filename)
        document.claims = claims
        return self.antecedent_report_from_document(document)

    def _fill_antecedent_report(self, report: CMReport, claims: Optional[ClaimDocument]) -> CMReport:
        """
        Runs the antecedent checks in errors-only mode.

        The hierarchy is computed but not printed: it is what lets the report say, once,
        that a claim's missing antecedents all stem from an invalid parent reference.
        """
        if not claims or not claims.claims:
            report.antecedents = AntecedentAnalysisResult(
                claim_count=0, total_findings=0, findings=[], summary={},
            )
            return report

        report.hierarchy = self._run("I", lambda: self.hierarchy_analyzer.analyze(claims), report)
        report.antecedents = self._run(
            "III", lambda: self.antecedent_analyzer.analyze(claims, errors_only=True), report
        )
        return report

    def generate_antecedent_pdf(
        self, report: CMReport, output_dir: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> str:
        generator = CMReportGenerator(output_dir=output_dir or str(settings.OUTPUT_DIR))
        return generator.generate_antecedent_report(report, output_path=output_path)

    # -- shared -------------------------------------------------------------

    @staticmethod
    def _new_report(document: PatentDocument) -> CMReport:
        claims = document.claims
        return CMReport(
            document_name=document.filename,
            generated=time.strftime("%d %b %Y"),
            page_count=document.page_count,
            claim_count=claims.claim_count if claims else 0,
            claim_document=claims,
            cancelled_claims=[
                int(number)
                for number in ((claims.metadata or {}).get("cancelled_claims", []) if claims else [])
            ],
        )

    @staticmethod
    def _run(section: str, analyser, report: CMReport):
        """Runs one section's analyser, recording a note instead of failing the report."""
        try:
            return analyser()
        except Exception as error:                    # pragma: no cover - defensive
            logger.exception(f"Section {section} failed: {error}")
            report.notes[section] = f"Analysis failed: {error}"
            return None


report_service = ReportService()
