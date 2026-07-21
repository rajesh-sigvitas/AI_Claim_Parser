from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    PROJECT_NAME: str = "Claim Parser AI"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Deployment & Paths
    UPLOAD_DIR: Path = Path("/tmp/claim_parser/uploads")
    OUTPUT_DIR: Path = Path("/tmp/claim_parser/outputs")
    
    # Security & Limits
    MAX_FILE_SIZE_MB: int = 50
    MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024
    
    # Processing
    WORKER_COUNT: int = 4
    LOGGING_LEVEL: str = "INFO"
    
    # OCR
    OCR_PROVIDER: str = "llama_scout" # or "tesseract", "paddle"
    OCR_API_KEY: str = ""
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore")

settings = Settings()

# Ensure directories exist
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
