from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from payments_processor.constants import PaymentsConstants
from payments_processor.database import Base
from payments_processor.enums import CurrencyEnum, PaymentStatusEnum
from payments_processor.utils import uuid7


class Payment(Base):
    UQ_PAYMENT_IDEMPOTENCY_KEY = "uq_payment_idempotency_key"
    CK_PAYMENT_AMOUNT_POSITIVE = "ck_payment_amount_positive"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(
            precision=PaymentsConstants.AMOUNT_MAX_DIGITS,
            scale=PaymentsConstants.AMOUNT_DECIMAL_PLACES,
        ),
        nullable=False,
    )
    currency: Mapped[CurrencyEnum] = mapped_column(
        Enum(CurrencyEnum, native_enum=False),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        String(PaymentsConstants.DESCRIPTION_MAX_LEN),
        nullable=True,
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    status: Mapped[PaymentStatusEnum] = mapped_column(
        Enum(PaymentStatusEnum, native_enum=False),
        nullable=False,
        default=PaymentStatusEnum.PENDING,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(PaymentsConstants.IDEMPOTENCY_KEY_MAX_LEN),
        nullable=False,
    )
    webhook_url: Mapped[str] = mapped_column(
        String(PaymentsConstants.WEBHOOK_URL_MAX_LEN),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name=UQ_PAYMENT_IDEMPOTENCY_KEY,
        ),
        CheckConstraint(
            "amount > 0",
            name=CK_PAYMENT_AMOUNT_POSITIVE,
        ),
    )
