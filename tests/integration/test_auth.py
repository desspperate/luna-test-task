from uuid import uuid4

import httpx2
import pytest

pytestmark = pytest.mark.integration


class TestProtectedEndpoints:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/api/v1/payments"),
            ("GET", "/api/v1/payments/00000000-0000-0000-0000-000000000000"),
        ],
    )
    async def test_without_api_key_returns_401(
        self,
        api_client: httpx2.AsyncClient,
        method: str,
        path: str,
    ) -> None:
        api_client.headers.pop("X-API-Key", None)
        resp = await api_client.request(method, path, json={})
        assert resp.status_code == 401
        assert resp.json()["code"] == "API_KEY_MISSING"

    async def test_with_wrong_api_key_returns_401(self, api_client: httpx2.AsyncClient) -> None:
        api_client.headers["X-API-Key"] = "definitely-not-the-real-key"
        resp = await api_client.get(f"/api/v1/payments/{uuid4()}")
        assert resp.status_code == 401
        assert resp.json()["code"] == "API_KEY_INVALID"


class TestPublicEndpoints:
    @pytest.mark.parametrize("path", ["/health", "/ready", "/openapi.json"])
    async def test_path_accessible_without_api_key(
        self,
        api_client: httpx2.AsyncClient,
        path: str,
    ) -> None:
        api_client.headers.pop("X-API-Key", None)
        resp = await api_client.get(path)
        assert resp.status_code == 200
