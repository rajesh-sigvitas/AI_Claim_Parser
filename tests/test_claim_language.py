"""
Claim-language patterns found by running the antecedent check over 200 random granted
US patents (docs/antecedent-evaluation.md).  A granted patent has been examined, so a
missing-antecedent error on one is almost always the parser's mistake; each pattern
below was a recurring source of them.

Every rule is general -- a way claims are written, not a word list for one patent -- and
each is paired with a case that must still be reported, so loosening a rule cannot hide
a real error.
"""
import pytest

from app.parser.claim_splitter import ClaimSplitter
from app.report.service import report_service

MISSING = "MISSING_ANTECEDENT"
POSSIBLY = "POSSIBLY_MISSING_ANTECEDENT"


def findings(claims: str):
    report = report_service.build_antecedent_report(
        ("What is claimed is:\n" + claims).encode(), "claims.txt"
    )
    return [(f.claim_number, f.type.value, f.term) for f in report.antecedents.findings]


# -- references that need no antecedent ---------------------------------------------------


@pytest.mark.parametrize("case,claims", [
    ("method-step boilerplate",
     "1. A method comprising: storing a record.\n"
     "2. The method of claim 1, further comprising the step of receiving a request.\n"),
    ("Markush group",
     "1. A paste comprising a glass frit selected from the group consisting of PbF2, SiO2 "
     "and ZnO.\n"),
    ("a list the text itself introduces",
     "1. A material having a structure selected from any one of the following structural "
     "formulas: A, B and C.\n"),
    ("a property of something (MPEP inherent characteristic)",
     "1. A method comprising: receiving a first timestamp and a second timestamp; and "
     "storing the difference between the first timestamp and the second timestamp.\n"),
    ("a property of an element introduced in the same phrase",
     "1. A system comprising an antenna, wherein the antenna reports the operational "
     "status of a second module.\n"),
    ("a proper name",
     "1. A method comprising generating links over the Internet.\n"),
])
def test_references_that_point_at_no_claimed_element(case, claims):
    assert findings(claims) == [], case


# -- how an element is introduced ---------------------------------------------------------


@pytest.mark.parametrize("case,claims", [
    ("ordinal shorthand in an introduction",
     "1. A system comprising first and second electrodes, wherein the first electrode is "
     "rubber.\n"),
    ("'a first and a second X'",
     "1. A drive comprising a first and a second clutch, wherein the first clutch is "
     "closed.\n"),
    ("an acronym defined in parentheses",
     "1. A system comprising an analog-to-digital converter (ADC), wherein the ADC is "
     "coupled to a memory.\n"),
    ("an acronym after the words it continues",
     "1. A method comprising decoding a portion of a physical layer (PHY) protocol data "
     "unit (PPDU), the portion of the PPDU comprising a field.\n"),
    ("an acronym keeps its ordinal",
     "1. A camera comprising a first field of view (FOV), wherein an area is covered by "
     "the first FOV.\n"),
    ("'having stored thereon'",
     "1. A system comprising a memory having stored thereon instructions.\n"
     "2. The system of claim 1, wherein the instructions are encrypted.\n"),
    ("an adverb before the noun",
     "1. A base comprising two oppositely arranged triangular plates, wherein the two "
     "triangular plates are welded.\n"),
    ("an -able word before a noun",
     "1. A module configured to identify the strongest available cellular signal.\n"
     "2. The module of claim 1, wherein the cellular signal is 5G.\n"),
    ("a participle before the noun",
     "1. A collar assembly comprising a rear locking collar, wherein the locking collar "
     "is steel.\n"),
    ("a participle of a recited act",
     "1. A method comprising: selecting a payment gateway; and processing a transaction "
     "using the selected payment gateway.\n"),
    ("a participle of a recited act spelled with a y/i change",
     "1. A process comprising: applying a coating composition onto a filament; and "
     "fixing the applied coating composition on the filament.\n"),
    ("an irregular past participle of a recited act",
     "1. A method comprising: winding a coated filament onto a roll, wherein the wound "
     "coated filament is unwound later.\n"),
    ("'resulting' points back at the element, it does not narrow it",
     "1. A method comprising: forming a mixture from a powder and a liquid, wherein the "
     "resulting mixture is heated.\n"),
    ("a trailing 'downstream'",
     "1. A unit comprising a drying section and an optional clearance section downstream "
     "of the drying section, wherein the optional clearance section is heated.\n"),
    ("the object of 'of' after an act noun is recited too",
     "1. A method comprising: producing a paste by a mixing of individual components in "
     "a mixer, wherein each of the individual components is metered.\n"),
])
def test_introductions_the_parser_must_see(case, claims):
    assert [f for f in findings(claims) if f[1] in (MISSING, POSSIBLY)] == [], case


# -- errors that must stay errors -----------------------------------------------------------


def test_an_element_never_introduced_is_an_error():
    """A granted patent's real error, reduced: nothing introduces the divider."""
    assert findings(
        "1. A system comprising a first charge pump and a controller.\n"
        "2. The system of claim 1, wherein the controller couples the first charge pump "
        "to the first capacitive voltage divider.\n"
    ) == [(2, MISSING, "the first capacitive voltage divider")]


