import time
from uuid import UUID

from payments_processor.utils import uuid7


class TestUuid7:
    def test_returns_version_7_uuid(self) -> None:
        value = uuid7()
        assert isinstance(value, UUID)
        assert value.version == 7

    def test_orders_monotonically_in_burst(self) -> None:
        """UUIDv7 contains a millisecond timestamp + monotonic counter, so a
        rapid burst of IDs must remain sortable."""
        batch = [uuid7() for _ in range(256)]
        assert batch == sorted(batch)

    def test_later_calls_produce_larger_values(self) -> None:
        a = uuid7()
        time.sleep(0.002)
        b = uuid7()
        assert a < b

    def test_encoded_timestamp_tracks_wall_clock(self) -> None:
        """The first 48 bits should encode unix-ms close to time.time()."""
        before_ms = int(time.time() * 1000)
        value = uuid7()
        after_ms = int(time.time() * 1000)

        ts_ms = value.int >> 80
        assert before_ms - 1 <= ts_ms <= after_ms + 1

    def test_unique_across_many_calls(self) -> None:
        ids = {uuid7() for _ in range(10_000)}
        assert len(ids) == 10_000
