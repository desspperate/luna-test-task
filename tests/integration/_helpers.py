"""Shared test helpers for integration tests.

Keep this thin — only fixtures/helpers reused across multiple test modules belong
here; per-module helpers stay private to that module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    import httpx2


def payment_payload(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    """Default payload for POST /api/v1/payments.

    All overrides accepted as kwargs (also lets you remove keys by passing
    `None` — they'll still appear; remove afterwards if needed).
    """
    base: dict[str, Any] = {
        "amount": "100.00",
        "currency": "RUB",
        "description": "Integration test payment",
        "meta": {"source": "integration-tests"},
        "webhook_url": "https://example.com/wh",
    }
    base.update(overrides)
    return base


async def create_payment(
    api_client: httpx2.AsyncClient,
    *,
    key: str,
    webhook_url: str = "https://example.com/wh",
    amount: str = "100.00",
    currency: str = "RUB",
) -> UUID:
    """Create a payment via API and return its UUID. Asserts 202."""
    resp = await api_client.post(
        "/api/v1/payments",
        json=payment_payload(
            amount=amount,
            currency=currency,
            webhook_url=webhook_url,
        ),
        headers={"Idempotency-Key": key},
    )
    assert resp.status_code == 202, f"expected 202 from /payments, got {resp.status_code}: {resp.text}"
    return UUID(resp.json()["payment_id"])
