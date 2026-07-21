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

@router.post("/parse", summary="Parse patent document", response_model=ParseResponse)
async def parse_document(file: UploadFile = File(...)):
    """
    Parse an uploaded patent document (XML, PDF, TXT) and return enhanced JSON.
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
        ocr_used=doc.ocr_used,
        processing_time_ms=processing_time_ms,
        confidence=doc.confidence_score,
        download_endpoint=download_endpoint,
        pdf_generated=doc.pdf_path is not None,
        pdf_path=doc.pdf_path,
        claims=doc.claims,
        metadata=doc.metadata
    )
# @router.post("/parse/pdf", summary="Parse patent document and return PDF")
# async def parse_document_pdf(file: UploadFile = File(...)):
#     """
#     Parse an uploaded patent document and return the generated USPTO-style PDF.
#     """
#     if not file.filename:
#         raise HTTPException(status_code=400, detail="No file provided")
    
#     file_bytes = await file.read()
#     _check_file_size(file_bytes)
    
#     try:
#         doc = parser_service.parse(file_bytes, file.filename, generate_pdf=True)
#         if not doc.pdf_path or not os.path.exists(doc.pdf_path):
#             raise HTTPException(status_code=500, detail="PDF generation failed.")
            
#         filename = Path(doc.pdf_path).name
#         return FileResponse(
#             path=doc.pdf_path,
#             media_type="application/pdf",
#             filename=filename
#         )
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @router.get("/download/{filename}", summary="Download generated PDF")
# async def download_pdf(filename: str = APIPath(..., description="The name of the generated PDF")):
#     """
#     Download a previously generated PDF.
#     """
#     # Sanitize filename
#     filename = os.path.basename(filename)
#     file_path = settings.OUTPUT_DIR / filename
    
#     if not file_path.exists() or not file_path.is_file():
#         raise HTTPException(status_code=404, detail="PDF not found.")
        
#     return FileResponse(
#         path=str(file_path),
#         media_type="application/pdf",
#         filename=filename
#     )
# @router.post("/parse/batch", summary="Batch parse multiple files", response_model=BatchParseResponse)
# async def parse_batch(files: List[UploadFile] = File(...)):
#     """
#     Accepts multiple files, processes them independently, and returns aggregated results.
#     """
#     results = []
#     processed = 0
#     failed = 0
    
#     for file in files:
#         if not file.filename:
#             continue
            
#         try:
#             start = time.time()
#             file_bytes = await file.read()
#             _check_file_size(file_bytes)
            
#             doc = parser_service.parse(file_bytes, file.filename)
#             processing_time = int((time.time() - start) * 1000)
            
#             results.append({
#                 "filename": file.filename,
#                 "status": "success",
#                 "document_type": doc.input_type.value,
#                 "claim_count": doc.claim_count,
#                 "confidence": doc.confidence_score,
#                 "processing_time_ms": processing_time
#             })
#             processed += 1
#         except Exception as e:
#             results.append({
#                 "filename": file.filename,
#                 "status": "error",
#                 "error": str(e)
#             })
#             failed += 1
            
#     return BatchParseResponse(
#         total_files=len(files),
#         processed=processed,
#         failed=failed,
#         results=results
#     )

# @router.post("/export/zip", summary="Export parsed claims as ZIP archive")
# async def export_zip(files: List[UploadFile] = File(...)):
#     """
#     Processes files and generates a ZIP archive containing JSON and PDF formats.
#     """
#     import zipfile
#     import json
#     import tempfile
#     import os
#     from fastapi.responses import FileResponse
#     from fastapi.background import BackgroundTasks
    
#     if not files:
#         raise HTTPException(status_code=400, detail="No files provided")
        
#     temp_dir = tempfile.mkdtemp()
#     zip_path = os.path.join(temp_dir, "Patent_Claims.zip")
    
#     summary = []
    
#     with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
#         for file in files:
#             if not file.filename:
#                 continue
            
#             base_name = os.path.splitext(file.filename)[0]
#             try:
#                 file_bytes = await file.read()
#                 _check_file_size(file_bytes)
#                 doc = parser_service.parse(file_bytes, file.filename)
                
#                 # Write JSON
#                 json_data = doc.model_dump_json(indent=2)
#                 zipf.writestr(f"{base_name}.json", json_data)
                
#                 # Write PDF
#                 if doc.pdf_path and os.path.exists(doc.pdf_path):
#                     with open(doc.pdf_path, 'rb') as f:
#                         zipf.writestr(f"{base_name}.pdf", f.read())
#                 else:
#                     raise Exception("PDF generation failed during zip export")
                
#                 summary.append({"filename": file.filename, "status": "success", "claims": doc.claim_count})
#             except Exception as e:
#                 summary.append({"filename": file.filename, "status": "error", "error": str(e)})
                
#         # Write summary
#         zipf.writestr("summary.json", json.dumps({"summary": summary}, indent=2))
        
#     def cleanup():
#         if os.path.exists(zip_path):
#             os.remove(zip_path)
#         if os.path.exists(temp_dir):
#             os.rmdir(temp_dir)
            
#     # Normally we'd use BackgroundTasks to cleanup, but for simplicity here we return it directly
#     return FileResponse(zip_path, media_type="application/zip", filename="Patent_Claims.zip")

@router.get("/health", summary="Detailed Health Check", response_model=HealthResponse)
async def health_check():
    import datetime
    uptime = str(datetime.timedelta(seconds=int(time.time() - _start_time)))
    
    return HealthResponse(
        status="healthy",
        version=settings.VERSION,
        uptime=uptime,
        ocr_availability=True, # Depending on OCR provider config
        supported_formats=["USPTO XML", "Generic XML", "Text PDF", "Scanned PDF", "TXT", "Raw Text"],
        temporary_storage_status="OK"
    )

# @router.get("/version", summary="Get API Version")
# async def get_version():
#     return {"version": settings.VERSION}

# @router.get("/metrics", summary="Get API Metrics", response_model=MetricsResponse)
# async def get_metrics():
#     avg_time = 0
#     if _metrics["total_processed"] > 0:
#         avg_time = _metrics["total_processing_time_ms"] // _metrics["total_processed"]
        
#     return MetricsResponse(
#         total_processed=_metrics["total_processed"],
#         average_processing_time_ms=avg_time,
#         ocr_usage_count=_metrics["ocr_usage_count"]
#     )
