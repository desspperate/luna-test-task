from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.actions import PaymentAction
from payments_processor.repositories import OutboxRepository, PaymentRepository
from payments_processor.services import PaymentService
from payments_processor.utils import SSRFGuard


class PaymentProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_payment_action(
            self,
            session: AsyncSession,
            payment_service: PaymentService,
    ) -> PaymentAction:
        return PaymentAction(
            session=session,
            payment_service=payment_service,
        )

    @provide(scope=Scope.REQUEST)
    def get_payment_service(
            self,
            payment_repository: PaymentRepository,
            outbox_repository: OutboxRepository,
            ssrf_guard: SSRFGuard,
    ) -> PaymentService:
        return PaymentService(
            payment_repository=payment_repository,
            outbox_repository=outbox_repository,
            ssrf_guard=ssrf_guard,
        )

    @provide(scope=Scope.REQUEST)
    def get_payment_repository(self, session: AsyncSession) -> PaymentRepository:
        return PaymentRepository(session=session)
