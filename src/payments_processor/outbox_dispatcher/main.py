import asyncio
import signal
import sys

from dishka import AsyncContainer
from faststream.rabbit import RabbitBroker
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.configs import AppConfig, OutboxDispatcherConfig, PGConfig, RMQConfig
from payments_processor.di import make_payments_container
from payments_processor.messaging import PaymentEventPublisher
from payments_processor.services import OutboxService
from payments_processor.utils import print_pd_settings


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
        dispatcher_config: OutboxDispatcherConfig,
        broker: RabbitBroker,
) -> None:
    publisher = PaymentEventPublisher(broker=broker)
    shutdown = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown.set)

    logger.info("Outbox dispatcher started")

    while not shutdown.is_set():
        try:
            async with container() as request_container:
                processed = await _process_batch(
                    request_container=request_container,
                    publisher=publisher,
                    batch_size=dispatcher_config.OUTBOX_BATCH_SIZE,
                )
        except Exception as e:
            logger.exception(f"Outbox dispatcher iteration failed: {e}")
            processed = 0

        if processed < dispatcher_config.OUTBOX_BATCH_SIZE:
            try:
                await asyncio.wait_for(
                    shutdown.wait(),
                    timeout=dispatcher_config.OUTBOX_POLL_INTERVAL_SECONDS,
                )
            except TimeoutError:
                pass

    logger.info("Outbox dispatcher shutting down")


async def main() -> None:
    logger.remove()
    logger.add(sys.stderr, serialize=True)

    app_config = AppConfig()  # type: ignore[call-args]
    container = make_payments_container(app_config_instance=app_config)
    try:
        print_pd_settings(app_config)
        print_pd_settings(await container.get(PGConfig))
        print_pd_settings(await container.get(RMQConfig))
        dispatcher_config = await container.get(OutboxDispatcherConfig)
        print_pd_settings(dispatcher_config)

        broker = await container.get(RabbitBroker)
        await _run_loop(
            container=container,
            dispatcher_config=dispatcher_config,
            broker=broker,
        )
    finally:
        await container.close()


if __name__ == "__main__":
    asyncio.run(main())
