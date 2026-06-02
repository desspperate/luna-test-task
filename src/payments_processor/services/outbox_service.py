from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from loguru import logger

from payments_processor.configs import OutboxDispatcherConfig
from payments_processor.models import Outbox
from payments_processor.repositories import OutboxRepository


class OutboxService:
    def __init__(
            self,
            outbox_repository: OutboxRepository,
            outbox_dispatcher_config: OutboxDispatcherConfig,
    ) -> None:
        self.outbox_repository = outbox_repository
        self.outbox_dispatcher_config = outbox_dispatcher_config

    async def fetch_pending(self, batch_size: int) -> Sequence[Outbox]:
        now = datetime.now(tz=UTC)
        rows = await self.outbox_repository.fetch_pending(batch_size=batch_size, now=now)
        if rows:
            logger.debug(f"Locked {len(rows)} pending outbox rows")
        return rows

    async def mark_published(self, outbox_id: UUID) -> None:
        await self.outbox_repository.mark_published(
            outbox_id=outbox_id,
            published_at=datetime.now(tz=UTC),
        )
        logger.debug(f"Outbox {outbox_id} marked as published")

    async def bump_attempt(self, outbox_id: UUID, attempts: int, error: str) -> None:
        delay_seconds = self._compute_backoff_seconds(attempts=attempts)
        next_attempt_at = datetime.now(tz=UTC) + timedelta(seconds=delay_seconds)
        await self.outbox_repository.bump_attempt(
            outbox_id=outbox_id,
            error=error,
            next_attempt_at=next_attempt_at,
        )
        logger.warning(
            f"Outbox {outbox_id} attempt failed; next retry in {delay_seconds:.1f}s "
            f"(attempts done: {attempts + 1})",
        )

    def _compute_backoff_seconds(self, attempts: int) -> float:
        initial = self.outbox_dispatcher_config.OUTBOX_BACKOFF_INITIAL_SECONDS
        cap = self.outbox_dispatcher_config.OUTBOX_BACKOFF_MAX_SECONDS
        return min(cap, initial * (2 ** attempts))
