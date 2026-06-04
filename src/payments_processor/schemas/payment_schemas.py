from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue, field_validator

from payments_processor.constants import PaymentsConstants
from payments_processor.enums import CurrencyEnum, PaymentStatusEnum


class PaymentBase(BaseModel):
    amount: Decimal = Field(
        gt=Decimal(0),
        max_digits=PaymentsConstants.AMOUNT_MAX_DIGITS,
        decimal_places=PaymentsConstants.AMOUNT_DECIMAL_PLACES,
    )
    currency: CurrencyEnum
    description: str | None = Field(
        default=None,
        max_length=PaymentsConstants.DESCRIPTION_MAX_LEN,
    )
    meta: dict[str, JsonValue] | None = Field(
        default=None,
    )
    webhook_url: HttpUrl

    @field_validator("amount", mode="before")
    @classmethod
    def _prevent_float_precision_loss(cls, v: JsonValue) -> Decimal:
        if not isinstance(v, str | Decimal):
            error_message = (
                "Passing the amount as a anything but float is prohibited due to loss of precision."
                "Please pass the amount as a string (e.g., '1111122222333334.10')"
            )
            raise ValueError(error_message)  # noqa: TRY004
        return Decimal(v)

    @field_validator("webhook_url", mode="after")
    @classmethod
    def _check_webhook_url_length(cls, v: HttpUrl) -> HttpUrl:
        if len(str(v)) > PaymentsConstants.WEBHOOK_URL_MAX_LEN:
            error_message = f"webhook_url must be at most {PaymentsConstants.WEBHOOK_URL_MAX_LEN} characters"
            raise ValueError(error_message)
        return v

    model_config = ConfigDict(
        populate_by_name=True,
    )


class PaymentCreate(PaymentBase):
    pass


class PaymentCreatedResponse(BaseModel):
    payment_id: UUID
    status: PaymentStatusEnum
    created_at: datetime


class PaymentRead(PaymentBase):
    id: UUID
    status: PaymentStatusEnum
    idempotency_key: str
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime | None

    model_config = ConfigDict(
        from_attributes=True,
    )
