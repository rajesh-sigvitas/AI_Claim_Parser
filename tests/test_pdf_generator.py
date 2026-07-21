import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.formatter.pdf_generator import PDFGenerator
from app.models.document import ClaimDocument
from app.models.claim import Claim, ClaimElement
from app.core.constants import InputType, ClaimType
import io

client = TestClient(app)

def test_pdf_generator_creation(tmp_path):
    generator = PDFGenerator(output_dir=str(tmp_path))
    
    from app.core.constants import ElementType
    # Create a complex document with nested elements
    el1 = ClaimElement(text="(a) receiving;", level=1, element_type=ElementType.ENUMERATION, order=1)
    el2 = ClaimElement(text="(b) processing;", level=1, element_type=ElementType.ENUMERATION, order=2)
    c1 = Claim(
        number=1,
        claim_type=ClaimType.INDEPENDENT,
        claim_text="A method comprising:",
        header="A method comprising:",
        elements=[el1, el2]
    )
    
    # Long text to force line wrap
    c2 = Claim(
        number=2,
        claim_type=ClaimType.DEPENDENT,
        parent_claim=1,
        claim_text="The method of claim 1, wherein the processing is performed by a server and takes a long time without breaking the indentation." * 5,
        header="The method of claim 1 wherein:",
    )
    
    doc = ClaimDocument(
        input_type=InputType.RAW_TEXT,
        claims=[c1, c2],
        confidence_score=99.0
    )
    
    pdf_path = generator.generate(doc)
    assert os.path.exists(pdf_path)
    assert str(pdf_path).endswith(".pdf")
    
    # Check that it's actually a PDF file
    with open(pdf_path, 'rb') as f:
        header = f.read(5)
        assert header == b"%PDF-"

def test_parse_to_pdf_endpoint():
    file_content = b"What is claimed is:\n1. A method comprising receiving data.\n2. The method of claim 1."
    files = {'file': ('test.txt', io.BytesIO(file_content), 'text/plain')}
    
    response = client.post("/api/v1/parse/pdf", files=files)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")

def test_parse_and_download_flow():
    file_content = b"What is claimed is:\n1. A system comprising a processor; and a memory.\n"
    files = {'file': ('test2.txt', io.BytesIO(file_content), 'text/plain')}
    
    # 1. Parse which should generate PDF
    response = client.post("/api/v1/parse", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["pdf_generated"] is True
    assert data["download_endpoint"] is not None
    
    # 2. Download the generated PDF
    download_url = data["download_endpoint"]
    dl_response = client.get(download_url)
    assert dl_response.status_code == 200
    assert dl_response.headers["content-type"] == "application/pdf"
    assert dl_response.content.startswith(b"%PDF-")
