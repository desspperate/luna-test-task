import asyncio
import sys

from faststream.rabbit import RabbitBroker
from loguru import logger

from payments_processor.configs import RMQConfig
from payments_processor.messaging.topology import declare_topology
from payments_processor.utils import print_pd_settings


async def main() -> None:
    logger.remove()
    logger.add(sys.stderr, serialize=True)

    rmq_config = RMQConfig()  # type: ignore[call-args]
    print_pd_settings(rmq_config)

    broker = RabbitBroker(rmq_config.url)
    await broker.connect()
    try:
        await declare_topology(broker)
    finally:
        await broker.stop()


if __name__ == "__main__":
    asyncio.run(main())
