import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from payments_processor.error_handlers import register_error_handler
from payments_processor.errors import (
    PaymentsBusinessLogicError,
    PaymentsConflictError,
    PaymentsExternalServiceError,
    PaymentsForbiddenError,
    PaymentsNotFoundError,
    PaymentsUnauthorizedError,
    PaymentsValidationError,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    register_error_handler(app)

    @app.get("/not-found")
    async def not_found() -> None:  # pyright: ignore[reportUnusedFunction]
        raise PaymentsNotFoundError(
            code="X_NOT_FOUND",
            message="x not found",
            details={"id": 1},
        )

    @app.get("/validation")
    async def validation() -> None:  # pyright: ignore[reportUnusedFunction]
        raise PaymentsValidationError(code="X_INVALID", message="invalid")

    @app.get("/business")
    async def business() -> None:  # pyright: ignore[reportUnusedFunction]
        raise PaymentsBusinessLogicError(code="X_RULE", message="rule violated")

    @app.get("/conflict")
    async def conflict() -> None:  # pyright: ignore[reportUnusedFunction]
        raise PaymentsConflictError(
            code="X_CONFLICT",
            message="conflict",
            details={"key": "k"},
        )

    @app.get("/unauthorized")
    async def unauthorized() -> None:  # pyright: ignore[reportUnusedFunction]
        raise PaymentsUnauthorizedError(code="UNAUTHED", message="unauthorized")

    @app.get("/forbidden")
    async def forbidden() -> None:  # pyright: ignore[reportUnusedFunction]
        raise PaymentsForbiddenError(code="FORBID", message="forbidden")

    @app.get("/external")
    async def external() -> None:  # pyright: ignore[reportUnusedFunction]
        raise PaymentsExternalServiceError(code="EXT", message="upstream broken")

    @app.get("/unexpected")
    async def unexpected() -> None:  # pyright: ignore[reportUnusedFunction]
        msg = "boom secret_value=top-secret-token"
        raise RuntimeError(msg)

    class Body(BaseModel):
        n: int

    @app.post("/echo")
    async def echo(b: Body) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
        return {"n": b.n}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("path", "status_code"),
        [
            ("/not-found", 404),
            ("/validation", 400),
            ("/business", 400),
            ("/conflict", 409),
            ("/unauthorized", 401),
            ("/forbidden", 403),
            ("/external", 502),
        ],
    )
    def test_payments_error_subclass_maps_to_expected_status(
        self,
        client: TestClient,
        path: str,
        status_code: int,
    ) -> None:
        resp = client.get(path)
        assert resp.status_code == status_code


class TestResponseShape:
    def test_includes_code_message_and_details(self, client: TestClient) -> None:
        resp = client.get("/not-found")
        body = resp.json()
        assert body == {
            "code": "X_NOT_FOUND",
            "message": "x not found",
            "details": {"id": 1},
        }

    def test_omits_details_when_none(self, client: TestClient) -> None:
        resp = client.get("/validation")
        body = resp.json()
        assert "details" not in body
        assert body == {"code": "X_INVALID", "message": "invalid"}


class TestUnexpectedError:
    def test_returns_generic_500(self, client: TestClient) -> None:
        resp = client.get("/unexpected")
        assert resp.status_code == 500
        body = resp.json()
        assert body["code"] == "UNEXPECTED_ERROR"
        assert body["message"] == "Unexpected internal error"

    def test_does_not_leak_exception_message_or_traceback(
        self,
        client: TestClient,
    ) -> None:
        resp = client.get("/unexpected")
        text = resp.text
        assert "secret_value" not in text
        assert "top-secret-token" not in text
        assert "Traceback" not in text
        assert "RuntimeError" not in text


class TestRequestValidation:
    def test_pydantic_failure_returns_422_with_error_list(
        self,
        client: TestClient,
    ) -> None:
        resp = client.post("/echo", json={"n": "not-an-int"})
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert body["message"] == "Validation failed"
        assert isinstance(body["details"], list)
        assert len(body["details"]) >= 1
        first = body["details"][0]
        assert "loc" in first
        assert "type" in first

    def test_missing_body_returns_422(self, client: TestClient) -> None:
        resp = client.post("/echo")
        assert resp.status_code == 422
