import pytest
from fastapi.testclient import TestClient
from app.main import app
import io

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    
def test_version_endpoint():
    response = client.get("/api/v1/version")
    assert response.status_code == 200
    assert "version" in response.json()
    
def test_metrics_endpoint():
    response = client.get("/api/v1/metrics")
    assert response.status_code == 200
    assert "total_processed" in response.json()

def test_parse_document_json_no_file():
    response = client.post("/api/v1/parse")
    assert response.status_code == 422 # Unprocessable Entity (missing file)

def test_parse_document_json():
    # Provide a mock raw text file
    file_content = b"What is claimed is:\n1. A method comprising receiving data; processing data; and sending data.\n"
    files = {'file': ('test.txt', io.BytesIO(file_content), 'text/plain')}
    
    response = client.post("/api/v1/parse", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["claim_count"] == 1
    assert data["document_type"] == "RAW_TEXT"
    
def test_parse_batch():
    # Provide mock raw text files
    f1 = b"What is claimed is:\n1. A system comprising a processor.\n"
    f2 = b"What is claimed is:\n1. A method comprising receiving data.\n"
    
    files = [
        ('files', ('test1.txt', io.BytesIO(f1), 'text/plain')),
        ('files', ('test2.txt', io.BytesIO(f2), 'text/plain'))
    ]
    
    response = client.post("/api/v1/parse/batch", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 2
    assert data["processed"] == 2
    assert data["failed"] == 0
    assert len(data["results"]) == 2

def test_export_zip():
    file_content = b"What is claimed is:\n1. A method comprising receiving data.\n"
    files = [('files', ('test.txt', io.BytesIO(file_content), 'text/plain'))]
    
    response = client.post("/api/v1/export/zip", files=files)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
