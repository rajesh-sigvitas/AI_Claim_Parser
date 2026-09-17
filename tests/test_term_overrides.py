"""
Term-grouping overrides (docs/antecedent-basis-spec.md section 5).

Where one noun phrase ends is a judgement no rule set gets right for every drafting
style, so the spec asks for an escape hatch rather than more rules.  These tests cover
the three overrides, that they are off unless configured, and that a bad override file
cannot take the analysis down.
"""
import json

import pytest

from app.analysis.antecedent import overrides
from app.analysis.antecedent.overrides import TermOverrides, phrase_words
from app.analysis.antecedent.term_extractor import extract_terms_from_text
from app.report.service import report_service


@pytest.fixture(autouse=True)
def reset_overrides():
    """Every test sets its own; None restores loading from settings afterwards."""
    yield
    overrides.set_overrides(None)


def terms(text: str):
    return [t.normalized_term for t in extract_terms_from_text(text)]


def findings(claims: str):
    report = report_service.build_antecedent_report(
        ("What is claimed is:\n" + claims).encode(), "claims.txt"
    )
    return [(f.claim_number, f.type.value, f.term) for f in report.antecedents.findings]


# -- the three overrides ------------------------------------------------------------------


def test_force_group_keeps_a_phrase_whole():
    text = "a packet receiving device driver is loaded"
    assert "device driver" in terms(text)

    overrides.set_overrides(TermOverrides.from_dict(
        {"force_group": ["packet receiving device driver"]}))
    kept = terms(text)
    assert kept == ["packet receiving device driver"]


def test_truncate_cuts_an_over_grouped_phrase_back():
    """"server system // controls": the words after the marker were wrongly pulled in."""
    text = "a server system controller unit is coupled to the server system"
    assert terms(text) == ["server system controller unit", "server system"]

    overrides.set_overrides(TermOverrides.from_dict({"truncate": ["server system"]}))
    assert terms(text) == ["server system", "server system"]


def test_truncate_lets_the_later_reference_resolve():
    """
    The point of the override: the reference now has an introduction to match.

    Over-grouping does not usually produce a hard error -- the resolver offers the
    over-grouped phrase as a possible antecedent and reports a warning -- so what the
    override removes is a question the drafter would have had to answer by hand.
    """
    claims = (
        "1. A device comprising a server system controller unit.\n"
        "2. The device of claim 1, wherein the server system is remote.\n"
    )
    assert [(claim, term) for claim, _type, term in findings(claims)] == \
        [(2, "the server system")]

    overrides.set_overrides(TermOverrides.from_dict({"truncate": ["server system"]}))
    assert findings(claims) == []


def test_ignore_drops_a_phrase_entirely():
    text = "the accompanying drawings show a housing"
    assert "accompanying drawing" in terms(text)

    overrides.set_overrides(TermOverrides.from_dict({"ignore": ["the accompanying drawings"]}))
    kept = terms(text)
    assert "accompanying drawing" not in kept
    assert "housing" in kept


# -- matching -----------------------------------------------------------------------------


def test_phrases_match_regardless_of_case_hyphens_and_punctuation():
    assert phrase_words("Packet-Receiving, Device") == ("packet", "receiving", "device")

    overrides.set_overrides(TermOverrides.from_dict(
        {"force_group": ["packet receiving device driver"]}))
    assert terms("a Packet-Receiving Device Driver is loaded") == \
        ["packet receiving device driver"]


def test_a_phrase_must_cover_whole_words():
    """"packet receiving" must not claim half of the hyphenated "receiving-device"."""
    overrides.set_overrides(TermOverrides.from_dict({"force_group": ["packet receiving"]}))
    assert TermOverrides.from_dict(
        {"force_group": ["packet receiving"]}
    ).forced_length(["packet", "receiving-device", "driver"]) is None


def test_the_longest_listed_phrase_wins():
    listed = TermOverrides.from_dict(
        {"force_group": ["server system", "server system controller"]})
    assert listed.forced_length(["server", "system", "controller", "unit"]) == 3


# -- configuration ------------------------------------------------------------------------


def test_no_overrides_configured_changes_nothing():
    overrides.set_overrides(TermOverrides.empty())
    assert TermOverrides.empty().is_empty
    assert terms("a server system controller unit") == ["server system controller unit"]


def test_an_unreadable_override_file_is_ignored_rather_than_fatal(tmp_path):
    broken = tmp_path / "overrides.json"
    broken.write_text("{not json")
    assert TermOverrides.load(broken).is_empty
    assert TermOverrides.load(tmp_path / "does-not-exist.json").is_empty
    assert TermOverrides.load(None).is_empty


def test_overrides_load_from_a_file(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({
        "force_group": ["packet receiving device driver"],
        "truncate": ["server system"],
        "ignore": ["the accompanying drawings"],
    }))
    loaded = TermOverrides.load(path)
    assert not loaded.is_empty
    overrides.set_overrides(loaded)
    assert terms("a packet-receiving device driver") == ["packet receiving device driver"]
