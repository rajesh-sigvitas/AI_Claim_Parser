"""
Claim Master report: sections I-III and the pipeline that feeds them.

The fixtures are plain text so the tests do not need LibreOffice: the loader paginates
text synthetically, which exercises the same section detection, claim parsing and
analysis path a .docx takes after conversion.
"""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis.claim_errors import ClaimErrorAnalyzer
from app.analysis.claim_errors.models import ClaimIssueType
from app.analysis.hierarchy import HierarchyAnalyzer
from app.analysis.hierarchy.models import ClaimCategory, ClaimStatus, ParentIssue
from app.analysis.hierarchy.classifier import classify, split_status_marker
from app.document.loader import DocumentLoader
from app.document.models import SectionKind
from app.main import app
from app.parser.claim_splitter import ClaimSplitter
from app.report.service import report_service

client = TestClient(app)


SIMPLE_DOCUMENT = """FIELD
The disclosure relates to cleaning appliances.

BACKGROUND
Conventional extractors use a single nozzle.

DETAILED DESCRIPTION
The base assembly 102 includes a primary suction conduit 106-1.

What is claimed is:
1. A base assembly comprising:
a primary suction conduit; and
a secondary suction conduit.
2. The base assembly of claim 1, wherein the primary suction conduit is curved.
3. A method of cleaning a surface, the method comprising:
moving the base assembly of claim 1 across the surface.

ABSTRACT
A base assembly with two suction conduits.
"""


def load(text: str, name: str = "sample.txt"):
    return DocumentLoader(extract_figures=False).load(text.encode("utf-8"), name)


# -- document foundation ----------------------------------------------------


def test_loader_finds_sections_and_numbers_lines():
    document = load(SIMPLE_DOCUMENT)

    kinds = {section.kind for section in document.sections}
    assert SectionKind.CLAIMS in kinds
    assert SectionKind.DETAILED_DESCRIPTION in kinds
    assert SectionKind.ABSTRACT in kinds

    # Every line carries a resolvable citation.
    first = document.lines[0]
    assert first.page == 1 and first.number == 1
    assert first.citation == "[Page 1, line 1]"

    # The claims are parsed out of the claims section only.
    assert document.claims is not None
    assert document.claims.claim_count == 3


def test_specification_excludes_claims():
    document = load(SIMPLE_DOCUMENT)
    specification = document.specification_text
    assert "Conventional extractors" in specification
    assert "What is claimed is" not in specification


# -- amendment markup -------------------------------------------------------


def test_splitter_reads_bracketed_claim_numbers():
    """
    "[12.]" and "12.[13.]" are how a tracked-change rendering shows automatic numbers.
    Both are claim starts, the bracketed number is the claim's number, and nothing about
    brackets makes a claim cancelled.  (A misreading of this rendering once reported
    two live claims as cancelled and a valid dependency as a self-reference.)
    """
    text = (
        "11. The method of claim 1, wherein a is b.\n"
        "[12.] The method of claim 1, wherein c is d.\n"
        "12.[13.] The method of claim 1, wherein e is f.\n"
    )
    claims = ClaimSplitter().split(text)

    assert [(c.number, c.rendered_number, c.deleted) for c in claims] == [
        (11, None, False),
        (12, None, False),
        (13, 12, False),
    ]


def test_bracketed_claim_is_not_merged_into_the_previous_claim():
    document = load(
        "What is claimed is:\n"
        "1. A system comprising a processor.\n"
        "[2.] The system of claim 1, further comprising a widget.\n"
        "2.[3.] The system of claim 1, wherein the processor is fast.\n"
    )
    claims = {claim.number: claim for claim in document.claims.claims}

    assert sorted(claims) == [1, 2, 3]
    assert "widget" not in claims[1].claim_text
    assert claims[3].metadata["rendered_number"] == 2
    assert "cancelled_claims" not in document.claims.metadata


def test_canceled_status_cancels_a_claim_without_breaking_the_sequence():
    """37 CFR 1.121(c): a cancelled claim keeps its number and reads "(Canceled)"."""
    document = load(
        "What is claimed is:\n"
        "1. A system comprising a processor.\n"
        "2. (Canceled)\n"
        "3. The system of claim 1, wherein the processor is fast.\n"
    )
    claims = {claim.number: claim for claim in document.claims.claims}

    assert sorted(claims) == [1, 3]
    assert document.claims.metadata["cancelled_claims"] == [2]
    issues = ClaimErrorAnalyzer().analyze(document.claims).issues
    assert not [i for i in issues if i.type == ClaimIssueType.NON_SEQUENTIAL_NUMBERING]


