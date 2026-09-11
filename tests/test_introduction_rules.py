"""
Introduction rules (docs/antecedent-basis-spec.md, section 2) and the input
normalization that has to run before them.

An element is introduced whenever it appears without "the"/"said"; an indefinite
article is not required.  Each pattern the spec lists is checked end to end: the
reference that follows the introduction must not be reported as a missing antecedent.
"""
import pytest

from app.analysis.antecedent.term_extractor import extract_terms_from_text
from app.document.loader import DocumentLoader
from app.normalizer.engine import NormalizationEngine
from app.report.service import report_service


def antecedent_errors(claims: str):
    report = report_service.build_antecedent_report(
        ("What is claimed is:\n" + claims).encode(), "claims.txt"
    )
    return [(f.claim_number, f.type.value, f.term) for f in report.antecedents.findings]


def introductions(text: str):
    return {t.normalized_term for t in extract_terms_from_text(text) if not t.is_reference}


def normalize(text: str) -> str:
    return NormalizationEngine().normalize(text)[0]


# -- section 2 patterns -------------------------------------------------------


@pytest.mark.parametrize("pattern,claims", [
    ("bare mass noun",
     "1. A system configured to: receive telecommunication data from a device; "
     "and store the telecommunication data.\n"),
    ("ordinal-modified bare noun",
     "1. A method comprising: providing first content to a device; "
     "and presenting the first content.\n"),
    ("alternative branch",
     "1. A method comprising: determining second content for a first user, or third "
     "content for a second user; and providing the second content or the third content.\n"),
    ("preamble recitation, gerund object",
     "1. A method for processing signals, the method comprising: filtering the signals.\n"),
    ("preamble recitation, prepositional object",
     "1. A system for signal processing, comprising: a processor that performs the signal "
     "processing.\n"),
    ("quantified: one or more",
     "1. A method comprising: identifying one or more synonyms for a word; "
     "and ranking the synonyms.\n"),
    ("quantified: at least one",
     "1. A device comprising: at least one sensor; and a controller coupled to the sensor.\n"),
    ("gerund of a recited act",
     "1. A method comprising: automatically adjusting a parameter.\n"
     "2. The method of claim 1, wherein the adjusting comprises increasing a volume.\n"),
])
def test_introduction_pattern_gives_antecedent_basis(pattern, claims):
    assert antecedent_errors(claims) == [], pattern


def test_genuine_missing_antecedent_is_still_reported():
    """The spec's own MISSING_AB example: nothing introduces a shaft."""
    assert antecedent_errors(
        "1. A device comprising a housing; and a motor mounted to the shaft.\n"
    ) == [(1, "MISSING_ANTECEDENT", "the shaft")]


def test_verb_leading_a_limitation_is_split_from_its_object():
    assert "first content" in introductions("provide first content to a device")


def test_lone_verb_before_an_article_is_not_an_element():
    assert "identify" not in introductions("identify a category of the content")


def test_gerund_is_flagged_as_weak_support():
    gerunds = [t for t in extract_terms_from_text("automatically adjusting a parameter")
               if t.is_gerund]
    assert [t.normalized_term for t in gerunds] == ["adjusting"]


# -- normalization ----------------------------------------------------------------


def test_glued_article_is_split():
    assert "one or more of the moment" in normalize("wherein the one or more ofthe moment")


def test_glued_compound_is_split_when_the_text_spaces_it_elsewhere():
    text = normalize(
        "identify a user characteristic; measure the user characteristic; "
        "and store the usercharacteristic."
    )
    assert "usercharacteristic" not in text
    assert "store the user characteristic." in text


def test_real_compound_is_left_alone():
    assert "database" in normalize("a database storing records; and a server.")


def test_stray_colon_becomes_a_semicolon():
    text = normalize("determine a level by the first user: determine second content")
    assert "first user; determine" in text


@pytest.mark.parametrize("text", [
    "A system comprising: a processor",
    "cause the computing system to: provide content",
    "wherein: a primary conduit",
    "selected from the group consisting of: iron",
    "wherein the adjusting comprises: one or more of",
    "What is claimed is:\n1. A method",
    "the device having three parts: a lid, a base",
])
def test_list_colons_are_kept(text):
    assert ":" in normalize(text)


def test_repaired_colon_separates_limitations():
    """A stray colon used to nest every later limitation under the one before it."""
    claims = DocumentLoader(extract_figures=False).load(
        b"What is claimed is:\n"
        b"1. A method comprising: determining a level by a first user: determining "
        b"content for the first user; and providing the content.\n",
        "claims.txt",
    ).claims.claims

    assert [el.level for el in claims[0].elements] == [1, 1, 1]


def test_gerund_introductions_do_not_enter_number_agreement():
    """
    A gerund names an act, so it has no number: "providing" must not be reported as
    a singular/plural mismatch against "one or more of providing".
    """
    report = report_service.build(
        b"What is claimed is:\n"
        b"1. A method comprising: providing a signal.\n"
        b"2. The method of claim 1, wherein the method comprises one or more of providing a tone.\n"
        b"3. The method of claim 1, further comprising providing a light.\n",
        "claims.txt",
    )
    assert not [f for f in report.antecedents.findings if f.type.value == "SINGULAR_PLURAL"]
