import hashlib
import hmac
import json
import os
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from payments_processor.constants import PaymentsConstants
from payments_processor.enums import PaymentStatusEnum
from payments_processor.models import Payment
from payments_processor.schemas import PaymentCreatedEvent

from ._helpers import create_payment

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeMessage:
    """Stand-in for `faststream.rabbit.RabbitMessage` exposing only the surface
    that `_handle_payment_created` touches."""

    def __init__(self, headers: dict[str, Any] | None = None) -> None:
        self.headers = headers or {}
        self.acked = False
        self.rejected_requeue: bool | None = None
        self.nacked_requeue: bool | None = None

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, requeue: bool = True) -> None:
        self.rejected_requeue = requeue

    async def nack(self, requeue: bool = True) -> None:
        self.nacked_requeue = requeue


def _make_publisher() -> AsyncMock:
    from payments_processor.messaging import PaymentEventPublisher

    return AsyncMock(spec=PaymentEventPublisher)


async def _run_handler(
    *,
    api_app,
    payment_id: UUID,
    publisher: AsyncMock,
    msg: FakeMessage,
    max_retries: int = 3,
) -> None:
    from payments_processor.consumer.main import _handle_payment_created

    await _handle_payment_created(
        event=PaymentCreatedEvent(payment_id=payment_id),
        msg=msg,
        container=api_app.state.container,
        publisher=publisher,
        max_retries=max_retries,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_acks_message(
        self, api_app, api_client, webhook_receiver,
    ) -> None:
        payment_id = await create_payment(
            api_client, key="happy-1", webhook_url=webhook_receiver.url,
        )
        publisher = _make_publisher()
        msg = FakeMessage()

        await _run_handler(
            api_app=api_app, payment_id=payment_id, publisher=publisher, msg=msg,
        )
        assert msg.acked is True

    async def test_updates_payment_to_processed_status(
        self, api_app, api_client, webhook_receiver, pg_session,
    ) -> None:
        payment_id = await create_payment(
            api_client, key="happy-2", webhook_url=webhook_receiver.url,
        )
        await _run_handler(
            api_app=api_app,
            payment_id=payment_id,
            publisher=_make_publisher(),
            msg=FakeMessage(),
        )

        payment = (
            await pg_session.execute(select(Payment).where(Payment.id == payment_id))
        ).scalar_one()
        # CONSUMER_SUCCESS_PROBABILITY=1.0 in test env, so always SUCCEEDED
        assert payment.status == PaymentStatusEnum.SUCCEEDED
        assert payment.processed_at is not None

    async def test_sends_webhook_with_correct_event_type_header(
        self, api_app, api_client, webhook_receiver,
    ) -> None:
        payment_id = await create_payment(
            api_client, key="happy-3", webhook_url=webhook_receiver.url,
        )
        await _run_handler(
            api_app=api_app,
            payment_id=payment_id,
            publisher=_make_publisher(),
            msg=FakeMessage(),
        )

        assert len(webhook_receiver.requests) == 1
        delivered = webhook_receiver.requests[0]
        assert delivered["headers"][PaymentsConstants.WEBHOOK_EVENT_TYPE_HEADER] == \
            PaymentsConstants.PAYMENT_PROCESSED_EVENT_TYPE

    async def test_webhook_body_contains_payment_id_and_final_status(
        self, api_app, api_client, webhook_receiver,
    ) -> None:
        payment_id = await create_payment(
            api_client, key="happy-4", webhook_url=webhook_receiver.url,
        )
        await _run_handler(
            api_app=api_app,
            payment_id=payment_id,
            publisher=_make_publisher(),
            msg=FakeMessage(),
        )

        body = json.loads(webhook_receiver.requests[0]["body"])
        assert body["payment_id"] == str(payment_id)
        assert body["status"] == "SUCCEEDED"

    async def test_webhook_signature_validates_with_configured_secret(
        self, api_app, api_client, webhook_receiver,
    ) -> None:
        payment_id = await create_payment(
            api_client, key="happy-5", webhook_url=webhook_receiver.url,
        )
        await _run_handler(
            api_app=api_app,
            payment_id=payment_id,
            publisher=_make_publisher(),
            msg=FakeMessage(),
        )

        delivered = webhook_receiver.requests[0]
        ts = delivered["headers"][PaymentsConstants.WEBHOOK_TIMESTAMP_HEADER]
        sig = delivered["headers"][PaymentsConstants.WEBHOOK_SIGNATURE_HEADER]
        secret = os.environ["WEBHOOK_SECRET"]
        expected = hmac.new(
            key=secret.encode(),
            msg=f"{ts}.".encode() + delivered["body"],
            digestmod=hashlib.sha256,
        ).hexdigest()
        assert sig.removeprefix("sha256=") == expected

    async def test_does_not_publish_to_retry_or_dlq_on_success(
        self, api_app, api_client, webhook_receiver,
    ) -> None:
        payment_id = await create_payment(
            api_client, key="happy-6", webhook_url=webhook_receiver.url,
        )
        publisher = _make_publisher()
        await _run_handler(
            api_app=api_app, payment_id=payment_id, publisher=publisher, msg=FakeMessage(),
        )
        publisher.publish_to_queue.assert_not_awaited()
        publisher.publish_to_dlx.assert_not_awaited()


# ---------------------------------------------------------------------------
# Idempotency (consumer side)
# ---------------------------------------------------------------------------


class TestConsumerIdempotency:
    """Re-delivery of a payment event must not re-run the emulation, but should
    re-attempt the webhook (so a failed delivery can recover)."""

    async def test_processed_at_unchanged_on_second_delivery(
        self, api_app, api_client, webhook_receiver, pg_session,
    ) -> None:
        payment_id = await create_payment(
            api_client, key="idempo-1", webhook_url=webhook_receiver.url,
        )
        await _run_handler(
            api_app=api_app,
            payment_id=payment_id,
            publisher=_make_publisher(),
            msg=FakeMessage(),
        )
        first = (
            await pg_session.execute(select(Payment).where(Payment.id == payment_id))
        ).scalar_one()

        await _run_handler(
            api_app=api_app,
            payment_id=payment_id,
            publisher=_make_publisher(),
            msg=FakeMessage(),
        )
        pg_session.expire_all()
        second = (
            await pg_session.execute(select(Payment).where(Payment.id == payment_id))
        ).scalar_one()

        assert second.processed_at == first.processed_at
        assert second.status == first.status

    async def test_webhook_resent_on_each_delivery(
        self, api_app, api_client, webhook_receiver,
    ) -> None:
        payment_id = await create_payment(
            api_client, key="idempo-2", webhook_url=webhook_receiver.url,
        )
        for _ in range(2):
            await _run_handler(
                api_app=api_app,
                payment_id=payment_id,
                publisher=_make_publisher(),
                msg=FakeMessage(),
            )
        assert len(webhook_receiver.requests) == 2


# ---------------------------------------------------------------------------
# Retry / DLQ
# ---------------------------------------------------------------------------


class TestRetryAndDLQ:
    async def test_first_failure_schedules_first_retry(
        self, api_app, api_client, webhook_receiver,
    ) -> None:
        webhook_receiver.set_status(500)
        payment_id = await create_payment(
            api_client, key="retry-1", webhook_url=webhook_receiver.url,
        )
        publisher = _make_publisher()
        msg = FakeMessage()  # no retry count yet

        await _run_handler(
            api_app=api_app, payment_id=payment_id, publisher=publisher, msg=msg,
        )

        publisher.publish_to_queue.assert_awaited_once()
        kwargs = publisher.publish_to_queue.await_args.kwargs
        assert kwargs["queue"] == f"{PaymentsConstants.QUEUE_PAYMENTS_RETRY_PREFIX}1"
        assert kwargs["headers"][PaymentsConstants.RETRY_COUNT_HEADER] == 1
        assert kwargs["headers"][PaymentsConstants.RETRY_REASON_HEADER] == "non_2xx_response"
        assert kwargs["payload"] == {"payment_id": str(payment_id)}
        assert msg.acked is True
        publisher.publish_to_dlx.assert_not_awaited()

    async def test_subsequent_failure_uses_next_retry_queue(
        self, api_app, api_client, webhook_receiver,
    ) -> None:
        webhook_receiver.set_status(500)
        payment_id = await create_payment(
            api_client, key="retry-2", webhook_url=webhook_receiver.url,
        )
        publisher = _make_publisher()
        msg = FakeMessage(headers={PaymentsConstants.RETRY_COUNT_HEADER: 1})

        await _run_handler(
            api_app=api_app, payment_id=payment_id, publisher=publisher, msg=msg,
        )
        kwargs = publisher.publish_to_queue.await_args.kwargs
        assert kwargs["queue"] == f"{PaymentsConstants.QUEUE_PAYMENTS_RETRY_PREFIX}2"
        assert kwargs["headers"][PaymentsConstants.RETRY_COUNT_HEADER] == 2

    async def test_exhausted_retries_route_to_dlq(
        self, api_app, api_client, webhook_receiver,
    ) -> None:
        webhook_receiver.set_status(500)
        payment_id = await create_payment(
            api_client, key="dlq-1", webhook_url=webhook_receiver.url,
        )
        publisher = _make_publisher()
        msg = FakeMessage(headers={PaymentsConstants.RETRY_COUNT_HEADER: 3})

        await _run_handler(
            api_app=api_app,
            payment_id=payment_id,
            publisher=publisher,
            msg=msg,
            max_retries=3,
        )

        publisher.publish_to_dlx.assert_awaited_once()
        kwargs = publisher.publish_to_dlx.await_args.kwargs
        assert kwargs["routing_key"] == PaymentsConstants.PAYMENT_FAILED_ROUTING_KEY
        assert kwargs["payload"] == {"payment_id": str(payment_id)}
        assert kwargs["headers"][PaymentsConstants.DLQ_REASON_HEADER] == "non_2xx_response"

        publisher.publish_to_queue.assert_not_awaited()
        assert msg.acked is True


# ---------------------------------------------------------------------------
# Safety net
# ---------------------------------------------------------------------------


class TestSafetyNet:
    async def test_unknown_payment_id_rejected_without_requeue(
        self, api_app,
    ) -> None:
        """A message referencing a payment that no longer exists must NOT be
        retried. It goes to the DLQ via reject(requeue=False)."""
        publisher = _make_publisher()
        msg = FakeMessage()

        await _run_handler(
            api_app=api_app, payment_id=uuid4(), publisher=publisher, msg=msg,
        )

        assert msg.acked is False
        assert msg.rejected_requeue is False
        publisher.publish_to_queue.assert_not_awaited()
        publisher.publish_to_dlx.assert_not_awaited()
