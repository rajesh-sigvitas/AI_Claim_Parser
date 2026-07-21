from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from app.models.claim import Claim

class ParseResponse(BaseModel):
    """Enhanced response for document parsing."""
    status: str
    document_type: str
    claim_count: int
    independent_claims: int
    dependent_claims: int
    ocr_used: bool
    processing_time_ms: int
    confidence: float
    download_url: Optional[str] = None
    download_endpoint: Optional[str] = None
    pdf_generated: bool = False
    pdf_path: Optional[str] = None
    json_url: Optional[str] = None
    pdf_url: Optional[str] = None
    claims: Optional[List[Claim]] = None
    metadata: Dict[str, Any] = {}

class BatchParseResponse(BaseModel):
    """Response for batch parsing."""
    total_files: int
    processed: int
    failed: int
    results: List[Dict[str, Any]]

class HealthResponse(BaseModel):
    """Health status of the API."""
    status: str
    version: str
    uptime: str
    ocr_availability: bool
    supported_formats: List[str]
    temporary_storage_status: str

class MetricsResponse(BaseModel):
    """Metrics for the API."""
    total_processed: int
    average_processing_time_ms: int
    ocr_usage_count: int
