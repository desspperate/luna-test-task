from decimal import Decimal
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from payments_processor.enums import CurrencyEnum
from payments_processor.models import Payment
from payments_processor.services import PaymentService


class PaymentAction:
    def __init__(
        self,
        session: AsyncSession,
        payment_service: PaymentService,
    ) -> None:
        self.session = session
        self.payment_service = payment_service

    async def create_payment(  # noqa: PLR0913
        self,
        amount: Decimal,
        currency: CurrencyEnum,
        description: str | None,
        meta: dict[str, Any] | None,
        idempotency_key: str,
        webhook_url: str,
    ) -> Payment:
        payment, is_new = await self.payment_service.create_payment(
            amount=amount,
            currency=currency,
            description=description,
            meta=meta,
            idempotency_key=idempotency_key,
            webhook_url=webhook_url,
        )
        if is_new:
            await self.session.commit()
            logger.info(f"Payment created: id={payment.id} idempotency_key='{idempotency_key}'")
        return payment

    async def get_payment(self, payment_id: UUID) -> Payment:
        return await self.payment_service.get_payment(payment_id=payment_id)
