from typing import Any


class PaymentsError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


class PaymentsUnexpectedError(PaymentsError):
    code: str = "UNEXPECTED_ERROR"
    message: str = "Unexpected internal error"

    def __init__(
        self,
        code: str = "UNEXPECTED_ERROR",
        message: str = "Unexpected internal error",
    ) -> None:
        self.code = code
        self.message = message
        super().__init__(
            code=code,
            message=message,
        )


class PaymentsConflictError(PaymentsError):
    pass


class PaymentsNotFoundError(PaymentsError):
    pass


class PaymentsValidationError(PaymentsError):
    pass


class PaymentsUnauthorizedError(PaymentsError):
    pass


class PaymentsForbiddenError(PaymentsError):
    pass


class PaymentsBusinessLogicError(PaymentsError):
    pass


class PaymentsExternalServiceError(PaymentsError):
    pass
