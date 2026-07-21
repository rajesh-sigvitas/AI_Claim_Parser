from fastapi import HTTPException, status

class ParserBaseException(Exception):
    """Base exception for parser errors."""
    pass

class InvalidXMLError(ParserBaseException):
    """Raised when XML is malformed or missing claims."""
    pass

class MissingClaimsError(ParserBaseException):
    """Raised when no claims can be detected in the document."""
    pass

class UnsupportedFileTypeError(ParserBaseException):
    """Raised when the uploaded file type is not supported."""
    pass

class OCRFailureError(ParserBaseException):
    """Raised when OCR extraction fails."""
    pass

class CorruptedPDFError(ParserBaseException):
    """Raised when a PDF file is unreadable."""
    pass

class EmptyDocumentError(ParserBaseException):
    """Raised when the extracted text is empty."""
    pass

class MalformedHierarchyError(ParserBaseException):
    """Raised when the claim hierarchy is structurally invalid."""
    pass

class FileSizeLimitExceededError(ParserBaseException):
    """Raised when the file size exceeds the maximum limit."""
    pass

def setup_exception_handlers(app):
    from fastapi import Request
    from fastapi.responses import JSONResponse
    import traceback
    
    @app.exception_handler(ParserBaseException)
    async def parser_exception_handler(request: Request, exc: ParserBaseException):
        # We can map specific exceptions to status codes if needed. Default to 400.
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, UnsupportedFileTypeError):
            status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        elif isinstance(exc, FileSizeLimitExceededError):
            status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        
        return JSONResponse(
            status_code=status_code,
            content={
                "error": exc.__class__.__name__,
                "message": str(exc),
                "status": "error"
            }
        )
