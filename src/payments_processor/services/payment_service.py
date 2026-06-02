from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID

from asyncpg import CheckViolationError, UniqueViolationError
from loguru import logger
from sqlalchemy.exc import IntegrityError

from payments_processor.constants import PaymentsConstants
from payments_processor.enums import CurrencyEnum
from payments_processor.errors import (
    IdempotencyKeyConflictError,
    PaymentNotFoundError,
    UnhandledIntegrityError,
)
from payments_processor.models import Payment
from payments_processor.repositories import OutboxRepository, PaymentRepository
from payments_processor.utils import HandleIntegrityHelpers, get_asyncpg_error


@asynccontextmanager
async def handle_payment_integrity() -> AsyncIterator[None]:
    try:
        yield
    except IntegrityError as e:
        asyncpg_error = get_asyncpg_error(e)
        if asyncpg_error is None:
            raise UnhandledIntegrityError from e

        if isinstance(asyncpg_error, UniqueViolationError | CheckViolationError):
            constraint = HandleIntegrityHelpers.get_constraint(asyncpg_error, e)
            logger.debug(f"Integrity violation on constraint: {constraint}")

        raise UnhandledIntegrityError from e


class PaymentService:
    def __init__(
            self,
            payment_repository: PaymentRepository,
            outbox_repository: OutboxRepository,
    ) -> None:
        self.payment_repository = payment_repository
        self.outbox_repository = outbox_repository

    async def create_payment(
            self,
            amount: Decimal,
            currency: CurrencyEnum,
            description: str | None,
            meta: dict[str, Any] | None,
            idempotency_key: str,
            webhook_url: str,
    ) -> tuple[Payment, bool]:
        """
            :returns payment, is_new_payment
        """
        logger.info(f"Creating payment with idempotency_key='{idempotency_key}'")

        existing = await self.payment_repository.get_by_idempotency_key(idempotency_key=idempotency_key)
        if existing is not None:
            self._ensure_idempotent_match(
                existing=existing,
                amount=amount,
                currency=currency,
                webhook_url=webhook_url,
                idempotency_key=idempotency_key,
            )
            logger.info(f"Idempotent hit: returning existing payment {existing.id}")
            return existing, False

        async with handle_payment_integrity():
            new_payment = await self.payment_repository.create_payment(
                amount=amount,
                currency=currency,
                description=description,
                meta=meta,
                idempotency_key=idempotency_key,
                webhook_url=webhook_url,
            )
            await self.outbox_repository.enqueue(
                aggregate_type=PaymentsConstants.PAYMENT_AGGREGATE_TYPE,
                aggregate_id=new_payment.id,
                event_type=PaymentsConstants.PAYMENT_CREATED_EVENT_TYPE,
                routing_key=PaymentsConstants.PAYMENT_CREATED_ROUTING_KEY,
                payload={"payment_id": str(new_payment.id)},
            )
            await self.payment_repository.session.flush()

        return new_payment, True

    async def get_payment(self, payment_id: UUID) -> Payment:
        logger.info(f"Getting payment: {payment_id}")
        payment = await self.payment_repository.get_by_id(obj_id=payment_id)
        if payment is None:
            raise PaymentNotFoundError(payment_id=payment_id)
        return payment

    @staticmethod
    def _ensure_idempotent_match(
            existing: Payment,
            amount: Decimal,
            currency: CurrencyEnum,
            webhook_url: str,
            idempotency_key: str,
    ) -> None:
        conflicting: list[str] = []
        if existing.amount != amount:
            conflicting.append("amount")
        if existing.currency != currency:
            conflicting.append("currency")
        if existing.webhook_url != webhook_url:
            conflicting.append("webhook_url")
        if conflicting:
            raise IdempotencyKeyConflictError(
                idempotency_key=idempotency_key,
            )
