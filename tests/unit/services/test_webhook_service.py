import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
import respx
from freezegun import freeze_time
from pydantic import SecretStr

from payments_processor.configs import WebhookConfig
from payments_processor.constants import PaymentsConstants
from payments_processor.enums import CurrencyEnum, PaymentStatusEnum
from payments_processor.errors import WebhookSendError, WebhookUrlNotAllowedError
from payments_processor.services import WebhookService
from payments_processor.utils import SSRFGuard


SECRET_VALUE = "a-very-secret-value-32-chars-long!"


def _config(timeout: float = 5.0) -> WebhookConfig:
    return WebhookConfig(
        WEBHOOK_SECRET=SecretStr(SECRET_VALUE),
        WEBHOOK_TIMEOUT_SECONDS=timeout,
        WEBHOOK_ALLOW_PRIVATE_HOSTS=True,
    )


@pytest_asyncio.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def service(http_client: httpx.AsyncClient) -> WebhookService:
    return WebhookService(
        http_client=http_client,
        webhook_config=_config(),
        ssrf_guard=SSRFGuard(allow_private_hosts=True),
    )


class TestSendSuccess:
    @respx.mock
    async def test_sends_post_to_webhook_url(self, service, make_payment) -> None:
        payment = make_payment(webhook_url="https://example.com/wh")
        route = respx.post("https://example.com/wh").mock(
            return_value=httpx.Response(200),
        )

        await service.send(payment=payment)

        assert route.called

    @respx.mock
    async def test_body_contains_full_payment_payload(
        self, service, make_payment,
    ) -> None:
        payment = make_payment(
            amount=Decimal("123.45"),
            currency=CurrencyEnum.USD,
            status=PaymentStatusEnum.SUCCEEDED,
            meta={"order": "abc"},
            processed_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        )
        route = respx.post(payment.webhook_url).mock(return_value=httpx.Response(200))

        await service.send(payment=payment)

        body = json.loads(route.calls.last.request.content)
        assert body["payment_id"] == str(payment.id)
        assert body["status"] == "SUCCEEDED"
        assert Decimal(body["amount"]) == Decimal("123.45")
        assert body["currency"] == "USD"
        assert body["metadata"] == {"order": "abc"}
        assert body["processed_at"] == "2026-01-01T12:00:00Z"
        UUID(body["event_id"])  # parses as a real UUID

    @respx.mock
    async def test_event_id_is_uuid_v7(self, service, make_payment) -> None:
        payment = make_payment()
        route = respx.post(payment.webhook_url).mock(return_value=httpx.Response(200))

        await service.send(payment=payment)
        body = json.loads(route.calls.last.request.content)
        assert UUID(body["event_id"]).version == 7

    @respx.mock
    async def test_signature_is_hmac_sha256_of_ts_and_body(
        self, service, make_payment,
    ) -> None:
        payment = make_payment()
        route = respx.post(payment.webhook_url).mock(return_value=httpx.Response(200))

        await service.send(payment=payment)
        req = route.calls.last.request

        ts = req.headers[PaymentsConstants.WEBHOOK_TIMESTAMP_HEADER]
        sig_header = req.headers[PaymentsConstants.WEBHOOK_SIGNATURE_HEADER]
        assert sig_header.startswith("sha256=")

        expected = hmac.new(
            key=SECRET_VALUE.encode(),
            msg=f"{ts}.".encode() + req.content,
            digestmod=hashlib.sha256,
        ).hexdigest()
        assert sig_header.removeprefix("sha256=") == expected

    @respx.mock
    async def test_timestamp_header_is_current_unix_seconds(
        self, service, make_payment,
    ) -> None:
        with freeze_time("2026-06-01T00:00:00Z"):
            payment = make_payment()
            route = respx.post(payment.webhook_url).mock(
                return_value=httpx.Response(200),
            )
            await service.send(payment=payment)

        ts = route.calls.last.request.headers[PaymentsConstants.WEBHOOK_TIMESTAMP_HEADER]
        expected = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
        assert int(ts) == expected

    @respx.mock
    async def test_event_metadata_headers_set(self, service, make_payment) -> None:
        payment = make_payment()
        route = respx.post(payment.webhook_url).mock(return_value=httpx.Response(200))
        await service.send(payment=payment)

        req = route.calls.last.request
        assert req.headers["Content-Type"] == "application/json"
        assert req.headers["User-Agent"] == PaymentsConstants.WEBHOOK_USER_AGENT
        assert req.headers[PaymentsConstants.WEBHOOK_EVENT_TYPE_HEADER] == \
            PaymentsConstants.PAYMENT_PROCESSED_EVENT_TYPE
        assert UUID(req.headers[PaymentsConstants.WEBHOOK_ID_HEADER]).version == 7

    @respx.mock
    async def test_uses_configured_timeout(self, http_client, make_payment) -> None:
        service = WebhookService(
            http_client=http_client,
            webhook_config=_config(timeout=2.0),
            ssrf_guard=SSRFGuard(allow_private_hosts=True),
        )
        payment = make_payment()
        route = respx.post(payment.webhook_url).mock(return_value=httpx.Response(200))

        await service.send(payment=payment)

        # respx exposes the extension dict where timeout is stored
        timeout = route.calls.last.request.extensions["timeout"]
        assert timeout["connect"] == 2.0
        assert timeout["read"] == 2.0


