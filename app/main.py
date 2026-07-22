from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import api_router
from app.core.config import settings
from app.core.exceptions import setup_exception_handlers
from app.core.logger import setup_logger

# Ensure logger is setup
setup_logger()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI-Powered Patent Claim Reconstruction & Formatting Engine",
)

# CORS middleware for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register central error handlers
setup_exception_handlers(app)

# Include API Router
app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/", tags=["Root"])
def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME} API"}
