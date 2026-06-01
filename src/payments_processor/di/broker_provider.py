from collections.abc import AsyncIterable

from dishka import Provider, Scope, provide
from faststream.rabbit import RabbitBroker
from loguru import logger

from payments_processor.configs import RMQConfig


class BrokerProvider(Provider):
    @provide(scope=Scope.APP)
    async def get_broker(self, rmq_config: RMQConfig) -> AsyncIterable[RabbitBroker]:
        broker = RabbitBroker(rmq_config.url)
        await broker.connect()
        logger.debug("RabbitMQ broker connected")
        yield broker
        await broker.stop()
        logger.debug("RabbitMQ broker closed")
