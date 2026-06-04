from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from freezegun import freeze_time

from payments_processor.routers import worker_health_router
from payments_processor.utils import HealthState


def _make_client(health: HealthState) -> TestClient:
    app = FastAPI()
    app.include_router(worker_health_router)
    app.state.health = health
    return TestClient(app)


class TestNotStarted:
    def test_returns_503(self) -> None:
        resp = _make_client(HealthState()).get("/health")
        assert resp.status_code == 503

    def test_response_indicates_stale_and_not_started(self) -> None:
        resp = _make_client(HealthState()).get("/health")
        body = resp.json()
        assert body == {"status": "stale", "started": False}


class TestStartedAndHealthy:
    def test_returns_200_with_last_heartbeat(self) -> None:
        with freeze_time("2026-01-01T12:00:00Z"):
            state = HealthState()
            state.mark_started()
            resp = _make_client(state).get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["started"] is True
        parsed_ts = datetime.fromisoformat(body["last_heartbeat"])
        assert parsed_ts == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class TestStaleness:
    def test_returns_503_when_window_exceeded(self) -> None:
        with freeze_time("2026-01-01T00:00:00Z") as frozen:
            state = HealthState(stale_after_seconds=1)
            state.mark_started()
            frozen.tick(2)
            resp = _make_client(state).get("/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "stale"
        assert body["started"] is True
        assert "last_heartbeat" in body


class TestLivenessProbe:
    def test_liveness_check_failure_yields_503(self) -> None:
        state = HealthState()
        state.mark_started()
        state.set_liveness_check(lambda: False)
        resp = _make_client(state).get("/health")
        assert resp.status_code == 503
