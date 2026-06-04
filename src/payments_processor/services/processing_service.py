import asyncio
import secrets
from uuid import UUID

from loguru import logger

from payments_processor.configs import ConsumerConfig
from payments_processor.enums import ProcessingOutcomeEnum


class ProcessingService:
    def __init__(self, consumer_config: ConsumerConfig) -> None:
        self.consumer_config = consumer_config
        self._rng = secrets.SystemRandom()

    async def process(self, payment_id: UUID) -> ProcessingOutcomeEnum:
        delay_seconds = self._rng.uniform(
            self.consumer_config.CONSUMER_PROCESS_MIN_SECONDS,
            self.consumer_config.CONSUMER_PROCESS_MAX_SECONDS,
        )
        logger.info(f"Processing payment {payment_id}: emulating work for {delay_seconds:.2f}s")
        await asyncio.sleep(delay_seconds)

        succeeded = self._rng.random() < self.consumer_config.CONSUMER_SUCCESS_PROBABILITY
        outcome = ProcessingOutcomeEnum.SUCCEEDED if succeeded else ProcessingOutcomeEnum.FAILED
        logger.info(f"Processing payment {payment_id}: outcome={outcome.value}")
        return outcome
