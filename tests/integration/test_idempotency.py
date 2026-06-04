import asyncio
from typing import Any
from uuid import UUID

import pytest
from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.models import Outbox, Payment

from ._helpers import payment_payload

pytestmark = pytest.mark.integration


class TestSameRequestReplay:
    async def test_second_call_returns_same_payment_id(self, api_client: AsyncClient) -> None:
        first = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": "replay-1"},
        )
        second = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": "replay-1"},
        )
        assert first.json()["payment_id"] == second.json()["payment_id"]

    async def test_replay_does_not_create_extra_payment_row(
        self,
        api_client: AsyncClient,
        pg_session: AsyncSession,
    ) -> None:
        for _ in range(3):
            await api_client.post(
                "/api/v1/payments",
                json=payment_payload(),
                headers={"Idempotency-Key": "replay-2"},
            )
        count = (await pg_session.execute(select(func.count(Payment.id)))).scalar_one()
        assert count == 1

    async def test_replay_does_not_create_extra_outbox_row(
        self,
        api_client: AsyncClient,
        pg_session: AsyncSession,
    ) -> None:
        for _ in range(3):
            await api_client.post(
                "/api/v1/payments",
                json=payment_payload(),
                headers={"Idempotency-Key": "replay-3"},
            )
        count = (await pg_session.execute(select(func.count(Outbox.id)))).scalar_one()
        assert count == 1


class TestConflictingPayload:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("amount", "999.99"),
            ("currency", "USD"),
            ("webhook_url", "https://other.example.com/wh"),
        ],
    )
    async def test_changed_field_yields_409(
        self,
        api_client: AsyncClient,
        field: str,
        value: str,
    ) -> None:
        key = f"conflict-{field}"
        first = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": key},
        )
        assert first.status_code == 202

        second = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(**{field: value}),
            headers={"Idempotency-Key": key},
        )
        assert second.status_code == 409
        assert second.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"

    async def test_conflict_response_does_not_leak_field_values(
        self,
        api_client: AsyncClient,
    ) -> None:
        await api_client.post(
            "/api/v1/payments",
            json=payment_payload(amount="100.00"),
            headers={"Idempotency-Key": "leak-test"},
        )
        resp = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(amount="999.99"),
            headers={"Idempotency-Key": "leak-test"},
        )
        text = resp.text
        assert "999.99" not in text
        assert "100.00" not in text


class TestConcurrentReplay:
    async def test_parallel_calls_create_one_payment(
        self,
        api_client: AsyncClient,
        pg_session: AsyncSession,
    ) -> None:
        async def post() -> dict[str, Any]:
            r = await api_client.post(
                "/api/v1/payments",
                json=payment_payload(),
                headers={"Idempotency-Key": "race-1"},
            )
            return {"status": r.status_code, "json": r.json()}

        results = await asyncio.gather(*(post() for _ in range(5)))
        accepted = [r for r in results if r["status"] == 202]

        # All 202 responses agree on the same payment_id
        ids = {r["json"]["payment_id"] for r in accepted}
        assert len(ids) == 1

        # Database has exactly one payment row
        count = (await pg_session.execute(select(func.count(Payment.id)))).scalar_one()
        assert count == 1

        # And one outbox row — no duplicate events under concurrency
        outbox_count = (await pg_session.execute(select(func.count(Outbox.id)))).scalar_one()
        assert outbox_count == 1

        # Sanity-check the surviving payment id is a UUID
        UUID(accepted[0]["json"]["payment_id"])
