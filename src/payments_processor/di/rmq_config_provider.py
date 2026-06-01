from dishka import Provider, Scope, provide

from payments_processor.configs import RMQConfig


class RMQConfigProvider(Provider):
    @provide(scope=Scope.APP)
    def get_rmq_config(self) -> RMQConfig:
        return RMQConfig()  # type: ignore[call-args]
