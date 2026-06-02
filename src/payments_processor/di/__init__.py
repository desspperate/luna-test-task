from dishka import AsyncContainer, make_async_container

from payments_processor.configs import AppConfig

from .broker_provider import BrokerProvider
from .http_client_provider import HttpClientProvider
from .outbox_provider import OutboxProvider
from .payment_provider import PaymentProvider
from .pg_config_provider import PGConfigProvider
from .rmq_config_provider import RMQConfigProvider
from .sqlalchemy_provider import SqlalchemyProvider
from .webhook_provider import WebhookProvider


def make_payments_container(app_config_instance: AppConfig) -> AsyncContainer:
    return make_async_container(
        PGConfigProvider(),
        RMQConfigProvider(),
        SqlalchemyProvider(),
        BrokerProvider(),
        HttpClientProvider(),
        WebhookProvider(),
        OutboxProvider(),
        PaymentProvider(),
        context={AppConfig: app_config_instance},
    )