@pytest.mark.parametrize("marker,expected", [
    ("(Original) A method of doing.", ClaimStatus.ORIGINAL),
    ("(Currently Amended) A method.", ClaimStatus.CURRENTLY_AMENDED),
    ("(Previously Presented) A method.", ClaimStatus.PREVIOUSLY_PRESENTED),
    ("(New) A method.", ClaimStatus.NEW),
    ("(Withdrawn) A method.", ClaimStatus.WITHDRAWN),
])
def test_status_markers_are_split_off_the_claim_text(marker, expected):
    status, remainder = split_status_marker(marker)
    assert status == expected
    assert remainder.startswith("A method")


# -- I. hierarchy -----------------------------------------------------------


def test_hierarchy_builds_trees_and_classifies_claims():
    document = load(SIMPLE_DOCUMENT)
    result = HierarchyAnalyzer().analyze(document.claims)

    assert result.claim_count == 3
    assert result.independent_claims == [1]
    assert result.node(1).category == ClaimCategory.APPARATUS
    assert result.node(3).category == ClaimCategory.METHOD
    assert result.node(2).parents == [1]
    assert 2 in result.node(1).children


@pytest.mark.parametrize("preamble,text,expected", [
    ("A method of making a widget, comprising", "", ClaimCategory.METHOD),
    ("An apparatus comprising", "", ClaimCategory.APPARATUS),
    ("A composition comprising", "", ClaimCategory.COMPOSITION),
    ("A non-transitory computer-readable medium storing instructions", "",
     ClaimCategory.ARTICLE),
    ("An apparatus comprising", "an apparatus comprising means for filtering a signal",
     ClaimCategory.MEANS_PLUS_FUNCTION),
    ("A widget", "A widget produced by the process of claim 1",
     ClaimCategory.PRODUCT_BY_PROCESS),
    ("A machine", "A machine, wherein the improvement comprises a brake",
     ClaimCategory.JEPSON),
])
def test_claim_category_classification(preamble, text, expected):
    assert classify(preamble, text or preamble) == expected


def test_dependent_claim_is_classified_by_its_own_preamble():
    # "The method of claim 1" is a method claim even though claim 1 is an apparatus.
    assert classify("The method of claim 1, wherein the apparatus is heated") == ClaimCategory.METHOD


def test_invalid_parents_are_detected():
    document = load(
        "What is claimed is:\n"
        "1. A system comprising a processor.\n"
        "2. The system of claim 5, wherein the processor is fast.\n"
        "3. The system of claim 3, wherein the processor is slow.\n"
    )
    result = HierarchyAnalyzer().analyze(document.claims)

    assert result.node(2).parent_issues[5] == ParentIssue.MISSING_CLAIM
    assert result.node(3).parent_issues[3] == ParentIssue.SELF_REFERENCE
    # Both root their own trees rather than disappearing from the report.
    assert {tree.root for tree in result.trees} == {1, 2, 3}
    assert result.orphans == [2, 3]


# -- II. claim errors -------------------------------------------------------


def test_claim_error_analyzer_reports_dependency_errors():
    document = load(
        "What is claimed is:\n"
        "1. A system comprising a processor.\n"
        "2. The system of claim 9, wherein the processor is fast.\n"
        "3. The system of claim 4, wherein the processor is slow.\n"
        "4. The system of claim 1, wherein the processor is warm.\n"
    )
    result = ClaimErrorAnalyzer().analyze(document.claims)
    types = {(issue.claim_number, issue.type) for issue in result.issues}

    assert (2, ClaimIssueType.MISSING_PARENT) in types
    assert (3, ClaimIssueType.FORWARD_DEPENDENCY) in types
    assert result.errors >= 2


def test_dependent_claims_using_wherein_are_not_flagged_for_a_missing_transition():
    document = load(
        "What is claimed is:\n"
        "1. A system comprising a processor.\n"
        "2. The system of claim 1, wherein the processor is fast.\n"
    )
    result = ClaimErrorAnalyzer().analyze(document.claims)
    assert not [i for i in result.issues if i.type == ClaimIssueType.MISSING_TRANSITION]


