"""
Claim Master report endpoints.

``/report`` returns the findings as JSON, ``/report/pdf`` returns the rendered report.
Both run the same pipeline; the PDF route simply renders what the JSON route returns.
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.exceptions import FileSizeLimitExceededError
from app.report.models import CMReport
from app.report.service import report_service

router = APIRouter(tags=["Claim Master Report"])


async def _read_upload(file: UploadFile) -> bytes:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_FILE_SIZE_BYTES:
        raise FileSizeLimitExceededError(
            f"File size exceeds the {settings.MAX_FILE_SIZE_MB}MB limit."
        )
    return file_bytes


@router.post("/report", response_model=CMReport)
async def build_report(file: UploadFile = File(...)):
    """
    Runs every available Claim Master module over the uploaded document.

    Sections I to III (claim hierarchy, claim errors, antecedents) are analysed today;
    the specification sections report as pending until their modules are enabled.
    """
    file_bytes = await _read_upload(file)
    return report_service.build(file_bytes, file.filename)


@router.post("/report/pdf")
async def build_report_pdf(file: UploadFile = File(...)):
    """The same report, rendered as the Claim Master PDF."""
    file_bytes = await _read_upload(file)
    _report, pdf_path = report_service.build_and_render(file_bytes, file.filename)

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename="claim_master_report.pdf",
        headers={"Content-Disposition": 'attachment; filename="claim_master_report.pdf"'},
    )
