import httpx
from dishka import Provider, Scope, provide

from payments_processor.configs import WebhookConfig
from payments_processor.services import WebhookService
from payments_processor.utils import SSRFGuard


class WebhookProvider(Provider):
    @provide(scope=Scope.APP)
    def get_webhook_config(self) -> WebhookConfig:
        return WebhookConfig()  # type: ignore[call-args]

    @provide(scope=Scope.APP)
    def get_ssrf_guard(self, webhook_config: WebhookConfig) -> SSRFGuard:
        return SSRFGuard(allow_private_hosts=webhook_config.WEBHOOK_ALLOW_PRIVATE_HOSTS)

    @provide(scope=Scope.REQUEST)
    def get_webhook_service(
            self,
            http_client: httpx.AsyncClient,
            webhook_config: WebhookConfig,
            ssrf_guard: SSRFGuard,
    ) -> WebhookService:
        return WebhookService(
            http_client=http_client,
            webhook_config=webhook_config,
            ssrf_guard=ssrf_guard,
        )
