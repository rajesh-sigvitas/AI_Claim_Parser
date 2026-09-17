import pytest
from app.parser.engine import ParserEngine
from app.core.constants import InputType
from app.analysis.service import analysis_service
from app.analysis.models import FindingType

@pytest.fixture
def parser():
    return ParserEngine()

ANTECEDENT_DEFECTS = (FindingType.MISSING_ANTECEDENT, FindingType.REVERSE_ANTECEDENT)


def _analyze_text(parser, text):
    """
    Antecedent defects only.

    Section III also reports limiting preambles and number mismatches, which are
    questions put to the drafter rather than defects.  These tests are about basis
    resolution, so the advisory findings are filtered out here and covered by their
    own tests below; otherwise every independent claim in the suite would carry a
    preamble finding and each count would have to be re-baselined.
    """
    result = _analyze_full(parser, text)
    result.findings = [f for f in result.findings if f.type in ANTECEDENT_DEFECTS]
    result.total_findings = len(result.findings)
    return result


def _analyze_full(parser, text):
    """Every section III finding, advisory ones included."""
    doc = parser.parse(text, InputType.RAW_TEXT)
    return analysis_service.analyze_antecedents(doc)

def test_valid_simple_antecedent(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    a processor;
    a memory coupled to the processor.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0

def test_missing_antecedent(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    a memory coupled to the processor.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 1
    assert res.findings[0].type == FindingType.MISSING_ANTECEDENT
    assert res.findings[0].term == "the processor"

def test_reverse_antecedent(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    a processor configured to communicate with the controller;
    a controller.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 1
    assert res.findings[0].type == FindingType.REVERSE_ANTECEDENT
    assert res.findings[0].term == "the controller"

def test_dependent_claim_inheritance(parser):
    text = """
    What is claimed is:
    1. A system comprising a processor.
    2. The system of claim 1, wherein the processor is configured to process data.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0

def test_number_agreement_is_not_an_antecedent_defect(parser):
    """A plural reference still resolves against its singular introduction."""
    text = """
    What is claimed is:
    5. A system comprising:
    a primary suction conduit;
    the primary suction conduits.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0

def test_legitimate_plurality(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    a plurality of processors;
    the processors configured to process data;
    each processor coupled to a memory.
    """
    res = _analyze_text(parser, text)
    # "a plurality of processors" supports both "the processors" and
    # "each processor".
    assert res.total_findings == 0

def test_first_second_terms(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    a first processor;
    a second processor;
    the first processor coupled to the second processor.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0

def test_said_term_reference(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    a processor;
    said processor configured to process data.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0

def test_limiting_preamble_is_not_an_antecedent_defect(parser):
    """A preamble term reused in the body has proper basis; it is only a warning."""
    text = """
    What is claimed is:
    1. A base assembly of a cleaning appliance, the base assembly comprises:
    a processor;
    the base assembly configured to clean.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0

def test_preamble_without_reuse(parser):
    text = """
    What is claimed is:
    1. A base assembly of a cleaning appliance, the base assembly comprises:
    a processor;
    the processor configured to clean.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0

def test_multiple_dependent_inheritance(parser):
    text = """
    What is claimed is:
    1. A system comprising a processor.
    2. A system comprising a memory.
    3. The system of claims 1-2, wherein the processor is coupled to the memory.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0

def test_trailing_verb_removal(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    a processor configured to run;
    the processor rolling.
    """
    res = _analyze_text(parser, text)
    # The term 'processor configured to run' is stopped by 'configured'. So intro is 'processor'.
    # The reference 'the processor rolling' is stopped by 'rolling'. So ref is 'processor'.
    assert res.total_findings == 0

def test_noun_phrase_extraction_punctuation(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    a first processor, a memory;
    the first processor coupled to the memory.
    """
    res = _analyze_text(parser, text)
    # Punctuation (comma) should stop the noun phrase cleanly.
    assert res.total_findings == 0

def test_normalization_hyphens(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    a sub-bent portion;
    the subbent portion.
    """
    res = _analyze_text(parser, text)
    # Hyphens should be normalized away
    assert res.total_findings == 0


# ---------------------------------------------------------------------------
# Regression tests for defects in the previous implementation.
# ---------------------------------------------------------------------------

def test_reverse_antecedent_within_a_single_element(parser):
    """
    The old resolver re-scanned the whole element containing the reference to
    look for a bare introduction, so a reference and its introduction sitting
    in the same element never registered as reversed.
    """
    text = """
    What is claimed is:
    1. A system comprising:
    a housing supporting the widget and a widget.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 1
    assert res.findings[0].type == FindingType.REVERSE_ANTECEDENT
    assert res.findings[0].term == "the widget"


def test_reverse_antecedent_in_dependent_claim(parser):
    text = """
    What is claimed is:
    1. A system comprising a base.
    2. The system of claim 1, wherein the flange extends from the base, and a flange is welded.
    """
    res = _analyze_text(parser, text)
    reverse = [f for f in res.findings if f.type == FindingType.REVERSE_ANTECEDENT]
    assert len(reverse) == 1
    assert reverse[0].claim_number == 2
    assert reverse[0].term == "the flange"


def test_verb_is_not_absorbed_into_the_term(parser):
    """"the memory stores a memory map" must yield "memory", not "memory stores"."""
    text = """
    What is claimed is:
    1. A system comprising:
    a memory, wherein the memory stores a memory map for the processor.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 1
    assert res.findings[0].term == "the processor"


def test_deictic_modifier_resolves_to_its_antecedent(parser):
    """"the corresponding X" has antecedent basis in a bare plural "X"."""
    text = """
    What is claimed is:
    1. A system comprising:
    stationary rail bearings disposed in a space;
    surfaces in contact with the corresponding stationary rail bearings.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0


def test_compound_ordinal_reference(parser):
    """"the first and second tracks" resolves against each singular track."""
    text = """
    What is claimed is:
    1. A system comprising:
    a first track;
    a second track;
    bearings contacting the first and second tracks.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0


def test_compound_ordinal_reference_reports_the_unsupported_half(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    a first track;
    bearings contacting the first and second tracks.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 1
    assert res.findings[0].type == FindingType.MISSING_ANTECEDENT
    assert "second" in res.findings[0].term


def test_at_least_one_introduces_a_term(parser):
    text = """
    What is claimed is:
    1. A system comprising:
    at least one sensor;
    the sensor coupled to a memory.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0


def test_inherent_part_needs_no_antecedent(parser):
    """"the bottom of the housing" is inherent; "the open bottom" is not."""
    text = """
    What is claimed is:
    1. A system comprising:
    a housing;
    a lid attached to the bottom of the housing.
    2. The system of claim 1, wherein a bracket passes through the open bottom of the housing.
    """
    res = _analyze_full(parser, text)
    reported = ANTECEDENT_DEFECTS + (FindingType.POSSIBLY_MISSING_ANTECEDENT,)
    terms = [f.term for f in res.findings if f.type in reported]
    # Reported -- as "possibly missing": the housing it belongs to is introduced, so it
    # may be an inherent feature (MPEP 2173.05(e)), which a reviewer has to confirm.
    assert "the open bottom" in terms
    assert not any("the bottom" == t for t in terms)


def test_findings_carry_exact_character_offsets(parser):
    """Offsets are what the report uses to highlight the right words."""
    text = """
    What is claimed is:
    1. A system comprising:
    a memory coupled to the processor.
    """
    res = _analyze_text(parser, text)
    finding = res.findings[0]
    location = finding.location
    assert location.char_start is not None and location.char_end is not None
    assert location.element_text is not None
    excerpt = location.element_text[location.char_start:location.char_end]
    assert excerpt == "the processor"


def test_predicative_adjective_is_excluded_from_the_term(parser):
    """"making a movable body slidable" introduces "a movable body"."""
    text = """
    What is claimed is:
    1. A device for making a movable body slidable with respect to a support, comprising:
    a rail attached to the movable body.
    """
    res = _analyze_text(parser, text)
    assert res.total_findings == 0


# -- limiting preamble (MPEP 2111.02) ---------------------------------------


def test_limiting_preamble_reports_every_preamble_element(parser):
    """
    Ground truth: the reference Claim Master report for MID101312US flags all four
    elements introduced in claim 1's preamble, whether or not the body reuses them.
    """
    text = """
    What is claimed is:
    1. A base assembly of a cleaning appliance to extract a waste solution from a
    surface, the base assembly comprises:
    a primary suction conduit at a first portion of the base assembly.
    """
    res = _analyze_full(parser, text)
    preamble = [f for f in res.findings if f.type == FindingType.LIMITING_PREAMBLE]

    assert [f.term for f in preamble] == [
        "a base assembly", "a cleaning appliance", "a waste solution", "a surface",
    ]
    assert preamble[0].message.startswith('Limiting preamble?: "a base assembly."')
    assert "MPEP 2111.02" in preamble[0].message
    # Each carries the offsets the report needs to place its {n} marker.
    assert all(f.location.element_index == -1 for f in preamble)
    assert all(f.location.char_end > f.location.char_start for f in preamble)


def test_limiting_preamble_skips_dependent_claims(parser):
    """A dependent claim's opening words are a back-reference, not a preamble."""
    text = """
    What is claimed is:
    1. A system comprising a processor.
    2. The system of claim 1, wherein the processor is coupled to a memory.
    """
    res = _analyze_full(parser, text)
    flagged = {
        f.claim_number for f in res.findings if f.type == FindingType.LIMITING_PREAMBLE
    }
    assert flagged == {1}


# -- number agreement -------------------------------------------------------


def test_number_mismatch_is_reported_within_the_claim_chain(parser):
    """Spec 3.5: nothing was recited singly, so "the suction conduit" points at nothing."""
    text = """
    What is claimed is:
    1. A base assembly comprising a plurality of suction conduits.
    2. The base assembly of claim 1, wherein the suction conduit forms a first airpath.
    """
    res = _analyze_full(parser, text)
    mismatches = [f for f in res.findings if f.type == FindingType.SINGULAR_PLURAL]

    assert len(mismatches) == 1
    assert mismatches[0].claim_number == 2
    assert mismatches[0].term == "the suction conduit"
    assert "singular and plural forms" in mismatches[0].message


def test_a_chain_that_introduces_both_numbers_contradicts_neither(parser):
    """
    The MID101312US claim 9 shape: the claim recites the set and draws a member out of
    it, so a later singular reference has an introduction to point back at.  The real
    ClaimMaster report does not flag claims 10 and 11.
    """
    text = """
    What is claimed is:
    9. A base assembly comprising a plurality of suction conduits, wherein a primary
    suction conduit of the plurality of suction conduits is positioned at a first portion.
    10. The base assembly of claim 9, wherein the primary suction conduit is adjacent to
    a secondary suction conduit.
    """
    res = _analyze_full(parser, text)
    assert [f for f in res.findings if f.type == FindingType.SINGULAR_PLURAL] == []


def test_a_sibling_claims_plurality_does_not_put_a_claim_in_the_wrong(parser):
    """
    The same claims, except claim 5 depends on claim 1 rather than on claim 4, so the
    plurality is in a sibling claim it never incorporates.

    This is the MID101312US shape.  The real ClaimMaster report for that application
    reports eleven section III findings, all limiting preambles, and does not flag
    claim 5 -- a claim is measured against its own chain, not the whole claim set.
    """
    text = """
    What is claimed is:
    1. A base assembly comprising a primary suction conduit.
    4. The base assembly of claim 1, wherein the base assembly further comprises a
    plurality of suction conduits adjacent to one another, wherein a suction conduit of
    the plurality of suction conduits is coupled to a nozzle.
    5. The base assembly of claim 1, wherein the primary suction conduit forms a first
    airpath.
    """
    res = _analyze_full(parser, text)
    assert [f for f in res.findings if f.type == FindingType.SINGULAR_PLURAL] == []


def test_a_claim_drawing_a_member_from_its_plurality_is_not_a_mismatch(parser):
    """"a suction conduit of the plurality of suction conduits" is the correct form."""
    text = """
    What is claimed is:
    1. A base assembly comprising:
    a plurality of suction conduits;
    a suction conduit of the plurality of suction conduits coupled to a nozzle.
    """
    res = _analyze_full(parser, text)
    assert not [f for f in res.findings if f.type == FindingType.SINGULAR_PLURAL]


def test_one_number_mismatch_is_reported_per_claim(parser):
    """Related terms mismatch together; the rest are recorded as evidence."""
    text = """
    What is claimed is:
    1. A base assembly comprising a plurality of suction conduits and a plurality of
    suction nozzles.
    2. The base assembly of claim 1, wherein the suction conduit is coupled to the
    suction nozzle.
    """
    res = _analyze_full(parser, text)
    mismatches = [f for f in res.findings if f.type == FindingType.SINGULAR_PLURAL]

    assert len(mismatches) == 1
    assert mismatches[0].claim_number == 2
    assert mismatches[0].evidence.get("also")
