from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter, Header, status
from loguru import logger

from payments_processor.actions import PaymentAction
from payments_processor.constants import PaymentsConstants
from payments_processor.models import Payment
from payments_processor.schemas import PaymentCreate, PaymentCreatedResponse, PaymentRead

router = APIRouter(
    prefix=f"{PaymentsConstants.API_V1_PREFIX}/payments",
    tags=["Payments"],
    route_class=DishkaRoute,
)


@router.post(
    "",
    response_model=PaymentCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_payment(
        payment_action: FromDishka[PaymentAction],
        payload: PaymentCreate,
        idempotency_key: str = Header(
            alias=PaymentsConstants.IDEMPOTENCY_KEY_HEADER,
            max_length=PaymentsConstants.IDEMPOTENCY_KEY_MAX_LEN,
            min_length=1,
        ),
) -> PaymentCreatedResponse:
    with logger.contextualize(idempotency_key=idempotency_key):
        payment = await payment_action.create_payment(
            amount=payload.amount,
            currency=payload.currency,
            description=payload.description,
            meta=payload.meta,
            idempotency_key=idempotency_key,
            webhook_url=str(payload.webhook_url),
        )
        return PaymentCreatedResponse(
            payment_id=payment.id,
            status=payment.status,
            created_at=payment.created_at,
        )


@router.get(
    "/{payment_id}",
    response_model=PaymentRead,
)
async def get_payment(
        payment_action: FromDishka[PaymentAction],
        payment_id: UUID,
) -> Payment:
    with logger.contextualize(payment_id=payment_id):
        return await payment_action.get_payment(payment_id=payment_id)
