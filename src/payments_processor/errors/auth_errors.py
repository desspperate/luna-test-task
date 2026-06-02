from .payments_errors import PaymentsUnauthorizedError


class AuthError(Exception):
    pass


class MissingAPIKeyError(AuthError, PaymentsUnauthorizedError):
    def __init__(self) -> None:
        super().__init__(
            code="API_KEY_MISSING",
            message="X-API-Key header is required",
        )


class InvalidAPIKeyError(AuthError, PaymentsUnauthorizedError):
    def __init__(self) -> None:
        super().__init__(
            code="API_KEY_INVALID",
            message="Provided X-API-Key is invalid",
        )
