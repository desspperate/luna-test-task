from typing import Any

import pytest

from payments_processor.constants import PaymentsConstants
from payments_processor.messaging import build_dlq_headers, build_retry_headers, get_retry_count

COUNT_HEADER = PaymentsConstants.RETRY_COUNT_HEADER
REASON_HEADER = PaymentsConstants.RETRY_REASON_HEADER
DLQ_REASON_HEADER = PaymentsConstants.DLQ_REASON_HEADER


class TestGetRetryCount:
    @pytest.mark.parametrize("headers", [None, {}])
    def test_returns_zero_when_no_headers(self, headers: dict[str, Any] | None) -> None:
        assert get_retry_count(headers=headers) == 0

    def test_returns_explicit_int_value(self) -> None:
        assert get_retry_count(headers={COUNT_HEADER: 3}) == 3

    def test_parses_numeric_string(self) -> None:
        assert get_retry_count(headers={COUNT_HEADER: "5"}) == 5

    @pytest.mark.parametrize(
        "bad_value",
        ["abc", "", "1.5", "-not a number"],
    )
    def test_falls_back_to_zero_for_unparseable_explicit(self, bad_value: str) -> None:
        assert get_retry_count(headers={COUNT_HEADER: bad_value}) == 0

    def test_falls_back_to_x_death_count_when_explicit_missing(self) -> None:
        headers = {"x-death": [{"count": 7, "reason": "expired"}]}
        assert get_retry_count(headers=headers) == 7

    def test_explicit_header_takes_priority_over_x_death(self) -> None:
        headers = {COUNT_HEADER: 2, "x-death": [{"count": 99}]}
        assert get_retry_count(headers=headers) == 2

    @pytest.mark.parametrize(
        "headers",
        [
            {"x-death": []},
            {"x-death": "not a list"},
            {"x-death": [{"reason": "x"}]},  # missing count
            {"x-death": [{"count": "not an int"}]},
        ],
    )
    def test_returns_zero_for_malformed_x_death(self, headers: dict[str, Any]) -> None:
        assert get_retry_count(headers=headers) == 0


class TestBuildRetryHeaders:
    def test_includes_count_and_reason(self) -> None:
        assert build_retry_headers(next_count=2, reason="timeout") == {
            COUNT_HEADER: 2,
            REASON_HEADER: "timeout",
        }

    def test_round_trips_through_get_retry_count(self) -> None:
        headers = build_retry_headers(next_count=4, reason="x")
        assert get_retry_count(headers=headers) == 4


class TestBuildDlqHeaders:
    def test_includes_count_and_dlq_reason(self) -> None:
        assert build_dlq_headers(retry_count=3, reason="non_2xx_response") == {
            COUNT_HEADER: 3,
            DLQ_REASON_HEADER: "non_2xx_response",
        }

    def test_does_not_set_retry_reason(self) -> None:
        """DLQ headers use a separate reason key from retry headers."""
        headers = build_dlq_headers(retry_count=3, reason="exhausted")
        assert REASON_HEADER not in headers
