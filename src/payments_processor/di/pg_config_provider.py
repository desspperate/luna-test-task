from dishka import Provider, Scope, provide
from sqlalchemy import URL

from payments_processor.configs import PGConfig


class PGConfigProvider(Provider):
    @provide(scope=Scope.APP)
    def get_pg_config(self) -> PGConfig:
        return PGConfig()  # type: ignore[call-args]

    @provide(scope=Scope.APP)
    def get_sqlalchemy_url(self, pg_config: PGConfig) -> URL:
        return URL.create(
            drivername=pg_config.PG_DRIVER,
            host=pg_config.PG_HOST,
            port=pg_config.PG_PORT,
            username=pg_config.PG_USER,
            password=pg_config.PG_PASSWORD.get_secret_value(),
            database=pg_config.PG_DB,
        )
