import sys
import uuid
import contextvars
from loguru import logger
from app.core.config import settings

# Context variable to hold request ID for log correlation
request_id_var = contextvars.ContextVar("request_id", default="system")

def _correlation_id_filter(record):
    """Adds the request_id context variable to the log record."""
    record["extra"]["request_id"] = request_id_var.get()
    return True

def setup_logger():
    """
    Configures structured logging for production.
    Never logs full document text.
    """
    logger.remove()
    
    # Standard output structured JSON format for production environments
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "[<magenta>{extra[request_id]}</magenta>] "
        "- <level>{message}</level>"
    )
    
    logger.add(
        sys.stdout, 
        format=log_format, 
        level=settings.LOGGING_LEVEL,
        filter=_correlation_id_filter,
        enqueue=True, # Thread-safe
        serialize=False # Set to True in actual prod container if JSON logs are preferred by log aggregator
    )
    
    logger.info(f"Logger initialized at level {settings.LOGGING_LEVEL}")

setup_logger()
