from app.api.endpoints import parse_doc_json, health, doc_to_pdf, analysis, report
from fastapi import APIRouter

api_router = APIRouter()

api_router.include_router(parse_doc_json.router)
api_router.include_router(health.router)
api_router.include_router(doc_to_pdf.router)
api_router.include_router(analysis.router)
api_router.include_router(report.router)
