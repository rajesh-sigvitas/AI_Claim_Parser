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

@router.get("/health", summary="Detailed Health Check", response_model=HealthResponse)
async def health_check():
    import datetime

    _start_time = time.time()
    uptime = str(datetime.timedelta(seconds=int(time.time() - _start_time)))
    
    return HealthResponse(
        status="healthy",
        version=settings.VERSION,
        uptime=uptime,
        ocr_availability=True, # Depending on OCR provider config
        supported_formats=["USPTO XML", "Generic XML", "Text PDF", "Scanned PDF", "TXT", "Raw Text"],
        temporary_storage_status="OK"
    )
