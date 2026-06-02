from typing import Any
from uuid import UUID

from .payments_errors import PaymentsExternalServiceError


class WebhookError(Exception):
    pass


class WebhookSendError(WebhookError, PaymentsExternalServiceError):
    def __init__(
            self,
            payment_id: UUID | str,
            reason: str,
            status_code: int | None = None,
    ) -> None:
        self.payment_id = payment_id
        self.reason = reason
        self.status_code = status_code
        details: dict[str, Any] = {
            "payment_id": str(payment_id),
            "reason": reason,
        }
        if status_code is not None:
            details["status_code"] = status_code
        super().__init__(
            code="WEBHOOK_SEND_FAILED",
            message="Failed to deliver webhook",
            details=details,
        )