def test_language_checks_flag_terms_of_degree_and_examples():
    document = load(
        "What is claimed is:\n"
        "1. A system comprising a substantially flat plate, such as a disc.\n"
    )
    result = ClaimErrorAnalyzer().analyze(document.claims)
    types = {issue.type for issue in result.issues}

    assert ClaimIssueType.INDEFINITE_TERM in types
    assert ClaimIssueType.EXEMPLARY_LANGUAGE in types
    # Both point at the words they are about, so the renderer can mark them.
    for issue in result.issues:
        if issue.type in (ClaimIssueType.INDEFINITE_TERM, ClaimIssueType.EXEMPLARY_LANGUAGE):
            assert issue.locations and issue.locations[0].char_end > issue.locations[0].char_start


def test_multiple_dependent_claim_must_be_in_the_alternative():
    document = load(
        "What is claimed is:\n"
        "1. A system comprising a processor.\n"
        "2. The system of claim 1, wherein the processor is fast.\n"
        "3. The system of claims 1 and 2, wherein the processor is cool.\n"
    )
    result = ClaimErrorAnalyzer().analyze(document.claims)
    assert any(
        issue.type == ClaimIssueType.MULTIPLE_DEPENDENT_CONJUNCTION
        for issue in result.issues
    )


def test_clean_claim_set_reports_nothing():
    document = load(
        "What is claimed is:\n"
        "1. A system comprising a processor and a memory.\n"
        "2. The system of claim 1, wherein the memory stores an instruction.\n"
    )
    result = ClaimErrorAnalyzer().analyze(document.claims)
    assert result.is_clean, [issue.message for issue in result.issues]


# -- report -----------------------------------------------------------------


def test_report_service_runs_sections_one_to_three(tmp_path):
    report = report_service.build(SIMPLE_DOCUMENT.encode("utf-8"), "sample.txt")

    assert report.claim_count == 3
    assert report.hierarchy is not None
    assert report.claim_errors is not None
    assert report.antecedents is not None
    assert not report.notes            # no section failed

    pdf_path = report_service.generate_pdf(report, output_dir=str(tmp_path))
    assert pdf_path.endswith(".pdf")
    with open(pdf_path, "rb") as handle:
        assert handle.read(5) == b"%PDF-"


def test_report_endpoint_returns_json():
    files = {"file": ("sample.txt", io.BytesIO(SIMPLE_DOCUMENT.encode()), "text/plain")}
    response = client.post("/api/v1/report", files=files)

    assert response.status_code == 200
    payload = response.json()
    assert payload["claim_count"] == 3
    assert payload["hierarchy"]["independent_claims"] == [1]
    assert payload["claim_errors"] is not None


def test_report_pdf_endpoint_returns_a_pdf():
    files = {"file": ("sample.txt", io.BytesIO(SIMPLE_DOCUMENT.encode()), "text/plain")}
    response = client.post("/api/v1/report/pdf", files=files)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")


# -- report layout: section verdicts and page flow ---------------------------

from app.report.cm_report_generator import NO_ERRORS_TEXT, section_status
from app.report.models import ReportSection


def test_clean_sections_say_no_errors_found():
    report = report_service.build(
        b"What is claimed is:\n"
        b"1. A system comprising a processor and a memory.\n"
        b"2. The system of claim 1, wherein the memory stores an instruction.\n",
        "clean.txt",
    )

    for section in (ReportSection.CLAIMS_HIERARCHY, ReportSection.CLAIM_ERRORS):
        status = section_status(report, section)
        assert status.kind == "ok"
        assert status.headline == NO_ERRORS_TEXT

    # "a system" in claim 1's preamble is a limiting-preamble question, not an error.
    # A section whose findings are all notes is announced as notes (spec section 4).
    antecedents = section_status(report, ReportSection.ANTECEDENTS)
    assert antecedents.kind == "info"
    assert antecedents.headline == "3 notes found."
    assert report.antecedents.severity_summary == {"INFO": 3, "WARNING": 0, "ERROR": 0}
    # Sections not analysed yet say so, rather than claiming a clean result.
    assert section_status(report, ReportSection.LANGUAGE).kind == "pending"


