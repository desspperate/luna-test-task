from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.enums import CurrencyEnum, PaymentStatusEnum
from payments_processor.models import Payment
from payments_processor.utils import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session=session, model=Payment)

    async def create_payment(  # noqa: PLR0913
        self,
        amount: Decimal,
        currency: CurrencyEnum,
        description: str | None,
        meta: dict[str, Any] | None,
        idempotency_key: str,
        webhook_url: str,
    ) -> Payment:
        statement = (
            insert(Payment)
            .values(
                amount=amount,
                currency=currency,
                description=description,
                meta=meta,
                idempotency_key=idempotency_key,
                webhook_url=webhook_url,
            )
            .returning(Payment)
        )
        result = await self.session.execute(statement)
        return result.scalar_one()

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        statement = select(Payment).where(Payment.idempotency_key == idempotency_key)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def update_processing_outcome(
        self,
        payment_id: UUID,
        status: PaymentStatusEnum,
        processed_at: datetime,
    ) -> Payment | None:
        statement = (
            update(Payment)
            .where(Payment.id == payment_id)
            .values(status=status, processed_at=processed_at)
            .returning(Payment)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()
