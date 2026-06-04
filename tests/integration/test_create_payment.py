from datetime import UTC, datetime
from uuid import UUID

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.enums import OutboxStatusEnum, PaymentStatusEnum
from payments_processor.models import Outbox, Payment
from payments_processor.utils import SSRFGuard

from ._helpers import payment_payload

pytestmark = pytest.mark.integration


class TestSuccessfulCreate:
    async def test_returns_202_accepted(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": "create-1"},
        )
        assert resp.status_code == 202

    async def test_response_contains_required_fields(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": "create-2"},
        )
        body = resp.json()
        assert set(body.keys()) >= {"payment_id", "status", "created_at"}

    async def test_response_payment_id_is_uuid_v7(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": "create-3"},
        )
        payment_id = UUID(resp.json()["payment_id"])
        assert payment_id.version == 7

    async def test_response_status_starts_pending(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": "create-4"},
        )
        assert resp.json()["status"] == "PENDING"

    async def test_response_created_at_is_recent_iso8601(self, api_client: httpx2.AsyncClient) -> None:
        before = datetime.now(tz=UTC)
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": "create-5"},
        )
        after = datetime.now(tz=UTC)
        created_at = datetime.fromisoformat(resp.json()["created_at"])
        assert before <= created_at <= after


class TestPersistence:
    async def test_payment_row_persisted_with_pending_status(
        self,
        api_client: httpx2.AsyncClient,
        pg_session: AsyncSession,
    ) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(amount="250.55", currency="EUR"),
            headers={"Idempotency-Key": "persist-1"},
        )
        payment_id = UUID(resp.json()["payment_id"])
        row = (await pg_session.execute(select(Payment).where(Payment.id == payment_id))).scalar_one()

        assert row.status == PaymentStatusEnum.PENDING
        assert row.idempotency_key == "persist-1"
        assert str(row.amount) == "250.5500"
        assert row.currency.value == "EUR"
        assert row.webhook_url == "https://example.com/wh"
        assert row.processed_at is None

    async def test_outbox_event_created_with_correct_routing(
        self,
        api_client: httpx2.AsyncClient,
        pg_session: AsyncSession,
    ) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": "persist-2"},
        )
        payment_id = UUID(resp.json()["payment_id"])
        outbox = (
            await pg_session.execute(
                select(Outbox).where(Outbox.aggregate_id == payment_id),
            )
        ).scalar_one()

        assert outbox.status == OutboxStatusEnum.PENDING
        assert outbox.aggregate_type == "payment"
        assert outbox.event_type == "payment.created"
        assert outbox.routing_key == "payment.created"
        assert outbox.payload == {"payment_id": str(payment_id)}
        assert outbox.attempts == 0
        assert outbox.published_at is None


class TestBodyValidation:
    async def test_missing_idempotency_key_returns_422(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.post("/api/v1/payments", json=payment_payload())
        assert resp.status_code == 422

    async def test_empty_idempotency_key_returns_422(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": ""},
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("bad_amount", ["0", "-10", "0.0000"])
    async def test_non_positive_amount_returns_422(
        self,
        api_client: httpx2.AsyncClient,
        bad_amount: str,
    ) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(amount=bad_amount),
            headers={"Idempotency-Key": f"amt-{bad_amount}"},
        )
        assert resp.status_code == 422

    async def test_float_amount_rejected_to_prevent_precision_loss(
        self,
        api_client: httpx2.AsyncClient,
    ) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json={**payment_payload(), "amount": 10.50},
            headers={"Idempotency-Key": "amt-float"},
        )
        assert resp.status_code == 422

    async def test_unsupported_currency_returns_422(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(currency="JPY"),
            headers={"Idempotency-Key": "cur-jpy"},
        )
        assert resp.status_code == 422

    async def test_malformed_webhook_url_returns_422(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(webhook_url="not-a-url"),
            headers={"Idempotency-Key": "url-bad"},
        )
        assert resp.status_code == 422


class TestSSRFProtection:
    async def test_private_webhook_blocked_when_guard_strict(
        self,
        api_app: FastAPI,
        api_client: httpx2.AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        container = api_app.state.container
        guard = await container.get(SSRFGuard)
        monkeypatch.setattr(guard, "allow_private_hosts", False)

        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(webhook_url="https://127.0.0.1/x"),
            headers={"Idempotency-Key": "ssrf-1"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "WEBHOOK_URL_NOT_ALLOWED"

    async def test_ssrf_rejected_request_does_not_persist_payment(
        self,
        api_app: FastAPI,
        api_client: httpx2.AsyncClient,
        pg_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        container = api_app.state.container
        guard = await container.get(SSRFGuard)
        monkeypatch.setattr(guard, "allow_private_hosts", False)

        await api_client.post(
            "/api/v1/payments",
            json=payment_payload(webhook_url="https://127.0.0.1/x"),
            headers={"Idempotency-Key": "ssrf-2"},
        )

        rows = (await pg_session.execute(select(Payment))).scalars().all()
        assert rows == []
