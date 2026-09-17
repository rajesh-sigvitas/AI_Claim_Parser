"""
A reference must be matched to its introduction even when the wording is not identical.

Spec (docs/antecedent-basis-spec.md) section 2: "Non-identical wording still counts ...
Match on head noun, not on exact string", and section 3.2: going from specific to
general ("an aluminum lever" ... "the lever") is usually fine.  Exact-string matching
reported every one of these as a missing antecedent.

Loosening the match must not hide real errors, so each rule is paired with a case that
has to stay reported: a reference more specific than anything introduced, a different
head noun, a different ordinal, and an "-s" word that really is part of the noun.
"""
from pathlib import Path

import pytest

from app.report.service import report_service

FIXTURES = Path(__file__).parent / "fixtures"


def antecedent_errors(claims: str):
    report = report_service.build_antecedent_report(
        ("What is claimed is:\n" + claims).encode(), "claims.txt"
    )
    return [(f.claim_number, f.type.value, f.term) for f in report.antecedents.findings]


def full_section_iii(claims: str):
    report = report_service.build(("What is claimed is:\n" + claims).encode(), "claims.txt")
    return report.antecedents.findings


# -- references the exact-string match rejected -----------------------------------------


@pytest.mark.parametrize("case,claims", [
    ("modifier dropped (specific -> general)",
     "1. A device comprising: a flat top surface; and a sensor mounted on the top surface.\n"),
    ("same words, 'of' order",
     "1. A container composed out of fibres of plastic.\n"
     "2. The container of claim 1, wherein the plastic fibres are biodegradable.\n"),
    ("introduced after 'of'",
     "1. A container composed out of fibres of plastic.\n"
     "2. The container of claim 1, wherein the fibres of plastic are woven.\n"),
    ("trailing verb swallowed into the reference",
     "1. A system for growing plants, which system comprises: a buoyant body; and a seed "
     "placed on the buoyant body such that the buoyant body floats on water.\n"),
])
def test_equivalent_wording_resolves(case, claims):
    assert antecedent_errors(claims) == [], case


# -- errors that must still be reported ----------------------------------------------------


def test_reference_more_specific_than_its_introduction_is_still_reported():
    """
    General -> specific: "a lever" does not introduce "the aluminum lever" (MPEP
    2173.05(e)).  A lever is recited, so it is the double-check tier (spec 3.2), not a
    certain error -- but it must be reported.
    """
    assert antecedent_errors(
        "1. A device comprising a lever, wherein the aluminum lever is bent.\n"
    ) == [(1, "POSSIBLY_MISSING_ANTECEDENT", "the aluminum lever")]


def test_a_different_head_noun_is_still_reported():
    """"a sensor housing" introduces a housing, not a sensor: reported, to double-check."""
    assert antecedent_errors(
        "1. A device comprising: a sensor housing; and a cable attached to the sensor.\n"
    ) == [(1, "POSSIBLY_MISSING_ANTECEDENT", "the sensor")]


def test_nothing_that_could_be_the_antecedent_is_an_error():
    assert antecedent_errors(
        "1. A device comprising: a housing; and a motor mounted to the shaft.\n"
    ) == [(1, "MISSING_ANTECEDENT", "the shaft")]


def test_a_different_ordinal_is_still_missing():
    assert antecedent_errors(
        "1. A device comprising: a first wheel; and an axle joined to the second wheel.\n"
    ) == [(1, "MISSING_ANTECEDENT", "the second wheel")]


def test_an_s_word_used_as_a_noun_is_not_trimmed_as_a_verb():
    """
    "the motor pads are attached": a verb cannot be followed by "are", so "pads" belongs to
    the noun phrase and "the motor pads" is a new, unintroduced element.
    """
    findings = antecedent_errors(
        "1. An engine comprising: a motor; and a bracket, wherein the motor pads are "
        "attached to the bracket.\n"
    )
    assert (1, "POSSIBLY_MISSING_ANTECEDENT", "the motor pads") in findings


def test_an_s_word_attested_as_a_noun_elsewhere_is_not_trimmed():
    findings = antecedent_errors(
        "1. An engine comprising: a motor; and a bracket, wherein the motor floats on the "
        "bracket.\n"
        "2. The engine of claim 1, wherein the floats are rubber.\n"
    )
    assert (1, "POSSIBLY_MISSING_ANTECEDENT", "the motor floats") in findings


# -- claim structure and number agreement -------------------------------------------------


