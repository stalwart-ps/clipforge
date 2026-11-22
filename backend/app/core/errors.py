from typing import Any
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base domain exception."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", status_code: int = 500, details: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class NotFoundError(AppError):
    def __init__(self, message: str, code: str = "NOT_FOUND"):
        super().__init__(message, code=code, status_code=status.HTTP_404_NOT_FOUND)


class ConflictError(AppError):
    def __init__(self, message: str, code: str = "CONFLICT"):
        super().__init__(message, code=code, status_code=status.HTTP_409_CONFLICT)


class ValidationError(AppError):
    def __init__(self, message: str, code: str = "VALIDATION_FAILED", details: Any = None):
        super().__init__(message, code=code, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, details=details)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"https://clipforge.local/errors/{exc.code.lower()}",
                "title": exc.code.replace("_", " ").title(),
                "status": exc.status_code,
                "detail": exc.message,
                "code": exc.code,
                "details": exc.details,
                "instance": str(request.url.path),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "https://clipforge.local/errors/validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": "Request validation failed",
                "code": "REQUEST_VALIDATION_ERROR",
                "details": exc.errors(),
                "instance": str(request.url.path),
            },
        )
