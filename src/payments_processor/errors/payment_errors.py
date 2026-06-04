from uuid import UUID

from .payments_errors import PaymentsConflictError, PaymentsNotFoundError


class PaymentError(Exception):
    pass


class PaymentNotFoundError(PaymentError, PaymentsNotFoundError):
    def __init__(self, payment_id: UUID | str) -> None:
        self.payment_id = payment_id
        super().__init__(
            code="PAYMENT_NOT_FOUND",
            message="Payment not found",
        )


class IdempotencyKeyConflictError(PaymentError, PaymentsConflictError):
    def __init__(
        self,
        idempotency_key: str,
    ) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(
            code="IDEMPOTENCY_KEY_CONFLICT",
            message="Idempotency key was reused with a different request payload",
        )
