import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka import AsyncContainer
from dishka.integrations import fastapi as fastapi_integration
from fastapi import FastAPI
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.configs import AppConfig, OutboxDispatcherConfig, PGConfig, RMQConfig
from payments_processor.di import make_payments_container
from payments_processor.messaging import PaymentEventPublisher
from payments_processor.routers import worker_health_router
from payments_processor.services import OutboxService
from payments_processor.utils import HealthState, print_pd_settings


async def _process_batch(
        request_container: AsyncContainer,
        publisher: PaymentEventPublisher,
        batch_size: int,
) -> int:
    session = await request_container.get(AsyncSession)
    outbox_service = await request_container.get(OutboxService)

    rows = await outbox_service.fetch_pending(batch_size=batch_size)
    for row in rows:
        try:
            await publisher.publish(routing_key=row.routing_key, payload=row.payload)
            await outbox_service.mark_published(outbox_id=row.id)
            logger.info(f"Outbox {row.id} published to '{row.routing_key}'")
        except Exception as e:
            logger.exception(f"Failed to publish outbox {row.id}")
            await outbox_service.bump_attempt(
                outbox_id=row.id,
                attempts=row.attempts,
                error=str(e),
            )
    await session.commit()
    return len(rows)


async def _run_loop(
        container: AsyncContainer,
        publisher: PaymentEventPublisher,
        dispatcher_config: OutboxDispatcherConfig,
        health_state: HealthState,
) -> None:
    logger.info("Outbox dispatcher loop started")

    while True:
        try:
            async with container() as request_container:
                processed = await _process_batch(
                    request_container=request_container,
                    publisher=publisher,
                    batch_size=dispatcher_config.OUTBOX_BATCH_SIZE,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Outbox dispatcher iteration failed")
            processed = 0

        health_state.heartbeat()

        if processed < dispatcher_config.OUTBOX_BATCH_SIZE:
            await asyncio.sleep(dispatcher_config.OUTBOX_POLL_INTERVAL_SECONDS)


def create_app() -> FastAPI:
    logger.remove()
    logger.add(sys.stderr, serialize=True)

    app_config = AppConfig()  # type: ignore[call-arg]
    container = make_payments_container(app_config_instance=app_config)
    dispatcher_config = OutboxDispatcherConfig()  # type: ignore[call-arg]
    health_state = HealthState(
        stale_after_seconds=dispatcher_config.OUTBOX_POLL_INTERVAL_SECONDS * 10,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Outbox dispatcher starting up...")

        print_pd_settings(app_config)
        print_pd_settings(await container.get(PGConfig))
        print_pd_settings(await container.get(RMQConfig))
        print_pd_settings(dispatcher_config)

        publisher = await container.get(PaymentEventPublisher)

        dispatcher_task = asyncio.create_task(
            _run_loop(
                container=container,
                publisher=publisher,
                dispatcher_config=dispatcher_config,
                health_state=health_state,
            ),
            name="outbox_dispatcher_loop",
        )
        health_state.mark_started()
        logger.info("Outbox dispatcher started")

        try:
            yield
        finally:
            logger.info("Outbox dispatcher shutting down...")
            dispatcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await dispatcher_task
            await container.close()

    application = FastAPI(
        debug=app_config.DEBUG,
        title="Outbox Dispatcher",
        lifespan=lifespan,
    )
    application.state.health = health_state

    fastapi_integration.setup_dishka(container=container, app=application)
    application.include_router(worker_health_router)

    return application


app = create_app()
