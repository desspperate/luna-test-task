from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.configs import OutboxDispatcherConfig
from payments_processor.repositories import OutboxRepository
from payments_processor.services import OutboxService


class OutboxProvider(Provider):
    @provide(scope=Scope.APP)
    def get_outbox_dispatcher_config(self) -> OutboxDispatcherConfig:
        return OutboxDispatcherConfig()

    @provide(scope=Scope.REQUEST)
    def get_outbox_repository(self, session: AsyncSession) -> OutboxRepository:
        return OutboxRepository(session=session)

    @provide(scope=Scope.REQUEST)
    def get_outbox_service(
        self,
        outbox_repository: OutboxRepository,
        outbox_dispatcher_config: OutboxDispatcherConfig,
    ) -> OutboxService:
        return OutboxService(
            outbox_repository=outbox_repository,
            outbox_dispatcher_config=outbox_dispatcher_config,
        )
