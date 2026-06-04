from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue
from loguru import logger

from payments_processor.constants import PaymentsConstants


def _make_payments_exchange() -> RabbitExchange:
    return RabbitExchange(
        name=PaymentsConstants.EXCHANGE_PAYMENTS,
        type=ExchangeType.TOPIC,
        durable=True,
    )


def _make_dlx_exchange() -> RabbitExchange:
    return RabbitExchange(
        name=PaymentsConstants.EXCHANGE_PAYMENTS_DLX,
        type=ExchangeType.TOPIC,
        durable=True,
    )


def _make_main_queue() -> RabbitQueue:
    return RabbitQueue(
        name=PaymentsConstants.QUEUE_PAYMENTS_NEW,
        durable=True,
        arguments={
            "x-dead-letter-exchange": PaymentsConstants.EXCHANGE_PAYMENTS_DLX,
            "x-dead-letter-routing-key": PaymentsConstants.PAYMENT_SAFETY_NET_ROUTING_KEY,
        },
    )


def _make_retry_queue(attempt: int, ttl_ms: int) -> RabbitQueue:
    return RabbitQueue(
        name=f"{PaymentsConstants.QUEUE_PAYMENTS_RETRY_PREFIX}{attempt}",
        durable=True,
        arguments={
            "x-message-ttl": ttl_ms,
            "x-dead-letter-exchange": PaymentsConstants.EXCHANGE_PAYMENTS,
            "x-dead-letter-routing-key": PaymentsConstants.PAYMENT_CREATED_ROUTING_KEY,
        },
    )


def _make_dlq() -> RabbitQueue:
    return RabbitQueue(
        name=PaymentsConstants.QUEUE_PAYMENTS_DLQ,
        durable=True,
    )


async def declare_topology(broker: RabbitBroker) -> None:
    logger.info("Declaring RabbitMQ topology")

    exchange = await broker.declare_exchange(_make_payments_exchange())
    dlx_exchange = await broker.declare_exchange(_make_dlx_exchange())

    main_queue = await broker.declare_queue(_make_main_queue())
    await main_queue.bind(
        exchange=exchange,
        routing_key=PaymentsConstants.PAYMENT_CREATED_ROUTING_KEY,
    )
    logger.info(f"Declared queue '{PaymentsConstants.QUEUE_PAYMENTS_NEW}'")

    for attempt, ttl_ms in enumerate(PaymentsConstants.RETRY_TTL_MS_BY_ATTEMPT, start=1):
        await broker.declare_queue(_make_retry_queue(attempt=attempt, ttl_ms=ttl_ms))
        logger.info(
            f"Declared retry queue '{PaymentsConstants.QUEUE_PAYMENTS_RETRY_PREFIX}{attempt}' "
            f"(ttl={ttl_ms} ms)",
        )

    dlq = await broker.declare_queue(_make_dlq())
    await dlq.bind(
        exchange=dlx_exchange,
        routing_key=PaymentsConstants.PAYMENT_SAFETY_NET_ROUTING_KEY,
    )
    await dlq.bind(
        exchange=dlx_exchange,
        routing_key=PaymentsConstants.PAYMENT_FAILED_ROUTING_KEY,
    )
    logger.info(f"Declared dead-letter queue '{PaymentsConstants.QUEUE_PAYMENTS_DLQ}'")

    logger.info("RabbitMQ topology declared")
