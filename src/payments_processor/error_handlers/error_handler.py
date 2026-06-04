from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger

from payments_processor.errors import (
    PaymentsBusinessLogicError,
    PaymentsConflictError,
    PaymentsError,
    PaymentsExternalServiceError,
    PaymentsForbiddenError,
    PaymentsNotFoundError,
    PaymentsUnauthorizedError,
    PaymentsUnexpectedError,
    PaymentsValidationError,
)


def register_error_handler(app: FastAPI) -> None:
    async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, RequestValidationError):
            return await handle_all_errors(request=request, exc=exc)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "code": "VALIDATION_ERROR",
                "message": "Validation failed",
                "details": jsonable_encoder(exc.errors()),
            },
        )

    async def handle_all_errors(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, PaymentsError):
            logger.bind(
                method=request.method,
                path=request.url.path,
                error_type=exc.__class__.__name__,
            ).exception(f"Unhandled Application Error: {exc}")

            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "code": PaymentsUnexpectedError.code,
                    "message": PaymentsUnexpectedError.message,
                },
            )

        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        if isinstance(exc, PaymentsNotFoundError):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, PaymentsUnauthorizedError):
            status_code = status.HTTP_401_UNAUTHORIZED
        elif isinstance(exc, PaymentsForbiddenError):
            status_code = status.HTTP_403_FORBIDDEN
        elif isinstance(exc, PaymentsConflictError):
            status_code = status.HTTP_409_CONFLICT
        elif isinstance(exc, (PaymentsValidationError, PaymentsBusinessLogicError)):
            status_code = status.HTTP_400_BAD_REQUEST
        elif isinstance(exc, PaymentsExternalServiceError):
            status_code = status.HTTP_502_BAD_GATEWAY

        logger.bind(
            method=request.method,
            path=request.url.path,
            error_code=exc.code,
        ).info(f"Business Rule Violation [{exc.code}]: {exc.message} | Details: {exc.details}")

        content: dict[str, Any] = {
            "code": exc.code,
            "message": exc.message,
        }
        if exc.details is not None:
            content["details"] = exc.details

        return JSONResponse(
            status_code=status_code,
            content=content,
        )

    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, handle_all_errors)
