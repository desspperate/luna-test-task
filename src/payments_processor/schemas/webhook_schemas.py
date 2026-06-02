from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, JsonValue

from payments_processor.enums import CurrencyEnum, PaymentStatusEnum


class WebhookPayload(BaseModel):
    event_id: UUID
    payment_id: UUID
    status: PaymentStatusEnum
    amount: Decimal
    currency: CurrencyEnum
    processed_at: datetime | None
    metadata: dict[str, JsonValue] | None
