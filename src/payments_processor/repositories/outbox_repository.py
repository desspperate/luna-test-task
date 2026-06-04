from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.enums import OutboxStatusEnum
from payments_processor.models import Outbox
from payments_processor.utils import BaseRepository


class OutboxRepository(BaseRepository[Outbox]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session=session, model=Outbox)

    async def enqueue(
        self,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        routing_key: str,
        payload: dict[str, Any],
    ) -> Outbox:
        statement = (
            insert(Outbox)
            .values(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                routing_key=routing_key,
                payload=payload,
            )
            .returning(Outbox)
        )
        result = await self.session.execute(statement)
        return result.scalar_one()

    async def fetch_pending(self, batch_size: int, now: datetime) -> Sequence[Outbox]:
        statement = (
            select(Outbox)
            .where(
                Outbox.status == OutboxStatusEnum.PENDING,
                Outbox.next_attempt_at <= now,
            )
            .order_by(Outbox.next_attempt_at, Outbox.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def mark_published(self, outbox_id: UUID, published_at: datetime) -> None:
        statement = (
            update(Outbox)
            .where(Outbox.id == outbox_id)
            .values(
                status=OutboxStatusEnum.PUBLISHED,
                published_at=published_at,
                last_error=None,
            )
        )
        await self.session.execute(statement)

    async def bump_attempt(
        self,
        outbox_id: UUID,
        error: str,
        next_attempt_at: datetime,
    ) -> None:
        statement = (
            update(Outbox)
            .where(Outbox.id == outbox_id)
            .values(
                attempts=Outbox.attempts + 1,
                last_error=error,
                next_attempt_at=next_attempt_at,
            )
        )
        await self.session.execute(statement)
