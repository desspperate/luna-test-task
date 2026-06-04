import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payments_processor.constants import PaymentsConstants
from payments_processor.enums import OutboxStatusEnum
from payments_processor.messaging import PaymentEventPublisher
from payments_processor.models import Outbox
from payments_processor.outbox_dispatcher.main import (
    _process_batch,  # pyright: ignore[reportPrivateUsage]
)
from payments_processor.services import OutboxService

if TYPE_CHECKING:
    from dishka import AsyncContainer

pytestmark = pytest.mark.integration


async def _insert_pending_outbox(
    session: AsyncSession,
    payment_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[UUID, str, dict[str, Any]]:
    pid = payment_id or uuid4()
    row = Outbox(
        aggregate_type=PaymentsConstants.PAYMENT_AGGREGATE_TYPE,
        aggregate_id=pid,
        event_type=PaymentsConstants.PAYMENT_CREATED_EVENT_TYPE,
        routing_key=PaymentsConstants.PAYMENT_CREATED_ROUTING_KEY,
        payload=payload or {"payment_id": str(pid)},
        status=OutboxStatusEnum.PENDING,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row.id, row.routing_key, row.payload


async def _fetch_outbox(
    session_maker: async_sessionmaker[AsyncSession],
    outbox_id: UUID,
) -> Outbox:
    async with session_maker() as fresh:
        return (await fresh.execute(select(Outbox).where(Outbox.id == outbox_id))).scalar_one()


class TestOutboxDispatcher:
    async def test_publishes_pending_and_marks_published(
        self,
        pg_session: AsyncSession,
        session_maker: async_sessionmaker[AsyncSession],
        api_app: FastAPI,
    ) -> None:
        row_id, routing_key, payload = await _insert_pending_outbox(pg_session)

        publisher = AsyncMock(spec=PaymentEventPublisher)
        container = api_app.state.container

        async with container() as request_container:
            processed = await _process_batch(
                request_container=request_container,
                publisher=publisher,
                batch_size=10,
            )
        assert processed == 1
        publisher.publish.assert_awaited_once_with(
            routing_key=routing_key,
            payload=payload,
        )

        refreshed = await _fetch_outbox(session_maker, row_id)
        assert refreshed.status == OutboxStatusEnum.PUBLISHED
        assert refreshed.published_at is not None

    async def test_publisher_failure_bumps_attempt(
        self,
        pg_session: AsyncSession,
        session_maker: async_sessionmaker[AsyncSession],
        api_app: FastAPI,
    ) -> None:
        row_id, _, _ = await _insert_pending_outbox(pg_session)

        publisher = AsyncMock(spec=PaymentEventPublisher)
        publisher.publish.side_effect = RuntimeError("broker down")

        container = api_app.state.container
        async with container() as request_container:
            await _process_batch(
                request_container=request_container,
                publisher=publisher,
                batch_size=10,
            )

        refreshed = await _fetch_outbox(session_maker, row_id)
        assert refreshed.status == OutboxStatusEnum.PENDING
        assert refreshed.attempts == 1
        assert refreshed.last_error is not None
        assert "broker down" in refreshed.last_error
        assert refreshed.next_attempt_at > datetime.now(tz=UTC)

    async def test_skip_locked_prevents_double_processing(
        self,
        pg_session: AsyncSession,
        session_maker: async_sessionmaker[AsyncSession],
        api_app: FastAPI,
    ) -> None:
        for _ in range(4):
            await _insert_pending_outbox(pg_session)

        publisher = AsyncMock(spec=PaymentEventPublisher)
        container = api_app.state.container

        async def batch() -> int:
            async with container() as request_container:
                return await _process_batch(
                    request_container=request_container,
                    publisher=publisher,
                    batch_size=2,
                )

        results = await asyncio.gather(batch(), batch())
        assert sum(results) == 4
        assert publisher.publish.await_count == 4

        async with session_maker() as fresh:
            rows = (await fresh.execute(select(Outbox))).scalars().all()
        published = [r for r in rows if r.status == OutboxStatusEnum.PUBLISHED]
        assert len(published) == 4

    async def test_future_next_attempt_not_picked_up(
        self,
        pg_session: AsyncSession,
        session_maker: async_sessionmaker[AsyncSession],
        api_app: FastAPI,
    ) -> None:
        _ = session_maker
        row = Outbox(
            aggregate_type=PaymentsConstants.PAYMENT_AGGREGATE_TYPE,
            aggregate_id=uuid4(),
            event_type=PaymentsConstants.PAYMENT_CREATED_EVENT_TYPE,
            routing_key=PaymentsConstants.PAYMENT_CREATED_ROUTING_KEY,
            payload={"payment_id": str(uuid4())},
            status=OutboxStatusEnum.PENDING,
            next_attempt_at=datetime.now(tz=UTC) + timedelta(hours=1),
        )
        pg_session.add(row)
        await pg_session.commit()

        publisher = AsyncMock(spec=PaymentEventPublisher)
        container = api_app.state.container
        async with container() as request_container:
            processed = await _process_batch(
                request_container=request_container,
                publisher=publisher,
                batch_size=10,
            )
        assert processed == 0
        publisher.publish.assert_not_awaited()


class TestOutboxBackoff:
    @pytest.mark.parametrize(
        ("attempts", "expected"),
        [
            (0, 2.0),
            (1, 4.0),
            (2, 8.0),
            (3, 16.0),
            (10, 60.0),  # capped at OUTBOX_BACKOFF_MAX_SECONDS=60
        ],
    )
    async def test_backoff_formula(
        self,
        api_app: FastAPI,
        attempts: int,
        expected: float,
    ) -> None:
        container = cast("AsyncContainer", api_app.state.container)
        async with container() as request_container:
            svc = await request_container.get(OutboxService)
            assert svc._compute_backoff_seconds(attempts=attempts) == expected  # pyright: ignore[reportPrivateUsage]
