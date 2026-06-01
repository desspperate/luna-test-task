from typing import Any

from faststream.rabbit import RabbitBroker
from loguru import logger

from payments_processor.constants import PaymentsConstants


class PaymentEventPublisher:
    def __init__(self, broker: RabbitBroker) -> None:
        self.broker = broker

    async def publish(
            self,
            routing_key: str,
            payload: dict[str, Any],
            headers: dict[str, Any] | None = None,
    ) -> None:
        logger.debug(f"Publishing to '{PaymentsConstants.EXCHANGE_PAYMENTS}' with routing_key='{routing_key}'")
        await self.broker.publish(
            message=payload,
            exchange=PaymentsConstants.EXCHANGE_PAYMENTS,
            routing_key=routing_key,
            persist=True,
            mandatory=True,
            headers=headers or {},
        )

    async def publish_to_queue(
            self,
            queue: str,
            payload: dict[str, Any],
            headers: dict[str, Any] | None = None,
    ) -> None:
        logger.debug(f"Publishing directly to queue '{queue}'")
        await self.broker.publish(
            message=payload,
            queue=queue,
            persist=True,
            mandatory=True,
            headers=headers or {},
        )
