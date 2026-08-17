import time
from typing import Dict, Any, List
from fastapi import APIRouter, UploadFile, File, HTTPException, Path as APIPath
from fastapi.responses import FileResponse
from pathlib import Path
import os
from app.services.parser_service import parser_service
from app.core.config import settings
from app.api.models import ParseResponse, BatchParseResponse, HealthResponse, MetricsResponse
from app.core.exceptions import FileSizeLimitExceededError

router = APIRouter()

# Metrics tracking
_metrics = {
    "total_processed": 0,
    "total_processing_time_ms": 0,
    "ocr_usage_count": 0
}
_start_time = time.time()

def _check_file_size(file_bytes: bytes):
    if len(file_bytes) > settings.MAX_FILE_SIZE_BYTES:
        raise FileSizeLimitExceededError(f"File size exceeds the {settings.MAX_FILE_SIZE_MB}MB limit.")

@router.post("/parse", summary="Parse patent document and return json output", response_model=ParseResponse)
async def parse_document(file: UploadFile = File(...)):
    """
    Parse an uploaded patent document (XML) and return enhanced JSON.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    start = time.time()
    file_bytes = await file.read()
    _check_file_size(file_bytes)
    
    doc = parser_service.parse(file_bytes, file.filename)
    
    processing_time_ms = int((time.time() - start) * 1000)
    
    # Update metrics
    _metrics["total_processed"] += 1
    _metrics["total_processing_time_ms"] += processing_time_ms
    if doc.ocr_used:
        _metrics["ocr_usage_count"] += 1
    
    # Set download URLs if PDF generated
    download_endpoint = None
    if doc.pdf_path:
        filename = Path(doc.pdf_path).name
        download_endpoint = f"/api/v1/download/{filename}"
   
    return ParseResponse(
        status="success",
        document_type=doc.input_type.value if doc.input_type else "UNKNOWN",
        claim_count=doc.claim_count,
        independent_claims=len(doc.independent_claims),
        dependent_claims=len(doc.dependent_claims),
        ocr_used=doc.ocr_used ,
        processing_time_ms=processing_time_ms,
        confidence=doc.confidence_score,
        download_endpoint=download_endpoint,
        pdf_generated=doc.pdf_path is not None,
        pdf_path=doc.pdf_path,
        claims=doc.claims,
        metadata=doc.metadata
    )

