from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from freezegun import freeze_time

from payments_processor.constants import PaymentsConstants
from payments_processor.enums import CurrencyEnum, PaymentStatusEnum, ProcessingOutcomeEnum
from payments_processor.errors import (
    IdempotencyKeyConflictError,
    PaymentNotFoundError,
    WebhookUrlNotAllowedError,
)
from payments_processor.services import PaymentService


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class Doubles:
    payment_repo: MagicMock
    outbox_repo: MagicMock
    ssrf_guard: MagicMock
    service: PaymentService
    enqueue_payloads: list[dict[str, Any]] = field(default_factory=list)


def _build(
    *,
    existing_by_key: Any = None,
    created_payment: Any = None,
    fetched_payment: Any = None,
    updated_payment: Any = None,
    ssrf_should_block: bool = False,
) -> Doubles:
    session = MagicMock()
    session.flush = AsyncMock()

    payment_repo = MagicMock()
    payment_repo.session = session
    payment_repo.get_by_idempotency_key = AsyncMock(return_value=existing_by_key)
    payment_repo.create_payment = AsyncMock(return_value=created_payment)
    payment_repo.get_by_id = AsyncMock(return_value=fetched_payment)
    payment_repo.update_processing_outcome = AsyncMock(return_value=updated_payment)

    outbox_repo = MagicMock()
    outbox_repo.enqueue = AsyncMock()

    ssrf_guard = MagicMock()
    if ssrf_should_block:
        ssrf_guard.validate_url = AsyncMock(
            side_effect=WebhookUrlNotAllowedError(url="bad", reason="address_disallowed"),
        )
    else:
        ssrf_guard.validate_url = AsyncMock()

    service = PaymentService(
        payment_repository=payment_repo,
        outbox_repository=outbox_repo,
        ssrf_guard=ssrf_guard,
    )
    return Doubles(
        payment_repo=payment_repo,
        outbox_repo=outbox_repo,
        ssrf_guard=ssrf_guard,
        service=service,
    )


# ---------------------------------------------------------------------------
# create_payment
# ---------------------------------------------------------------------------


class TestCreatePayment_NewPayment:
    async def test_returns_created_payment_marked_as_new(
        self, make_payment,
    ) -> None:
        new_payment = make_payment()
        d = _build(created_payment=new_payment)

        result, is_new = await d.service.create_payment(
            amount=new_payment.amount,
            currency=new_payment.currency,
            description="d",
            meta=None,
            idempotency_key="k1",
            webhook_url=new_payment.webhook_url,
        )

        assert result is new_payment
        assert is_new is True

    async def test_persists_payment_via_repository(self, make_payment) -> None:
        new_payment = make_payment(
            amount=Decimal("250.00"),
            currency=CurrencyEnum.EUR,
            description="hello",
            meta={"k": "v"},
        )
        d = _build(created_payment=new_payment)

        await d.service.create_payment(
            amount=Decimal("250.00"),
            currency=CurrencyEnum.EUR,
            description="hello",
            meta={"k": "v"},
            idempotency_key="k1",
            webhook_url=new_payment.webhook_url,
        )

        d.payment_repo.create_payment.assert_awaited_once_with(
            amount=Decimal("250.00"),
            currency=CurrencyEnum.EUR,
            description="hello",
            meta={"k": "v"},
            idempotency_key="k1",
            webhook_url=new_payment.webhook_url,
        )

    async def test_enqueues_outbox_event_with_payment_id(self, make_payment) -> None:
        new_payment = make_payment()
        d = _build(created_payment=new_payment)

        await d.service.create_payment(
            amount=new_payment.amount,
            currency=new_payment.currency,
            description=None,
            meta=None,
            idempotency_key="k1",
            webhook_url=new_payment.webhook_url,
        )

        d.outbox_repo.enqueue.assert_awaited_once_with(
            aggregate_type=PaymentsConstants.PAYMENT_AGGREGATE_TYPE,
            aggregate_id=new_payment.id,
            event_type=PaymentsConstants.PAYMENT_CREATED_EVENT_TYPE,
            routing_key=PaymentsConstants.PAYMENT_CREATED_ROUTING_KEY,
            payload={"payment_id": str(new_payment.id)},
        )

    async def test_flushes_session_after_enqueue(self, make_payment) -> None:
        d = _build(created_payment=make_payment())

        await d.service.create_payment(
            amount=Decimal("100"),
            currency=CurrencyEnum.RUB,
            description=None,
            meta=None,
            idempotency_key="k1",
            webhook_url="https://example.com/wh",
        )
        d.payment_repo.session.flush.assert_awaited_once()


