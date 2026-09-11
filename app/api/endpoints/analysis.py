"""
Standalone antecedent analysis endpoints.

These report antecedent *errors* only -- a reference with no antecedent basis, and a
reference that comes before its introduction.  The limiting-preamble and singular/plural
checks are advisory, so they stay in the full Claim Master report (``/report``).

The upload goes through the same loading path as the Claim Master report: the document is
laid out and paginated, the claims section is found and parsed, and amendment markup is
resolved, so a claim reads identically here and in section III of the full report.
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.analysis.models import AntecedentAnalysisResult
from app.core.config import settings
from app.core.exceptions import FileSizeLimitExceededError
from app.report.models import CMReport
from app.report.service import report_service

router = APIRouter(tags=["Antecedent Module"])


async def _read_upload(file: UploadFile) -> bytes:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_FILE_SIZE_BYTES:
        raise FileSizeLimitExceededError(
            f"File size exceeds the {settings.MAX_FILE_SIZE_MB}MB limit."
        )
    return file_bytes


async def _antecedent_report(file: UploadFile) -> CMReport:
    report = report_service.build_antecedent_report(await _read_upload(file), file.filename)
    if report.antecedents is None:
        raise HTTPException(
            status_code=500,
            detail=report.notes.get("III", "Antecedent analysis failed."),
        )
    return report


@router.post("/analyze/antecedents", response_model=AntecedentAnalysisResult)
async def analyze_antecedents(file: UploadFile = File(...)):
    """
    Report antecedent and reverse antecedent errors in the uploaded claims.
    """
    report = await _antecedent_report(file)
    return report.antecedents


@router.post("/analyze/antecedents/pdf")
async def analyze_antecedents_pdf(file: UploadFile = File(...)):
    """
    Same analysis, returned as a PDF with every error marked in the claims.
    """
    report = await _antecedent_report(file)
    pdf_path = report_service.generate_antecedent_pdf(report)

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename="antecedent_analysis_report.pdf",
        headers={
            "Content-Disposition": 'attachment; filename="antecedent_analysis_report.pdf"'
        },
    )