def test_comprises_is_a_transition():
    """"which system comprises:" ends the preamble; "a buoyant body" is a body element."""
    findings = full_section_iii(
        "1. A system for growing plants, which system comprises: a buoyant body having a "
        "flat top surface; and a seed on the top surface.\n"
        "2. The system of claim 1, wherein the buoyant body is foam.\n"
    )
    preamble = [f.term for f in findings if f.type.value == "LIMITING_PREAMBLE"]
    assert "a buoyant body" not in preamble


def test_each_member_of_a_plurality_is_not_a_number_mismatch():
    """"each container" quantifies over "a plurality of containers"; it is correct drafting."""
    findings = full_section_iii(
        "1. A system comprising a plurality of containers, wherein each container holds a seed.\n"
        "2. The system of claim 1, wherein the containers are plastic.\n"
        "3. The system of claim 1, wherein each container is round.\n"
    )
    assert not [f for f in findings if f.type.value == "SINGULAR_PLURAL"]


def test_one_or_more_matches_singular_and_plural():
    """Spec 3.5: "one or more X" has indeterminate number and matches both."""
    findings = full_section_iii(
        "1. A method comprising identifying one or more synonyms for a word.\n"
        "2. The method of claim 1, wherein the synonym is ranked.\n"
    )
    assert not [f for f in findings if f.type.value in ("SINGULAR_PLURAL", "MISSING_ANTECEDENT")]


# -- the reported document -------------------------------------------------------------------


def test_test_sept15_claims_have_no_false_findings():
    """
    All nine section III findings reported on this claim set were false: missing
    antecedents from a dropped adjective, word order and a swallowed verb, a body element
    read as preamble, and "each container" read as a number mismatch.
    """
    text = (FIXTURES / "test_sept15.claims.txt").read_text()
    findings = report_service.build(text.encode(), "test_sept15.claims.txt").antecedents.findings

    assert [f.term for f in findings if f.type.value in ("MISSING_ANTECEDENT", "REVERSE_ANTECEDENT")] == []
    assert [f.term for f in findings if f.type.value == "SINGULAR_PLURAL"] == []
    assert sorted(f.term for f in findings if f.type.value == "LIMITING_PREAMBLE") == [
        "a system", "a water surface",
    ]


# -- verbs read into a term (the page-table claim set) --------------------------------------


def test_verb_swallowed_into_an_introduction_is_set_aside():
    """"a second software component points to ..." introduces the software component."""
    assert antecedent_errors(
        "1. A method comprising: storing a table, wherein a first software component "
        "points to the table, and a second software component points to the table, "
        "wherein the table is shared between the second software component and the "
        "first software component.\n"
        "2. The method of claim 1, wherein the first software component is a hypervisor.\n"
    ) == []


def test_plural_subject_verb_ends_the_reference():
    assert antecedent_errors(
        "1. A method comprising accessing page tables stored in a memory.\n"
        "2. The method of claim 1, wherein the page tables include at least three levels.\n"
    ) == []


def test_bare_phrase_after_having_is_an_introduction():
    assert antecedent_errors(
        "1. A system comprising a first component having higher execution privileges "
        "than a second component.\n"
        "2. The system of claim 1, wherein the first component having the higher "
        "execution privileges is a hypervisor.\n"
    ) == []


def test_different_compounds_are_not_a_number_mismatch():
    """"privilege level" and "translation levels" share only their last word."""
    findings = full_section_iii(
        "1. A method comprising: storing tables over multiple translation levels; and "
        "assigning a higher privilege level to a component.\n"
        "2. The method of claim 1, wherein the higher privilege level is fixed.\n"
    )
    assert not [f for f in findings if f.type.value == "SINGULAR_PLURAL"]


def test_the_same_compound_is_matched_across_numbers():
    """
    The other half of the pair above: a singular "drain conduit" must not supply the
    singular for "the suction conduit", which was only ever recited as a plurality.
    """
    findings = full_section_iii(
        "1. A device comprising a plurality of suction conduits and a drain conduit.\n"
        "2. The device of claim 1, wherein the suction conduit is long.\n"
    )
    assert [(f.claim_number, f.term) for f in findings if f.type.value == "SINGULAR_PLURAL"] \
        == [(2, "the suction conduit")]


def test_a_dependent_claims_opening_reference_is_not_a_recitation():
    """
    "The rear attachment lens according to claim 1" opens every dependent claim of that
    application.  It says what the claim depends from; reading it as a recitation put
    five claims of one granted patent in the wrong at once.
    """
    findings = full_section_iii(
        "1. An apparatus comprising a plurality of rear attachment lenses.\n"
        "2. The rear attachment lens according to claim 1, wherein a focal length is "
        "fixed.\n"
    )
    assert not [f for f in findings if f.type.value == "SINGULAR_PLURAL"]


