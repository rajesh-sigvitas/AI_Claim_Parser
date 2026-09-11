"""
The standalone antecedent route reports antecedent errors only.

Limiting-preamble and singular/plural findings are advisory; they belong to the full
Claim Master report and must not appear here.
"""
import io

import fitz
from fastapi.testclient import TestClient

from app.analysis.antecedent.analyzer import ANTECEDENT_ERROR_TYPES, AntecedentAnalyzer
from app.analysis.models import FindingType
from app.document.loader import DocumentLoader
from app.main import app
from app.report.service import report_service

client = TestClient(app)

# Clean antecedent basis, but an independent-claim preamble that the full report questions.
PREAMBLE_ONLY = (
    "What is claimed is:\n"
    "1. A base assembly of a cleaning appliance, the base assembly comprising:\n"
    "a primary conduit; and\n"
    "a secondary conduit coupled to the primary conduit.\n"
)

# One missing antecedent ("the processor") and one reverse antecedent ("the controller").
WITH_ERRORS = (
    "What is claimed is:\n"
    "1. A system comprising:\n"
    "a memory coupled to the processor;\n"
    "a sensor configured to communicate with the controller; and\n"
    "a controller.\n"
)


def _post(path: str, text: str):
    return client.post(path, files={"file": ("claims.txt", io.BytesIO(text.encode()), "text/plain")})


def _pdf_text(content: bytes) -> str:
    with fitz.open(stream=content, filetype="pdf") as document:
        return "\n".join(page.get_text() for page in document)


def test_route_does_not_report_preamble_findings():
    response = _post("/api/v1/analyze/antecedents", PREAMBLE_ONLY)

    assert response.status_code == 200
    payload = response.json()
    assert payload["claim_count"] == 1
    assert payload["total_findings"] == 0
    assert payload["findings"] == []


def test_route_reports_missing_and_reverse_antecedents():
    response = _post("/api/v1/analyze/antecedents", WITH_ERRORS)

    assert response.status_code == 200
    found = {(f["type"], f["term"]) for f in response.json()["findings"]}
    assert found == {
        (FindingType.MISSING_ANTECEDENT.value, "the processor"),
        (FindingType.REVERSE_ANTECEDENT.value, "the controller"),
    }


def test_full_report_still_carries_the_advisory_checks():
    """The narrowing applies to the route only; section III of the CM report is unchanged."""
    report = report_service.build(PREAMBLE_ONLY.encode(), "claims.txt")
    assert any(f.type == FindingType.LIMITING_PREAMBLE for f in report.antecedents.findings)


def test_analyzer_errors_only_returns_antecedent_defects():
    claims = DocumentLoader(extract_figures=False).load(WITH_ERRORS.encode(), "c.txt").claims

    full = AntecedentAnalyzer().analyze(claims)
    errors = AntecedentAnalyzer().analyze(claims, errors_only=True)

    assert any(f.type == FindingType.LIMITING_PREAMBLE for f in full.findings)
    assert errors.findings
    assert all(f.type in ANTECEDENT_ERROR_TYPES for f in errors.findings)
    assert set(errors.summary) <= {t.value for t in ANTECEDENT_ERROR_TYPES}


def test_pdf_route_lists_only_antecedent_errors():
    response = _post("/api/v1/analyze/antecedents/pdf", WITH_ERRORS)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    text = _pdf_text(response.content)

    assert "Antecedent Analysis Report" in text
    assert "Missing antecedent basis" in text
    assert "Reverse antecedent" in text
    assert "Limiting preamble" not in text
    # A single-analysis report has no contents page or section numbering.
    assert "TABLE OF CONTENTS" not in text


def test_pdf_route_says_so_when_there_are_no_errors():
    response = _post("/api/v1/analyze/antecedents/pdf", PREAMBLE_ONLY)

    assert response.status_code == 200
    text = _pdf_text(response.content)
    assert "No antecedent or reverse antecedent errors found." in text
    assert "Limiting preamble" not in text
