import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dishka import AsyncContainer
from dishka.integrations import fastapi as fastapi_integration
from fastapi import FastAPI
from faststream import AckPolicy
from faststream.rabbit import Channel, RabbitBroker, RabbitMessage, RabbitQueue
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.configs import AppConfig, ConsumerConfig, PGConfig, RMQConfig, WebhookConfig
from payments_processor.constants import PaymentsConstants
from payments_processor.di import make_payments_container
from payments_processor.enums import PaymentStatusEnum
from payments_processor.errors import PaymentNotFoundError, WebhookSendError
from payments_processor.messaging import (
    PaymentEventPublisher,
    build_dlq_headers,
    build_retry_headers,
    get_retry_count,
)
from payments_processor.routers import worker_health_router
from payments_processor.schemas import PaymentCreatedEvent
from payments_processor.services import PaymentService, ProcessingService, WebhookService
from payments_processor.utils import HealthState, print_pd_settings


async def _retry_or_dlq(
        publisher: PaymentEventPublisher,
        msg: RabbitMessage,
        event: PaymentCreatedEvent,
        error: WebhookSendError,
        max_retries: int,
) -> None:
    current_count = get_retry_count(headers=msg.headers)
    next_count = current_count + 1
    payload = {"payment_id": str(event.payment_id)}

    if next_count > max_retries:
        logger.warning(
            f"Retries exhausted ({current_count}/{max_retries}); routing payment "
            f"{event.payment_id} to DLQ (reason={error.reason})",
        )
        await publisher.publish_to_dlx(
            routing_key=PaymentsConstants.PAYMENT_FAILED_ROUTING_KEY,
            payload=payload,
            headers=build_dlq_headers(retry_count=current_count, reason=error.reason),
        )
        return

    retry_queue = f"{PaymentsConstants.QUEUE_PAYMENTS_RETRY_PREFIX}{next_count}"
    logger.warning(
        f"Webhook delivery failed for payment {event.payment_id}; scheduling retry "
        f"{next_count}/{max_retries} via '{retry_queue}' (reason={error.reason})",
    )
    await publisher.publish_to_queue(
        queue=retry_queue,
        payload=payload,
        headers=build_retry_headers(next_count=next_count, reason=error.reason),
    )


async def _handle_payment_created(
        event: PaymentCreatedEvent,
        msg: RabbitMessage,
        container: AsyncContainer,
        publisher: PaymentEventPublisher,
        max_retries: int,
) -> None:
    with logger.contextualize(payment_id=str(event.payment_id)):
        try:
            async with container() as request_container:
                session = await request_container.get(AsyncSession)
                payment_service = await request_container.get(PaymentService)
                processing_service = await request_container.get(ProcessingService)
                webhook_service = await request_container.get(WebhookService)

                payment = await payment_service.get_payment(payment_id=event.payment_id)

                if payment.status == PaymentStatusEnum.PENDING:
                    outcome = await processing_service.process(payment_id=event.payment_id)
                    payment = await payment_service.apply_processing_outcome(
                        payment_id=event.payment_id,
                        outcome=outcome,
                    )
                    await session.commit()
                else:
                    logger.info(
                        f"Payment already processed with status={payment.status.name}; "
                        f"skipping emulation and re-attempting webhook",
                    )

                try:
                    await webhook_service.send(payment=payment)
                except WebhookSendError as e:
                    await _retry_or_dlq(
                        publisher=publisher,
                        msg=msg,
                        event=event,
                        error=e,
                        max_retries=max_retries,
                    )

            await msg.ack()
        except PaymentNotFoundError:
            logger.error(f"Payment {event.payment_id} not found; rejecting to safety-net DLQ")
            await msg.reject(requeue=False)
        except Exception as e:
            logger.exception(f"Unexpected failure processing payment {event.payment_id}: {e}")
            await msg.nack(requeue=False)


def _register_consumer(
        broker: RabbitBroker,
        container: AsyncContainer,
        consumer_config: ConsumerConfig,
        publisher: PaymentEventPublisher,
) -> None:
    queue = RabbitQueue(
        name=PaymentsConstants.QUEUE_PAYMENTS_NEW,
        durable=True,
        arguments={
            "x-dead-letter-exchange": PaymentsConstants.EXCHANGE_PAYMENTS_DLX,
            "x-dead-letter-routing-key": PaymentsConstants.PAYMENT_SAFETY_NET_ROUTING_KEY,
        },
    )
    subscriber = broker.subscriber(
        queue=queue,
        channel=Channel(prefetch_count=consumer_config.CONSUMER_PREFETCH_COUNT),
        ack_policy=AckPolicy.MANUAL,
    )

    async def _entrypoint(event: PaymentCreatedEvent, msg: RabbitMessage) -> None:
        await _handle_payment_created(
            event=event,
            msg=msg,
            container=container,
            publisher=publisher,
            max_retries=consumer_config.CONSUMER_MAX_RETRIES,
        )

    subscriber(_entrypoint)


def _broker_is_alive(broker: RabbitBroker) -> bool:
    if not broker.running:
        return False
    connection = broker._connection  # type: ignore[reportPrivateUsage]  # noqa: SLF001
    if connection is None:
        return False
    return not connection.is_closed


def create_app() -> FastAPI:
    logger.remove()
    logger.add(sys.stderr, serialize=True)

    app_config = AppConfig()  # type: ignore[call-arg]
    container = make_payments_container(app_config_instance=app_config)
    health_state = HealthState()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("Consumer starting up...")

        print_pd_settings(app_config)
        print_pd_settings(await container.get(PGConfig))
        print_pd_settings(await container.get(RMQConfig))
        print_pd_settings(await container.get(WebhookConfig))
        consumer_config = await container.get(ConsumerConfig)
        print_pd_settings(consumer_config)

        broker = await container.get(RabbitBroker)
        publisher = await container.get(PaymentEventPublisher)

        _register_consumer(
            broker=broker,
            container=container,
            consumer_config=consumer_config,
            publisher=publisher,
        )

        await broker.start()
        health_state.set_liveness_check(lambda: _broker_is_alive(broker))
        health_state.mark_started()
        logger.info("Consumer started")

        yield

        logger.info("Consumer shutting down...")
        await container.close()

    application = FastAPI(
        debug=app_config.DEBUG,
        title="Payments Consumer",
        lifespan=lifespan,
    )
    application.state.health = health_state

    fastapi_integration.setup_dishka(container=container, app=application)
    application.include_router(worker_health_router)

    return application


app = create_app()
