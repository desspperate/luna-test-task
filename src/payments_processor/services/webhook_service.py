from datetime import UTC, datetime
from uuid import UUID

import httpx
from loguru import logger

from payments_processor.configs import WebhookConfig
from payments_processor.constants import PaymentsConstants
from payments_processor.errors import WebhookSendError
from payments_processor.models import Payment
from payments_processor.schemas import WebhookPayload
from payments_processor.utils import SSRFGuard, sign_webhook, uuid7


class WebhookService:
    def __init__(
            self,
            http_client: httpx.AsyncClient,
            webhook_config: WebhookConfig,
            ssrf_guard: SSRFGuard,
    ) -> None:
        self.http_client = http_client
        self.webhook_config = webhook_config
        self.ssrf_guard = ssrf_guard

    async def send(self, payment: Payment) -> None:
        await self.ssrf_guard.validate_url(url=payment.webhook_url)

        event_id = uuid7()
        body = self._build_body(payment=payment, event_id=event_id)
        ts = int(datetime.now(tz=UTC).timestamp())
        signature = sign_webhook(
            body=body,
            secret=self.webhook_config.WEBHOOK_SECRET,
            ts=ts,
        )

        headers = {
            "Content-Type": "application/json",
            "User-Agent": PaymentsConstants.WEBHOOK_USER_AGENT,
            PaymentsConstants.WEBHOOK_SIGNATURE_HEADER:
                f"{PaymentsConstants.WEBHOOK_SIGNATURE_PREFIX}{signature}",
            PaymentsConstants.WEBHOOK_TIMESTAMP_HEADER: str(ts),
            PaymentsConstants.WEBHOOK_ID_HEADER: str(event_id),
            PaymentsConstants.WEBHOOK_EVENT_TYPE_HEADER: PaymentsConstants.PAYMENT_PROCESSED_EVENT_TYPE,
        }

        logger.info(f"Sending webhook event_id={event_id} payment_id={payment.id} url={payment.webhook_url}")
        try:
            response = await self.http_client.post(
                payment.webhook_url,
                content=body,
                headers=headers,
                timeout=self.webhook_config.WEBHOOK_TIMEOUT_SECONDS,
            )
        except httpx.RequestError as e:
            raise WebhookSendError(payment_id=payment.id, reason=type(e).__name__) from e

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise WebhookSendError(
                payment_id=payment.id,
                reason="non_2xx_response",
                status_code=response.status_code,
            )
        logger.info(f"Webhook delivered event_id={event_id} status={response.status_code}")

    @staticmethod
    def _build_body(payment: Payment, event_id: UUID) -> bytes:
        payload = WebhookPayload(
            event_id=event_id,
            payment_id=payment.id,
            status=payment.status,
            amount=payment.amount,
            currency=payment.currency,
            processed_at=payment.processed_at,
            metadata=payment.meta,
        )
        return payload.model_dump_json().encode()