class TestSendFailures:
    @respx.mock
    @pytest.mark.parametrize(
        ("status_code", "marker"),
        [(400, "client error"), (404, "client error"), (500, "server error"), (503, "server error")],
    )
    async def test_non_2xx_raises_with_status_code(
        self, service, make_payment, status_code: int, marker: str,
    ) -> None:
        _ = marker
        payment = make_payment()
        respx.post(payment.webhook_url).mock(return_value=httpx.Response(status_code))

        with pytest.raises(WebhookSendError) as exc_info:
            await service.send(payment=payment)
        assert exc_info.value.reason == "non_2xx_response"
        assert exc_info.value.status_code == status_code
        assert exc_info.value.payment_id == payment.id

    @respx.mock
    @pytest.mark.parametrize(
        ("exception", "expected_reason"),
        [
            (httpx.ConnectError("conn refused"), "ConnectError"),
            (httpx.ReadTimeout("slow"), "ReadTimeout"),
            (httpx.ConnectTimeout("slow conn"), "ConnectTimeout"),
        ],
    )
    async def test_transport_errors_surface_as_send_error(
        self, service, make_payment, exception: Exception, expected_reason: str,
    ) -> None:
        payment = make_payment()
        respx.post(payment.webhook_url).mock(side_effect=exception)

        with pytest.raises(WebhookSendError) as exc_info:
            await service.send(payment=payment)
        assert exc_info.value.reason == expected_reason
        assert exc_info.value.status_code is None

    @respx.mock
    async def test_2xx_other_than_200_is_accepted(self, service, make_payment) -> None:
        payment = make_payment()
        respx.post(payment.webhook_url).mock(return_value=httpx.Response(204))

        await service.send(payment=payment)  # must not raise


class TestSSRFGuardOrdering:
    @respx.mock
    async def test_guard_runs_before_http_call(
        self, http_client, make_payment,
    ) -> None:
        class BlockingGuard:
            async def validate_url(self, url: str) -> None:
                raise WebhookUrlNotAllowedError(url=url, reason="address_disallowed")

        service = WebhookService(
            http_client=http_client,
            webhook_config=_config(),
            ssrf_guard=BlockingGuard(),
        )
        payment = make_payment(webhook_url="https://blocked.example.com/wh")
        route = respx.post(payment.webhook_url).mock(return_value=httpx.Response(200))

        with pytest.raises(WebhookUrlNotAllowedError):
            await service.send(payment=payment)

        assert not route.called

    @respx.mock
    async def test_guard_receives_actual_webhook_url(
        self, http_client, make_payment,
    ) -> None:
        captured: list[str] = []

        class RecordingGuard:
            async def validate_url(self, url: str) -> None:
                captured.append(url)

        service = WebhookService(
            http_client=http_client,
            webhook_config=_config(),
            ssrf_guard=RecordingGuard(),
        )
        payment = make_payment(webhook_url="https://target.example.com/path")
        respx.post(payment.webhook_url).mock(return_value=httpx.Response(200))

        await service.send(payment=payment)

        assert captured == ["https://target.example.com/path"]
