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


@router.post("/parse/pdf", summary="Parse patent document and return PDF")
async def parse_document_pdf(file: UploadFile = File(...)):
    """
    Parse an uploaded patent document and return the generated USPTO-style PDF.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    file_bytes = await file.read()
    _check_file_size(file_bytes)
    
    try:
        doc = parser_service.parse(file_bytes, file.filename, generate_pdf=True)
        if not doc.pdf_path or not os.path.exists(doc.pdf_path):
            raise HTTPException(status_code=500, detail="PDF generation failed.")
            
        filename = Path(doc.pdf_path).name
        return FileResponse(
            path=doc.pdf_path,
            media_type="application/pdf",
            filename=filename
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# @router.get("/download/{filename}", summary="Download a generated PDF")
# async def download_pdf(filename: str):
#     """
#     Download a previously generated PDF file.
#     """
#     file_path = settings.OUTPUT_DIR / filename
#     if not file_path.exists():
#         raise HTTPException(status_code=404, detail="File not found")
        
#     return FileResponse(
#         path=file_path,
#         media_type="application/pdf",
#         filename=filename
#     )