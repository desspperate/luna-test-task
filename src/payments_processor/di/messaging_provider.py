from dishka import Provider, Scope, provide
from faststream.rabbit import RabbitBroker

from payments_processor.messaging import PaymentEventPublisher


class MessagingProvider(Provider):
    @provide(scope=Scope.APP)
    def get_payment_event_publisher(self, broker: RabbitBroker) -> PaymentEventPublisher:
        return PaymentEventPublisher(broker=broker)
