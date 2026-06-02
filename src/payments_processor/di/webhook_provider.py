import httpx
from dishka import Provider, Scope, provide

from payments_processor.configs import WebhookConfig
from payments_processor.services import WebhookService


class WebhookProvider(Provider):
    @provide(scope=Scope.APP)
    def get_webhook_config(self) -> WebhookConfig:
        return WebhookConfig()  # type: ignore[call-args]

    @provide(scope=Scope.REQUEST)
    def get_webhook_service(
            self,
            http_client: httpx.AsyncClient,
            webhook_config: WebhookConfig,
    ) -> WebhookService:
        return WebhookService(
            http_client=http_client,
            webhook_config=webhook_config,
        )