def test_a_concrete_element_is_not_excused_by_a_similar_verb():
    """"the base station" is not an act of "based"; "the controller" not of "controlling"."""
    result = findings(
        "1. A method comprising controlling a valve based on a signal received from the "
        "base station, wherein the controller is remote.\n"
    )
    assert (1, MISSING, "the base station") in result
    assert (1, MISSING, "the controller") in result


def test_a_bare_act_noun_is_a_double_check():
    """"changing the ownership" ... "the change": recited only as a verb."""
    assert findings(
        "1. A method comprising changing an ownership of a page, wherein the change is "
        "logged.\n"
    ) == [(1, POSSIBLY, "the change")]


def test_a_nominalised_act_is_a_double_check_not_an_error():
    """
    "the extrusion" <- "extruding", "the initial production" <- "initially producing".
    Something in the claim could be the antecedent, so these are warnings; reporting
    them as errors said a granted claim was indefinite when it was not.
    """
    assert findings(
        "1. A method comprising: extruding a plurality of strands onto a substrate, "
        "wherein a layer remains during the extrusion of the strands.\n"
    ) == [(1, POSSIBLY, "the extrusion")]
    assert findings(
        "1. A method comprising the step of initially producing a coating composition, "
        "and passing the composition after the initial production thereof to a unit.\n"
    ) == [(1, POSSIBLY, "the initial production")]


def test_an_act_noun_does_not_excuse_an_element_the_claim_never_recites():
    """"the resulting slurry" has no slurry to point back at."""
    assert findings(
        "1. A method comprising: heating a powder, wherein the resulting slurry is "
        "cooled.\n"
    ) == [(1, MISSING, "the resulting slurry")]


def test_an_of_object_introduces_only_what_it_governs():
    """"a mixing of individual components" recites the components, not every element."""
    assert findings(
        "1. A method comprising: a mixing of individual components in a mixer, wherein "
        "the pressure sensors are read.\n"
    ) == [(1, MISSING, "the pressure sensors")]


def test_a_quantifier_of_object_is_not_a_plural_introduction():
    """
    "a first pair of cameras" counts cameras; it must not introduce a plural "cameras"
    that the singular "the first camera" then contradicts.
    """
    assert findings(
        "1. A device comprising a first pair of cameras and a first camera, wherein the "
        "first camera is tilted.\n"
    ) == []


def test_a_shortened_reading_does_not_hide_a_missing_element():
    """"an image" must not supply "the image processing device"."""
    result = findings(
        "1. A method comprising receiving an image, wherein the image processing device "
        "filters the image.\n"
    )
    assert any(f[2] == "the image processing device" and f[1] in (MISSING, POSSIBLY)
               for f in result)


# -- ambiguous antecedent basis (spec 3.3) ----------------------------------------------------

AMBIGUOUS = "AMBIGUOUS_ANTECEDENT"


def test_two_elements_answering_to_one_reference_is_ambiguous():
    """MPEP 2173.05(e): two housings are recited, so "the housing" does not say which."""
    assert findings(
        "1. A device comprising a bottom housing and a top housing, wherein the housing "
        "is steel.\n"
    ) == [(1, AMBIGUOUS, "the housing")]


def test_ambiguity_is_read_along_the_claim_chain():
    """The second element arrives in the dependent claim that then refers to both."""
    assert findings(
        "1. A device comprising a bottom housing.\n"
        "2. The device of claim 1, further comprising a top housing, wherein the housing "
        "is steel.\n"
    ) == [(2, AMBIGUOUS, "the housing")]


@pytest.mark.parametrize("case,claims", [
    ("an ordinal says which one",
     "1. A device comprising a first wheel and a second wheel, wherein the first wheel "
     "turns.\n"),
    ("the introduction's own wording says which one",
     "1. A device comprising a semiconductor material and a first semiconductor "
     "material, wherein the semiconductor material is doped.\n"),
    ("a plural reference covers the group",
     "1. A device comprising a first ring oscillator and a second ring oscillator, "
     "wherein the ring oscillators are coupled.\n"),
    ("a distributive reference reaches every one",
     "1. A device comprising a first face and a peripheral face, wherein each of the "
     "faces is flat.\n"),
    ("a deictic modifier pairs it with its context",
     "1. A device comprising a first face and a peripheral face, wherein the respective "
     "face is flat.\n"),
    ("a dependent claim's opening back-reference names no element",
     "1. A modular system comprising an intelligent control system and a relay.\n"
     "2. The system of claim 1, wherein the relay is fast.\n"),
])
def test_references_that_say_which_element_they_mean(case, claims):
    assert [f for f in findings(claims) if f[1] == AMBIGUOUS] == [], case


# -- claim boundaries -------------------------------------------------------------------------


def test_a_number_starting_a_line_inside_a_claim_is_not_a_claim():
    text = (
        "1. A composition having a viscosity of\n"
        "4300. cP at 25 C.\n"
        "2. The composition of claim 1, further comprising a filler.\n"
    )
    assert [claim.number for claim in ClaimSplitter().split(text)] == [1, 2]
