from collections.abc import Callable
from datetime import UTC, datetime


class HealthState:
    def __init__(self, stale_after_seconds: float | None = None) -> None:
        self.stale_after_seconds = stale_after_seconds
        self.started = False
        self.last_heartbeat: datetime | None = None
        self.liveness_check: Callable[[], bool] | None = None

    def mark_started(self) -> None:
        now = datetime.now(tz=UTC)
        self.started = True
        self.last_heartbeat = now

    def heartbeat(self) -> None:
        self.last_heartbeat = datetime.now(tz=UTC)

    def set_liveness_check(self, check: Callable[[], bool]) -> None:
        self.liveness_check = check

    def is_healthy(self) -> bool:
        if not self.started:
            return False

        if self.stale_after_seconds is not None:
            if self.last_heartbeat is None:
                return False
            elapsed = (datetime.now(tz=UTC) - self.last_heartbeat).total_seconds()
            if elapsed >= self.stale_after_seconds:
                return False

        return not (self.liveness_check is not None and not self.liveness_check())
