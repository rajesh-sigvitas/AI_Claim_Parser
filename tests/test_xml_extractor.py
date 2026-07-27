import pytest
from app.extractor.xml import USPTOXMLExtractor
from app.models.claim import ClaimType
import re

def test_uspto_xml_extraction():
    xml_content = b"""
    <us-patent-grant>
        <claims>
            <claim id="CLM-00001">
                <claim-text><b>1</b>. A system comprising:
                    <claim-text>a processor;</claim-text>
                    <claim-text>a memory;</claim-text>
                </claim-text>
            </claim>
            <claim id="CLM-00002">
                <claim-text><b>2</b>. The system of <claim-ref idref="CLM-00001">claim 1</claim-ref>, wherein the processor is fast.</claim-text>
            </claim>
        </claims>
    </us-patent-grant>
    """
    extractor = USPTOXMLExtractor()
    claims, metadata = extractor.extract(xml_content)
    
    assert len(claims) == 2
    assert claims[0].number == 1
    assert claims[0].header == "A system comprising:"
    assert len(claims[0].elements) == 2
    assert claims[0].elements[0].text == "a processor;"
    assert claims[0].references == []
    
    assert claims[1].number == 2
    assert claims[1].header == "The system of claim 1, wherein the processor is fast."
    assert claims[1].parent_claim == 1
    assert len(claims[1].references) == 1
    assert claims[1].references[0] == {
        "text": "claim 1",
        "claim_number": 1,
        "idref": "CLM-00001"
    }
