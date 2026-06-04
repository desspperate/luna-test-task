import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from payments_processor.constants import PaymentsConstants
from payments_processor.error_handlers import register_error_handler
from payments_processor.middlewares import register_api_key_middleware

API_KEY = "test-key-must-be-32-chars-long!!"


def _make_app() -> FastAPI:
    app = FastAPI()
    register_api_key_middleware(app=app, api_key=SecretStr(API_KEY))
    register_error_handler(app)

    @app.get("/protected")
    async def protected() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"ok": "yes"}

    @app.get("/health")
    async def health() -> str:  # pyright: ignore[reportUnusedFunction]
        return "ok"

    @app.get("/ready")
    async def ready() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ready"}

    @app.get("/docs")
    async def docs() -> str:  # pyright: ignore[reportUnusedFunction]
        return "docs"

    @app.get("/openapi.json")
    async def openapi() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"openapi": "3.1"}

    @app.get("/redoc")
    async def redoc() -> str:  # pyright: ignore[reportUnusedFunction]
        return "redoc"

    @app.get("/docs/oauth2-redirect")
    async def oauth_redirect() -> str:  # pyright: ignore[reportUnusedFunction]
        return "oauth"

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


class TestMissingKey:
    def test_returns_401(self, client: TestClient) -> None:
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_response_uses_documented_error_code(self, client: TestClient) -> None:
        resp = client.get("/protected")
        body = resp.json()
        assert body["code"] == "API_KEY_MISSING"

    def test_response_does_not_leak_internals(self, client: TestClient) -> None:
        resp = client.get("/protected")
        text = resp.text
        assert "Traceback" not in text
        assert API_KEY not in text


class TestInvalidKey:
    def test_returns_401(self, client: TestClient) -> None:
        resp = client.get(
            "/protected",
            headers={PaymentsConstants.API_KEY_HEADER: "wrong"},
        )
        assert resp.status_code == 401

    def test_response_uses_documented_error_code(self, client: TestClient) -> None:
        resp = client.get(
            "/protected",
            headers={PaymentsConstants.API_KEY_HEADER: "wrong"},
        )
        assert resp.json()["code"] == "API_KEY_INVALID"

    def test_response_does_not_echo_back_provided_or_expected(
        self,
        client: TestClient,
    ) -> None:
        resp = client.get(
            "/protected",
            headers={PaymentsConstants.API_KEY_HEADER: "wrong-attempt"},
        )
        assert "wrong-attempt" not in resp.text
        assert API_KEY not in resp.text

    def test_same_length_but_wrong_value_still_rejected(self, client: TestClient) -> None:
        same_length_wrong = "X" * len(API_KEY)
        resp = client.get(
            "/protected",
            headers={PaymentsConstants.API_KEY_HEADER: same_length_wrong},
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == "API_KEY_INVALID"


class TestValidKey:
    def test_passes_through_to_route(self, client: TestClient) -> None:
        resp = client.get("/protected", headers={"X-API-Key": API_KEY})
        assert resp.status_code == 200
        assert resp.json() == {"ok": "yes"}


class TestBypassPaths:
    @pytest.mark.parametrize(
        "path",
        [
            "/health",
            "/ready",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/docs/oauth2-redirect",
        ],
    )
    def test_listed_paths_skip_authentication(
        self,
        client: TestClient,
        path: str,
    ) -> None:
        resp = client.get(path)
        assert resp.status_code == 200

    def test_unrelated_get_still_requires_key(self, client: TestClient) -> None:
        """Make sure the bypass list is exact-match, not prefix-match."""
        resp = client.get("/healthx")  # not registered, but the middleware runs first
        # Either 404 (route miss) after auth passes, or 401 (auth blocks).
        # The middleware must NOT bypass /healthx — so it should reach 401.
        assert resp.status_code == 401
