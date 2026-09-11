"""
Term span boundaries (stage 2b).

A term must end at the real noun-phrase boundary.  Over-grouping swallows the next
word ("the vehicle together") so the reference no longer matches "a vehicle";
stopping early at a binding preposition truncates "a level of understanding" to
"level".  Both surface as false missing antecedents.

Cases live in tests/fixtures/term_boundaries.json; the US12731445 claim set is the
real document these errors were reported on.
"""
import json
from pathlib import Path

import pytest

from app.analysis.antecedent import lexicon
from app.analysis.antecedent.term_extractor import extract_terms_from_text
from app.normalizer.engine import NormalizationEngine
from app.report.service import report_service

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "term_boundaries.json").read_text())["cases"]


def extracted(text: str):
    return {
        ("REF" if t.is_reference else "INTRO", t.normalized_term)
        for t in extract_terms_from_text(text)
    }


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_term_boundary(case):
    terms = extracted(case["text"])
    normalized = {term for _kind, term in terms}

    for kind, term in case.get("expect", []):
        assert (kind, term) in terms, f"{case['id']}: missing {kind} {term!r} in {sorted(terms)}"
    for term in case.get("forbid", []):
        assert term not in normalized, f"{case['id']}: over/under-grouped {term!r} in {sorted(terms)}"


def test_non_breaking_prepositions_are_configurable(monkeypatch):
    """The binding-preposition set is read at extraction time, not baked in."""
    text = "a sensor for vehicle monitoring; and a controller"
    assert ("INTRO", "sensor") in extracted(text)

    monkeypatch.setattr(lexicon, "NON_BREAKING_PREPOSITIONS", {"of", "for"})
    assert ("INTRO", "sensor for vehicle") in extracted(text)


def test_broken_hyphen_is_rejoined():
    text = NormalizationEngine().normalize("at pre- defined distance increments")[0]
    assert "pre-defined distance increments" in text


def test_suspended_hyphen_is_left_alone():
    text = NormalizationEngine().normalize("left- and right-hand wheels")[0]
    assert "left- and right-hand" in text


def test_us12731445_has_no_missing_antecedents():
    """All 14 findings reported on this patent were boundary false positives."""
    text = (FIXTURES / "us12731445.claims.txt").read_text()
    report = report_service.build_antecedent_report(text.encode(), "us12731445.claims.txt")

    assert report.claim_count == 20
    assert [(f.claim_number, f.type.value, f.term) for f in report.antecedents.findings] == []