class TestCreatePayment_Idempotency:
    async def test_returns_existing_when_payload_matches(self, make_payment) -> None:
        existing = make_payment(idempotency_key="k1")
        d = _build(existing_by_key=existing)

        result, is_new = await d.service.create_payment(
            amount=existing.amount,
            currency=existing.currency,
            description="anything",
            meta={"any": "thing"},
            idempotency_key="k1",
            webhook_url=existing.webhook_url,
        )

        assert result is existing
        assert is_new is False
        d.payment_repo.create_payment.assert_not_called()
        d.outbox_repo.enqueue.assert_not_called()
        d.payment_repo.session.flush.assert_not_called()

    @pytest.mark.parametrize(
        ("differing_field", "new_value"),
        [
            ("amount", Decimal("999.99")),
            ("currency", CurrencyEnum.USD),
            ("webhook_url", "https://other.example.com/wh"),
        ],
    )
    async def test_conflict_raised_when_payload_differs(
        self, make_payment, differing_field: str, new_value: Any,
    ) -> None:
        existing = make_payment(
            amount=Decimal("100.00"),
            currency=CurrencyEnum.RUB,
            webhook_url="https://example.com/wh",
            idempotency_key="k1",
        )
        d = _build(existing_by_key=existing)

        kwargs: dict[str, Any] = {
            "amount": Decimal("100.00"),
            "currency": CurrencyEnum.RUB,
            "description": None,
            "meta": None,
            "idempotency_key": "k1",
            "webhook_url": "https://example.com/wh",
        }
        kwargs[differing_field] = new_value

        with pytest.raises(IdempotencyKeyConflictError) as exc_info:
            await d.service.create_payment(**kwargs)

        assert exc_info.value.idempotency_key == "k1"

    async def test_conflict_details_do_not_leak_field_values(
        self, make_payment,
    ) -> None:
        existing = make_payment(amount=Decimal("100"), idempotency_key="k1")
        d = _build(existing_by_key=existing)

        with pytest.raises(IdempotencyKeyConflictError) as exc_info:
            await d.service.create_payment(
                amount=Decimal("999.99"),
                currency=existing.currency,
                description=None,
                meta=None,
                idempotency_key="k1",
                webhook_url=existing.webhook_url,
            )
        details = exc_info.value.details or {}
        rendered = repr(details)
        assert "999.99" not in rendered
        assert "100" not in rendered

    async def test_description_and_meta_do_not_affect_idempotency(
        self, make_payment,
    ) -> None:
        """Only amount, currency, webhook_url participate in the match."""
        existing = make_payment(description="old", meta={"a": 1}, idempotency_key="k1")
        d = _build(existing_by_key=existing)

        result, is_new = await d.service.create_payment(
            amount=existing.amount,
            currency=existing.currency,
            description="new",  # different
            meta={"b": 2},  # different
            idempotency_key="k1",
            webhook_url=existing.webhook_url,
        )
        assert result is existing
        assert is_new is False


class TestCreatePayment_SSRFGuardOrdering:
    async def test_guard_runs_before_repository_lookup(self) -> None:
        d = _build(ssrf_should_block=True)

        with pytest.raises(WebhookUrlNotAllowedError):
            await d.service.create_payment(
                amount=Decimal("100"),
                currency=CurrencyEnum.RUB,
                description=None,
                meta=None,
                idempotency_key="k",
                webhook_url="https://bad.example.com/",
            )

        d.payment_repo.get_by_idempotency_key.assert_not_called()
        d.payment_repo.create_payment.assert_not_called()
        d.outbox_repo.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# get_payment
