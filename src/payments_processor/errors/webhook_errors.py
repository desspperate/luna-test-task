from typing import Any
from uuid import UUID

from .payments_errors import PaymentsExternalServiceError, PaymentsValidationError


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


class WebhookUrlNotAllowedError(WebhookError, PaymentsValidationError):
    def __init__(
        self,
        url: str,
        reason: str,
        resolved_ip: str | None = None,
    ) -> None:
        self.url = url
        self.reason = reason
        self.resolved_ip = resolved_ip
        details: dict[str, Any] = {
            "url": url,
            "reason": reason,
        }
        if resolved_ip is not None:
            details["resolved_ip"] = resolved_ip
        super().__init__(
            code="WEBHOOK_URL_NOT_ALLOWED",
            message="Webhook URL is not allowed",
            details=details,
        )
