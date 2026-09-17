"""
Finding where the claims start, and where each claim starts.

Two general failures, both seen on a real draft through the /parse pipeline, which reads
the whole document rather than just its claims section:

* the claim statement ("What is claimed is:") was merged onto the line before it, so the
  line-anchored detector missed it and the specification was parsed as claims;
* the specification's paragraph numbers ("[0001]") then matched the bracketed claim
  number form, turning every paragraph into a claim.
"""
import os

import pytest

from app.parser.claim_detector import ClaimStatementDetector
from app.parser.claim_splitter import ClaimSplitter


def test_paragraph_numbers_are_not_claim_starts():
    text = (
        "[0001] The disclosure relates to tables.\n"
        "[0002] Tables are common in documents.\n"
        "1. A method comprising receiving an image.\n"
        "2. The method of claim 1, wherein the image is scanned.\n"
    )
    assert [claim.number for claim in ClaimSplitter().split(text)] == [1, 2]


def test_bracketed_claim_number_with_its_period_is_still_a_claim_start():
    text = "11. The method of claim 1.\n[12.] The method of claim 1, wherein a is b.\n"
    assert [claim.number for claim in ClaimSplitter().split(text)] == [11, 12]


def test_claim_statement_is_found_when_merged_into_a_line():
    text = "the table is recovered. CLAIM What is claimed is: 1. A method comprising a step."
    assert ClaimStatementDetector().detect_and_strip(text).startswith("1. A method")


def test_the_last_claim_statement_is_used():
    text = (
        "In one example, what is claimed is: a broad idea. More description. "
        "What is claimed is: 1. A method comprising a step."
    )
    assert ClaimStatementDetector().detect_and_strip(text) == "1. A method comprising a step."


def test_a_line_anchored_statement_still_wins():
    text = "Summary of the claims: brief.\nWhat is claimed is:\n1. A method comprising a step."
    assert ClaimStatementDetector().detect_and_strip(text).startswith("1. A method")


DRAFT = "/home/sig/Downloads/50OR570US - Draft - QCed - 5-Aug-2026.docx"


@pytest.mark.skipif(not os.path.exists(DRAFT), reason="draft not available")
def test_parse_pipeline_reads_the_claims_of_a_tracked_changes_draft():
    """/parse reads the whole document; it must still find exactly claims 1-20."""
    from app.services.parser_service import parser_service

    document = parser_service.parse(open(DRAFT, "rb").read(), os.path.basename(DRAFT),
                                    generate_pdf=False)
    claims = {claim.number: claim for claim in document.claims}

    assert sorted(claims) == list(range(1, 21))
    assert claims[17].metadata.get("parent_claims") == [16]
