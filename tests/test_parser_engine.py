import pytest
from app.parser.engine import ParserEngine
from app.core.constants import InputType, ClaimType
from app.normalizer.engine import NormalizationEngine

def test_parser_engine_full_pipeline():
    # Example text representing raw text extracted from a PDF or OCR
    # Contains: preamble junk, claim statement, independent claim, dependent claim, OCR errors
    raw_text = """
    US Patent No. 12,345,678
    Page 14 of 40
    
    What is claimed is:
    
    1. A method cornprising:
    (a) receiving a request;
    (b) processing the request; and
    (c) sending a response.
    
    2. The method of claim 1, whereln the request is processed by a server.
    
    3. A system comprising:
    a processor;
    a memory; and
    a display.
    
    4. The system of claims 2-3, further comprising a network interface.
    """
    
    # 1. Normalize
    normalizer = NormalizationEngine()
    normalized_text, ops = normalizer.normalize(raw_text)
    
    # Verify OCR and Page normalizations
    assert "page_artifacts_removed" in ops
    assert "ocr_cleanup_applied" in ops
    assert "cornprising" not in normalized_text
    assert "whereln" not in normalized_text
    assert "comprising" in normalized_text
    assert "wherein" in normalized_text
    
    # 2. Parse
    parser = ParserEngine()
    doc = parser.parse(normalized_text, InputType.RAW_TEXT)
    
    # Verify Claims Document
    assert doc.input_type == InputType.RAW_TEXT
    assert doc.confidence_score > 90.0
    assert len(doc.claims) == 4
    
    # Claim 1: Independent Method Claim with Enumerations
    c1 = doc.claims[0]
    assert c1.number == 1
    assert c1.claim_type == ClaimType.INDEPENDENT
    assert c1.parent_claim is None
    assert c1.metadata["claim_category"] == "method"
    assert "comprising:" in c1.header
    assert len(c1.elements) == 3
    assert c1.elements[0].text == "receiving a request;"
    assert c1.elements[0].level == 1
    
    # Claim 2: Dependent Claim
    c2 = doc.claims[1]
    assert c2.number == 2
    assert c2.claim_type == ClaimType.DEPENDENT
    assert c2.parent_claim == 1
    assert c2.metadata["parent_claims"] == [1]
    
    # Claim 3: Independent System Claim with Semicolons
    c3 = doc.claims[2]
    assert c3.number == 3
    assert c3.claim_type == ClaimType.INDEPENDENT
    assert c3.metadata["claim_category"] == "system"
    assert "comprising:" in c3.header
    assert len(c3.elements) == 3
    assert c3.elements[0].text == "a processor;"
    
    # Claim 4: Dependent Claim with Range
    c4 = doc.claims[3]
    assert c4.number == 4
    assert c4.claim_type == ClaimType.DEPENDENT
    assert c4.parent_claim == 2
    assert c4.metadata["parent_claims"] == [2, 3]

def test_parser_engine_validation():
    parser = ParserEngine()
    
    # Duplicate claim number
    bad_text_1 = "What is claimed is:\n1. A method.\n1. A system."
    with pytest.raises(ValueError, match="Duplicate claim number"):
        parser.parse(bad_text_1, InputType.RAW_TEXT)
        
    # Missing claim body
    bad_text_2 = "What is claimed is:\n1.  \n2. A system."
    with pytest.raises(ValueError, match="empty body text"):
        parser.parse(bad_text_2, InputType.RAW_TEXT)