# ---------------------------------------------------------------------------


class TestGetPayment:
    async def test_returns_payment_when_found(self, make_payment) -> None:
        payment = make_payment()
        d = _build(fetched_payment=payment)

        result = await d.service.get_payment(payment_id=payment.id)
        assert result is payment

    async def test_raises_with_id_when_not_found(self) -> None:
        d = _build(fetched_payment=None)
        pid = uuid4()

        with pytest.raises(PaymentNotFoundError) as exc_info:
            await d.service.get_payment(payment_id=pid)
        assert exc_info.value.payment_id == pid


# ---------------------------------------------------------------------------
# apply_processing_outcome
# ---------------------------------------------------------------------------


class TestApplyProcessingOutcome:
    @pytest.mark.parametrize(
        ("outcome", "expected_status"),
        [
            (ProcessingOutcomeEnum.SUCCEEDED, PaymentStatusEnum.SUCCEEDED),
            (ProcessingOutcomeEnum.FAILED, PaymentStatusEnum.FAILED),
        ],
    )
    async def test_maps_outcome_to_payment_status(
        self,
        make_payment,
        outcome: ProcessingOutcomeEnum,
        expected_status: PaymentStatusEnum,
    ) -> None:
        d = _build(updated_payment=make_payment(status=expected_status))

        await d.service.apply_processing_outcome(payment_id=uuid4(), outcome=outcome)

        update_kwargs = d.payment_repo.update_processing_outcome.await_args.kwargs
        assert update_kwargs["status"] == expected_status

    async def test_records_processing_timestamp_at_call_time(
        self, make_payment,
    ) -> None:
        d = _build(updated_payment=make_payment(status=PaymentStatusEnum.SUCCEEDED))

        with freeze_time("2026-04-01T12:34:56Z"):
            await d.service.apply_processing_outcome(
                payment_id=uuid4(),
                outcome=ProcessingOutcomeEnum.SUCCEEDED,
            )

        update_kwargs = d.payment_repo.update_processing_outcome.await_args.kwargs
        assert update_kwargs["processed_at"] == datetime(
            2026, 4, 1, 12, 34, 56, tzinfo=UTC,
        )

    async def test_raises_with_id_when_payment_disappeared(self) -> None:
        d = _build(updated_payment=None)
        pid = uuid4()

        with pytest.raises(PaymentNotFoundError) as exc_info:
            await d.service.apply_processing_outcome(
                payment_id=pid,
                outcome=ProcessingOutcomeEnum.SUCCEEDED,
            )
        assert exc_info.value.payment_id == pid


# ---------------------------------------------------------------------------
# _ensure_idempotent_match (helper)
# ---------------------------------------------------------------------------


class TestEnsureIdempotentMatchHelper:
    def test_no_conflict_returns_none(self, make_payment) -> None:
        existing = make_payment(
            amount=Decimal("100"),
            currency=CurrencyEnum.RUB,
            webhook_url="https://example.com/wh",
        )
        # Should not raise
        PaymentService._ensure_idempotent_match(
            existing=existing,
            amount=Decimal("100"),
            currency=CurrencyEnum.RUB,
            webhook_url="https://example.com/wh",
            idempotency_key="k",
        )

    def test_raises_single_conflict_even_when_multiple_fields_differ(
        self, make_payment,
    ) -> None:
        existing = make_payment(
            amount=Decimal("100"),
            currency=CurrencyEnum.RUB,
            webhook_url="https://example.com/wh",
        )
        with pytest.raises(IdempotencyKeyConflictError) as exc_info:
            PaymentService._ensure_idempotent_match(
                existing=existing,
                amount=Decimal("999"),
                currency=CurrencyEnum.USD,
                webhook_url="https://other.example.com/wh",
                idempotency_key="k",
            )
        assert exc_info.value.idempotency_key == "k"
