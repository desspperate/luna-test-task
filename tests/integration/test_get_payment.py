from uuid import UUID, uuid4

import httpx2
import pytest

from ._helpers import payment_payload

pytestmark = pytest.mark.integration


class TestGetExisting:
    async def test_returns_200_with_full_payload(self, api_client: httpx2.AsyncClient) -> None:
        created = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(amount="200.50", currency="USD"),
            headers={"Idempotency-Key": "get-1"},
        )
        payment_id = created.json()["payment_id"]

        resp = await api_client.get(f"/api/v1/payments/{payment_id}")
        assert resp.status_code == 200

        body = resp.json()
        assert body["id"] == payment_id
        assert body["amount"] == "200.5000"
        assert body["currency"] == "USD"
        assert body["status"] == "PENDING"
        assert body["idempotency_key"] == "get-1"
        assert body["webhook_url"].startswith("https://example.com/wh")
        assert body["processed_at"] is None
        assert body["created_at"]
        assert body["updated_at"] is None

    async def test_returned_id_round_trips_as_uuid(self, api_client: httpx2.AsyncClient) -> None:
        created = await api_client.post(
            "/api/v1/payments",
            json=payment_payload(),
            headers={"Idempotency-Key": "get-2"},
        )
        resp = await api_client.get(f"/api/v1/payments/{created.json()['payment_id']}")
        UUID(resp.json()["id"])  # raises if not a UUID


class TestNotFound:
    async def test_unknown_id_returns_404(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.get(f"/api/v1/payments/{uuid4()}")
        assert resp.status_code == 404

    async def test_404_uses_payment_not_found_code(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.get(f"/api/v1/payments/{uuid4()}")
        assert resp.json()["code"] == "PAYMENT_NOT_FOUND"


class TestPathValidation:
    async def test_invalid_uuid_returns_422(self, api_client: httpx2.AsyncClient) -> None:
        resp = await api_client.get("/api/v1/payments/not-a-uuid")
        assert resp.status_code == 422
