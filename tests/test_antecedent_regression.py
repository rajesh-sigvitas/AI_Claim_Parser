import os
import pytest
from app.services.parser_service import parser_service
from app.analysis.service import analysis_service

def test_regression_test_aug_18():
    path = "/home/sig/Downloads/test_Aug_18.docx"
    if not os.path.exists(path):
        pytest.skip(f"Test file {path} not found")
        
    with open(path, "rb") as f:
        doc_bytes = f.read()
    
    doc = parser_service.parse(doc_bytes, "test_Aug_18.docx", generate_pdf=False)
    result = analysis_service.analyze_antecedents(doc)
    
    # We started with 139 findings due to extraction errors.
    # It should now be dramatically smaller (around 38 legitimate findings).
    assert result.total_findings < 50
    assert result.total_findings > 0  # There are legitimate missing antecedents
    
    # Verify some legitimate findings remain
    finding_terms = [f.term for f in result.findings]
    assert "the open bottom" in finding_terms
    assert "the open top" in finding_terms
