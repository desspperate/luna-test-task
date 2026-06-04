from uuid import UUID

from pydantic import BaseModel


class PaymentCreatedEvent(BaseModel):
    payment_id: UUID
