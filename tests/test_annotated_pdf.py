import pytest
import os
from fastapi.testclient import TestClient
from app.main import app
from app.analysis.models import FindingType

client = TestClient(app)

def test_annotated_pdf_generation():
    text = """
    What is claimed is:
    1. A system comprising:
    a memory;
    the processor coupled to the memory.
    """
    
    response = client.post(
        "/api/v1/analyze/antecedents/pdf",
        files={"file": ("test.txt", text.encode("utf-8"), "text/plain")}
    )
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "antecedent_analysis_report.pdf" in response.headers["content-disposition"]
    
    # Save to check manually if desired, but we just verify it isn't empty
    pdf_content = response.content
    assert len(pdf_content) > 1000
    assert pdf_content.startswith(b"%PDF")
