from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from payments_processor.enums import CurrencyEnum, PaymentStatusEnum
from payments_processor.models import Payment
from payments_processor.utils import uuid7


def _make_payment(
    *,
    payment_id: UUID | None = None,
    amount: Decimal = Decimal("100.00"),
    currency: CurrencyEnum = CurrencyEnum.RUB,
    description: str | None = "test payment",
    meta: dict[str, Any] | None = None,
    status: PaymentStatusEnum = PaymentStatusEnum.PENDING,
    idempotency_key: str = "test-idempotency-key",
    webhook_url: str = "https://example.com/wh",
    processed_at: datetime | None = None,
    created_at: datetime | None = None,
) -> Payment:
    payment = Payment(
        id=payment_id or uuid7(),
        amount=amount,
        currency=currency,
        description=description,
        meta=meta,
        status=status,
        idempotency_key=idempotency_key,
        webhook_url=webhook_url,
        processed_at=processed_at,
    )
    payment.created_at = created_at or datetime.now(tz=UTC)
    payment.updated_at = None
    return payment


@pytest.fixture
def make_payment():
    return _make_payment