def test_the_same_mismatch_in_the_claim_body_is_still_reported():
    """The paired case: in the body it is a recitation, and it still disagrees."""
    findings = full_section_iii(
        "1. An apparatus comprising a plurality of rear attachment lenses.\n"
        "2. The apparatus of claim 1, wherein the rear attachment lens is glass.\n"
    )
    assert [(f.claim_number, f.term) for f in findings if f.type.value == "SINGULAR_PLURAL"] \
        == [(2, "the rear attachment lens")]


def test_a_singular_noun_ending_in_s_is_not_a_plural():
    """"lens" is not the plural of "len": two spellings of one word are not a mismatch."""
    findings = full_section_iii(
        "1. An apparatus comprising a lens and a gas.\n"
        "2. The apparatus of claim 1, wherein the lens is glass and the gas is inert.\n"
    )
    assert not [f for f in findings if f.type.value == "SINGULAR_PLURAL"]


def test_a_member_drawn_out_of_a_set_is_not_a_mismatch():
    """
    The MID101312US claim 9 shape.  Claim 2 recites the set and names a member of it, so
    claim 3's singular reference has an introduction to point back at.  The real
    ClaimMaster report does not flag it.
    """
    findings = full_section_iii(
        "1. A device comprising a primary suction conduit.\n"
        "2. The device of claim 1, further comprising a plurality of suction conduits, "
        "wherein a suction conduit of the plurality of suction conduits is long.\n"
        "3. The device of claim 2, wherein the primary suction conduit is short.\n"
    )
    assert not [f for f in findings if f.type.value == "SINGULAR_PLURAL"]


def test_page_table_claims_report_only_references_without_a_noun_introduction():
    """
    The 20 missing-antecedent errors reported on this claim set came from verbs read into
    terms ("component points", "tables include", "entry indicates") and from "having
    higher execution privileges" not counting as an introduction.  "the changed
    ownership" follows "changing the ownership" and "an ownership", so it is described,
    not new.  What remains is "the change", introduced only by the verb -- a reference to
    double-check, not a certain error.
    """
    text = (FIXTURES / "page_table_ownership.claims.txt").read_text()
    findings = report_service.build_antecedent_report(
        text.encode(), "page_table_ownership.claims.txt"
    ).antecedents.findings
    assert [(f.claim_number, f.type.value, f.term) for f in findings] == [
        (10, "POSSIBLY_MISSING_ANTECEDENT", "the change"),
    ]


# -- ordinal shorthand ("the first and second X") -------------------------------------------


DUAL_MOTOR = (
    "1. A coupling system for a vehicle, comprising: a vehicle body; a first electric "
    "motor; a second electric motor; and a vehicle axle including: a first rotating member "
    "coupled to the first electric motor and connectable to a first wheel assembly; and a "
    "second rotating member coupled to the second electric motor and connectable to a "
    "second wheel assembly, wherein the first - and second-wheel assemblies are disposed "
    "on opposing ends of the vehicle axle.\n"
    "2. The coupling system of claim 1, wherein a combined torque is provided to the "
    "first- and second-wheel assemblies when the first - and second-wheel assemblies are "
    "connected to the first and second rotating members, respectively.\n"
)


def test_participle_after_an_ordinal_is_part_of_the_term():
    """"a first rotating member" introduces "first rotating member", not "a first"."""
    assert antecedent_errors(DUAL_MOTOR) == []


def test_participle_after_a_noun_still_ends_the_term():
    """"a first extension line connecting centers": "connecting" starts a clause."""
    assert antecedent_errors(
        "1. A drawing comprising a first extension line connecting centers and a second "
        "extension line, wherein the first and second extension lines are dashed.\n"
    ) == []


def test_suspended_hyphen_ordinals_are_expanded():
    """"the first- and second-wheel assemblies" names both wheel assemblies."""
    assert antecedent_errors(
        "1. A vehicle comprising a first wheel assembly and a second wheel assembly.\n"
        "2. The vehicle of claim 1, wherein the first- and second-wheel assemblies are "
        "aligned.\n"
    ) == []


def test_suspended_hyphen_reference_to_an_unintroduced_element_is_reported():
    findings = antecedent_errors(
        "1. A vehicle comprising a first wheel assembly.\n"
        "2. The vehicle of claim 1, wherein the first- and second-wheel assemblies are "
        "aligned.\n"
    )
    assert (2, "MISSING_ANTECEDENT", "the second wheel assemblies") in findings