def test_section_three_counts_each_tier_separately():
    """
    Spec section 4: errors, warnings and notes are never added into one headline, and a
    section is never announced as errors when nothing in it is one.

    Claim 2 refers to a gadget nothing introduces -- an error -- while the preamble terms
    are notes.  The banner has to say so without turning four findings into "4 errors".
    """
    report = report_service.build(
        b"What is claimed is:\n"
        b"1. A system comprising a processor and a memory.\n"
        b"2. The system of claim 1, wherein the gadget is red.\n",
        "mixed.txt",
    )
    tiers = report.antecedents.severity_summary
    assert tiers["ERROR"] == 1
    assert tiers["INFO"] == 3
    assert sum(tiers.values()) == report.antecedents.total_findings

    status = section_status(report, ReportSection.ANTECEDENTS)
    assert status.kind == "error"
    assert status.headline == "1 error and 3 notes found."


def test_a_finding_takes_its_tier_from_its_type():
    """One table decides the tier, so no checker can quietly rate its own findings."""
    from app.analysis.models import DEFAULT_SEVERITY, FindingType, Severity

    assert DEFAULT_SEVERITY[FindingType.MISSING_ANTECEDENT] is Severity.ERROR
    assert DEFAULT_SEVERITY[FindingType.LIMITING_PREAMBLE] is Severity.INFO

    report = report_service.build(
        b"What is claimed is:\n"
        b"1. A system comprising a processor.\n"
        b"2. The system of claim 1, wherein the gadget is red.\n",
        "tiers.txt",
    )
    for finding in report.antecedents.findings:
        assert finding.severity is DEFAULT_SEVERITY[finding.type]


def test_invalid_parent_is_an_error_in_sections_one_and_two():
    report = report_service.build(
        b"What is claimed is:\n"
        b"1. A system comprising a processor.\n"
        b"2. The system of claim 2, wherein the processor is fast.\n",
        "broken.txt",
    )

    hierarchy = section_status(report, ReportSection.CLAIMS_HIERARCHY)
    assert hierarchy.kind == "error"
    assert hierarchy.details == ["Claim 2 refers to itself."]

    errors = section_status(report, ReportSection.CLAIM_ERRORS)
    assert errors.kind == "error"
    assert any("claim 2" in detail for detail in errors.details)


def test_claim_with_more_findings_than_fit_on_a_page_still_renders(tmp_path):
    """A section III row taller than a page must continue overleaf, not raise."""
    references = ", ".join(f"the {letter * 3} member" for letter in "abcdefghijklmnopqrstuvwxyz")
    text = (
        "What is claimed is:\n"
        "1. A system comprising a processor.\n"
        f"2. The system of claim 1, wherein the processor is coupled to {references}.\n"
    )
    report = report_service.build(text.encode(), "long.txt")
    assert sum(1 for f in report.antecedents.findings if f.claim_number == 2) >= 20

    pdf_path = report_service.generate_pdf(report, output_dir=str(tmp_path))
    with open(pdf_path, "rb") as handle:
        assert handle.read(5) == b"%PDF-"


def _antecedent_table(report, tmp_path):
    from reportlab.platypus import Table

    from app.report.cm_report_generator import CMReportGenerator

    story = []
    CMReportGenerator(output_dir=str(tmp_path))._build_antecedents(report, story)
    return [f for f in story if isinstance(f, Table)][-1]


def test_a_claim_row_just_taller_than_the_page_still_splits(tmp_path):
    """
    A §III row that reaches the top of a page and is only a little taller than it must
    split there -- it cannot fit anywhere else.  With splitInRow=40 ReportLab refused any
    split leaving under 40pt overleaf, and with the claim cell passed as a bare flowable
    it could not split the cell at all; either way the report raised LayoutError.
    """
    from app.report.cm_report_generator import CONTENT_WIDTH

    elements = "; ".join(
        f"a component {i} coupled to the frame by a bracket {i}" for i in range(1, 30)
    )
    text = (
        "What is claimed is:\n"
        f"1. A system comprising: a frame; {elements}; and a sensor on the widget.\n"
    )
    table = _antecedent_table(report_service.build(text.encode(), "tall.txt"), tmp_path)
    _width, height = table.wrap(CONTENT_WIDTH, 10_000)

    parts = table.split(CONTENT_WIDTH, height - 16)   # overflows by 16pt, as seen
    assert len(parts) == 2
