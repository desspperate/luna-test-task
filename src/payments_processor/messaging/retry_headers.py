from collections.abc import Mapping
from typing import Any, cast

from payments_processor.constants import PaymentsConstants


def get_retry_count(headers: Mapping[str, Any] | None) -> int:
    if not headers:
        return 0

    explicit = headers.get(PaymentsConstants.RETRY_COUNT_HEADER)
    if explicit is not None:
        try:
            return int(cast(int | str, explicit))
        except (TypeError, ValueError):
            return 0

    x_death = headers.get("x-death")
    if isinstance(x_death, list) and len(x_death) > 0:
        first = x_death[0]
        if isinstance(first, dict):
            count = first.get("count")
            if isinstance(count, int):
                return count
    return 0


def build_retry_headers(next_count: int, reason: str) -> dict[str, Any]:
    return {
        PaymentsConstants.RETRY_COUNT_HEADER: next_count,
        PaymentsConstants.RETRY_REASON_HEADER: reason,
    }


def build_dlq_headers(retry_count: int, reason: str) -> dict[str, Any]:
    return {
        PaymentsConstants.RETRY_COUNT_HEADER: retry_count,
        PaymentsConstants.DLQ_REASON_HEADER: reason,
    }
