from datetime import UTC, datetime

from freezegun import freeze_time

from payments_processor.utils import HealthState


class TestInitialState:
    def test_fresh_instance_is_unhealthy(self) -> None:
        state = HealthState()
        assert state.started is False
        assert state.last_heartbeat is None
        assert state.is_healthy() is False


class TestMarkStarted:
    def test_records_current_time_as_heartbeat(self) -> None:
        with freeze_time("2026-01-01T12:00:00Z"):
            state = HealthState()
            state.mark_started()

        assert state.started is True
        assert state.last_heartbeat == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_makes_state_healthy_when_no_other_constraints(self) -> None:
        state = HealthState()
        state.mark_started()
        assert state.is_healthy() is True


class TestStaleness:
    def test_within_window_is_healthy(self) -> None:
        with freeze_time("2026-01-01T00:00:00Z") as frozen:
            state = HealthState(stale_after_seconds=10)
            state.mark_started()
            frozen.tick(9)
            assert state.is_healthy() is True

    def test_at_or_past_window_is_unhealthy(self) -> None:
        with freeze_time("2026-01-01T00:00:00Z") as frozen:
            state = HealthState(stale_after_seconds=10)
            state.mark_started()
            frozen.tick(10)
            assert state.is_healthy() is False

    def test_heartbeat_extends_window(self) -> None:
        with freeze_time("2026-01-01T00:00:00Z") as frozen:
            state = HealthState(stale_after_seconds=10)
            state.mark_started()
            frozen.tick(11)
            assert state.is_healthy() is False

            state.heartbeat()
            assert state.last_heartbeat == datetime(2026, 1, 1, 0, 0, 11, tzinfo=UTC)
            assert state.is_healthy() is True

    def test_started_without_stale_window_never_becomes_stale(self) -> None:
        with freeze_time("2026-01-01T00:00:00Z") as frozen:
            state = HealthState(stale_after_seconds=None)
            state.mark_started()
            frozen.tick(60 * 60 * 24)
            assert state.is_healthy() is True


class TestLivenessCheck:
    def test_failing_check_overrides_healthy_state(self) -> None:
        state = HealthState()
        state.mark_started()
        state.set_liveness_check(lambda: False)
        assert state.is_healthy() is False

    def test_passing_check_allows_healthy_state(self) -> None:
        state = HealthState()
        state.mark_started()
        state.set_liveness_check(lambda: True)
        assert state.is_healthy() is True

    def test_check_not_called_before_started(self) -> None:
        calls: list[None] = []

        def tracker() -> bool:
            calls.append(None)
            return True

        state = HealthState()
        state.set_liveness_check(tracker)
        assert state.is_healthy() is False
        assert calls == []

    def test_staleness_takes_precedence_over_passing_liveness(self) -> None:
        with freeze_time("2026-01-01T00:00:00Z") as frozen:
            state = HealthState(stale_after_seconds=5)
            state.mark_started()
            state.set_liveness_check(lambda: True)
            frozen.tick(10)
            assert state.is_healthy() is False
