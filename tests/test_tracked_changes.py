"""
Word tracked changes are accepted before a document is read.

Read from LibreOffice's rendering, a tracked-changes draft has deleted and inserted
words side by side and its automatic claim numbers shown twice ("12.[13.]"), which
corrupts claim text, claim numbers and every dependency.  The synthetic .docx files
below exercise each kind of revision; the last test runs a real draft against
ClaimMaster's own report on it.
"""
import io
import os
import zipfile

import pytest
from lxml import etree

from app.document.revisions import (
    W,
    accept_tracked_changes,
    claims_with_tracked_edits,
    has_tracked_changes,
)

REV = 'w:id="1" w:author="Reviewer" w:date="2026-01-01T00:00:00Z"'
NUMBERED = '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="10"/></w:numPr>'


def docx(body: str, styles: str = "") -> bytes:
    buffer = io.BytesIO()
    header = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'{header}<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>',
        )
        if styles:
            archive.writestr("word/styles.xml", f'{header}<w:styles xmlns:w="{W}">{styles}</w:styles>')
    return buffer.getvalue()


def run(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def inserted(text: str) -> str:
    return f"<w:ins {REV}>{run(text)}</w:ins>"


def deleted(text: str) -> str:
    return f'<w:del {REV}><w:r><w:delText xml:space="preserve">{text}</w:delText></w:r></w:del>'


def para(*runs: str, numbered: bool = False, extra: str = "") -> str:
    return f"<w:p><w:pPr>{NUMBERED if numbered else ''}{extra}</w:pPr>{''.join(runs)}</w:p>"


def claims_section(*claims: str) -> str:
    return para(run("What is claimed is:")) + "".join(claims) + para(run("ABSTRACT"))


def paragraph_texts(docx_bytes: bytes):
    root = etree.fromstring(zipfile.ZipFile(io.BytesIO(docx_bytes)).read("word/document.xml"))
    return ["".join(t.text or "" for t in p.iter(f"{{{W}}}t")) for p in root.iter(f"{{{W}}}p")]


# -- accepting changes -------------------------------------------------------------


def test_deleted_text_is_removed_and_inserted_text_kept():
    """Rendered, this reads "configured tofor generating"."""
    source = docx(para(run("an encoder configured "), deleted("to"), inserted("for"),
                       run(" generating embeddings")))
    assert paragraph_texts(accept_tracked_changes(source)) == [
        "an encoder configured for generating embeddings"
    ]


def test_deleted_paragraph_mark_joins_the_paragraphs():
    mark = f"<w:rPr><w:del {REV}/></w:rPr>"
    source = docx(para(run("a processor;"), extra=mark) + para(run(" and a memory.")))
    assert paragraph_texts(accept_tracked_changes(source)) == ["a processor; and a memory."]


def test_inserted_paragraph_mark_keeps_the_paragraphs():
    mark = f"<w:rPr><w:ins {REV}/></w:rPr>"
    source = docx(para(run("a processor;"), extra=mark) + para(run("a memory.")))
    assert paragraph_texts(accept_tracked_changes(source)) == ["a processor;", "a memory."]


def test_non_docx_bytes_pass_through_unchanged():
    assert accept_tracked_changes(b"not a zip archive") == b"not a zip archive"


# -- which claims were edited ---------------------------------------------------------


def test_edited_claims_are_counted_in_the_accepted_numbering():
    source = docx(claims_section(
        para(run("A system comprising a processor."), numbered=True),
        para(run("The system of claim 1, wherein the processor is "), deleted("slow"),
             inserted("fast"), run("."), numbered=True),
        para(run("The system of claim 1, wherein the processor is warm."), numbered=True),
    ))
    edits = claims_with_tracked_edits(source)
    assert (edits.claim_count, edits.edited) == (3, [2])


def test_numbering_removed_by_a_tracked_change_does_not_start_a_claim():
    """
    A reviewer turned a numbered paragraph into claim 1's last element.  The number is
    only in the *old* properties; in the accepted document the paragraph is unnumbered.
    Counting it shifted every later claim by one.
    """
    old_numbering = f"<w:pPrChange {REV}><w:pPr>{NUMBERED}</w:pPr></w:pPrChange>"
    source = docx(claims_section(
        para(run("A method comprising: receiving a signal;"), numbered=True),
        para(run("filtering the signal."), extra=old_numbering),
        para(run("The method of claim 1, wherein the signal is audio."), numbered=True),
    ))
    edits = claims_with_tracked_edits(source)
    assert edits.claim_count == 2
    # A formatting change alone is not treated as an amendment of the claim's text.
    assert edits.edited == []


def test_list_number_zero_means_unnumbered():
    off = '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr>'
    source = docx(claims_section(
        para(run("A method comprising a first step;"), numbered=True),
        f"<w:p><w:pPr>{off}</w:pPr>{inserted('and a second step.')}</w:p>",
    ))
    edits = claims_with_tracked_edits(source)
    assert (edits.claim_count, edits.edited) == (1, [1])


def test_numbering_inherited_from_the_paragraph_style_is_recognised():
    styles = f'<w:style w:type="paragraph" w:styleId="Claim"><w:pPr>{NUMBERED}</w:pPr></w:style>'

    def claim(*runs):
        return f'<w:p><w:pPr><w:pStyle w:val="Claim"/></w:pPr>{"".join(runs)}</w:p>'

    source = docx(claims_section(
        claim(run("A device.")),
        claim(run("The device of claim 1, "), inserted("wherein it is red"), run(".")),
    ), styles)
    edits = claims_with_tracked_edits(source)
    assert (edits.claim_count, edits.edited) == (2, [2])


def test_documents_without_tracked_changes_are_left_alone():
    source = docx(claims_section(para(run("A device."), numbered=True)))
    assert not has_tracked_changes(source)
    assert claims_with_tracked_edits(source) is None


# -- end to end: a real tracked-changes draft against ClaimMaster --------------------------

DRAFT = "/home/sig/Downloads/50OR570US - Draft - QCed - 5-Aug-2026.docx"


@pytest.mark.skipif(not os.path.exists(DRAFT), reason="tracked-changes draft not available")
def test_tracked_changes_draft_matches_claimmaster():
    """
    ClaimMaster's report on this draft is the reference: 20 claims, claims 1, 2, 12, 15,
    16 and 20 amended without a status identifier, no self-dependency, and a single
    missing antecedent -- "the features" in claim 15.
    """
    from app.report.service import report_service

    raw = open(DRAFT, "rb").read()
    name = os.path.basename(DRAFT)
    report = report_service.build(raw, name)

    assert report.claim_count == 20
    assert report.cancelled_claims == []

    issues = [(issue.claim_number, issue.type.value) for issue in report.claim_errors.issues]
    assert not [issue for issue in issues if issue[1] == "SELF_DEPENDENT"]
    assert sorted(n for n, kind in issues if kind == "AMENDED_WITHOUT_STATUS") == [1, 2, 12, 15, 16, 20]

    findings = report_service.build_antecedent_report(raw, name).antecedents.findings
    assert [(f.claim_number, f.type.value, f.term) for f in findings] == [
        (15, "MISSING_ANTECEDENT", "the features")
    ]
