from collections.abc import AsyncIterable
from unittest.mock import AsyncMock, MagicMock

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations import fastapi as fastapi_integration
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.error_handlers import register_error_handler
from payments_processor.routers import api_health_router


class _SessionProvider(Provider):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    @provide(scope=Scope.REQUEST)
    async def get_session(self) -> AsyncIterable[AsyncSession]:
        yield self._session


def _make_client(session: AsyncSession) -> TestClient:
    container = make_async_container(_SessionProvider(session))
    app = FastAPI()
    app.include_router(api_health_router)
    register_error_handler(app)
    fastapi_integration.setup_dishka(container=container, app=app)
    return TestClient(app)


@pytest.fixture
def healthy_session() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=MagicMock())
    return session


@pytest.fixture
def broken_session() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        side_effect=OperationalError("ping", {}, BaseException("db down")),
    )
    return session


class TestHealth:
    def test_returns_200_with_ok_payload(self, healthy_session: MagicMock) -> None:
        resp = _make_client(healthy_session).get("/health")
        assert resp.status_code == 200
        assert resp.json() == "ok"

    def test_does_not_touch_database(self, healthy_session: MagicMock) -> None:
        _make_client(healthy_session).get("/health")
        healthy_session.execute.assert_not_called()


class TestReady:
    def test_db_healthy_returns_200(self, healthy_session: MagicMock) -> None:
        resp = _make_client(healthy_session).get("/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready", "checks": {"database": True}}

    def test_db_healthy_runs_select_1(self, healthy_session: MagicMock) -> None:
        _make_client(healthy_session).get("/ready")
        healthy_session.execute.assert_awaited_once()
        # The argument is a sqlalchemy TextClause — compare its string form
        executed = healthy_session.execute.await_args.args[0]
        assert str(executed) == "SELECT 1"

    def test_db_broken_returns_503(self, broken_session: MagicMock) -> None:
        resp = _make_client(broken_session).get("/ready")
        assert resp.status_code == 503

    def test_db_broken_response_shape(self, broken_session: MagicMock) -> None:
        resp = _make_client(broken_session).get("/ready")
        body = resp.json()
        assert body["status"] == "db_unhealthy"
        assert body["checks"] == {"database": False}
        assert body["error"] == "OperationalError"
