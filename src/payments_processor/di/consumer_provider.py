from dishka import Provider, Scope, provide

from payments_processor.configs import ConsumerConfig
from payments_processor.services import ProcessingService


class ConsumerProvider(Provider):
    @provide(scope=Scope.APP)
    def get_consumer_config(self) -> ConsumerConfig:
        return ConsumerConfig()  # type: ignore[call-arg]

    @provide(scope=Scope.REQUEST)
    def get_processing_service(self, consumer_config: ConsumerConfig) -> ProcessingService:
        return ProcessingService(consumer_config=consumer_config)
