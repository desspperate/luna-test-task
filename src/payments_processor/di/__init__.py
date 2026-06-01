from dishka import AsyncContainer, make_async_container

from payments_processor.configs import AppConfig

from .pg_config_provider import PGConfigProvider
from .sqlalchemy_provider import SqlalchemyProvider


def make_payments_container(app_config_instance: AppConfig) -> AsyncContainer:
    return make_async_container(
        PGConfigProvider(),
        SqlalchemyProvider(),
        context={AppConfig: app_config_instance},
    )
