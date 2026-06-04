from typing import Any
from uuid import uuid4

import pytest

from payments_processor.configs import ConsumerConfig
from payments_processor.enums import ProcessingOutcomeEnum
from payments_processor.services import ProcessingService


def _config(**overrides: Any) -> ConsumerConfig:  # noqa: ANN401
    defaults: dict[str, Any] = {
        "CONSUMER_PREFETCH_COUNT": 10,
        "CONSUMER_MAX_RETRIES": 3,
        "CONSUMER_PROCESS_MIN_SECONDS": 2.0,
        "CONSUMER_PROCESS_MAX_SECONDS": 5.0,
        "CONSUMER_SUCCESS_PROBABILITY": 0.9,
    }
    defaults.update(overrides)
    return ConsumerConfig(**defaults)


class ScriptedRng:
    """Deterministic stand-in for SystemRandom that records its calls."""

    def __init__(self, *, uniform: float, random: float) -> None:
        self._uniform = uniform
        self._random = random
        self.uniform_calls: list[tuple[float, float]] = []
        self.random_calls: int = 0

    def uniform(self, a: float, b: float) -> float:
        self.uniform_calls.append((a, b))
        return self._uniform

    def random(self) -> float:
        self.random_calls += 1
        return self._random


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:  # pyright: ignore[reportUnusedFunction]
    """Replace asyncio.sleep with a no-op that records the requested delay so
    tests can assert on it without waiting."""
    recorded: list[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(
        "payments_processor.services.processing_service.asyncio.sleep",
        fake_sleep,
    )
    return recorded


def _build_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: ConsumerConfig | None = None,
    rng: ScriptedRng | None = None,
) -> tuple[ProcessingService, ScriptedRng]:
    cfg = config or _config()
    rng_obj = rng or ScriptedRng(uniform=3.0, random=0.5)
    service = ProcessingService(consumer_config=cfg)
    monkeypatch.setattr(service, "_rng", rng_obj)
    return service, rng_obj


class TestOutcome:
    async def test_random_below_threshold_yields_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        service, _ = _build_service(
            monkeypatch,
            config=_config(CONSUMER_SUCCESS_PROBABILITY=0.9),
            rng=ScriptedRng(uniform=3.0, random=0.5),
        )
        assert await service.process(payment_id=uuid4()) == ProcessingOutcomeEnum.SUCCEEDED

    async def test_random_at_threshold_yields_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`< 0.9` predicate means random == 0.9 is failure, not success."""
        service, _ = _build_service(
            monkeypatch,
            config=_config(CONSUMER_SUCCESS_PROBABILITY=0.9),
            rng=ScriptedRng(uniform=3.0, random=0.9),
        )
        assert await service.process(payment_id=uuid4()) == ProcessingOutcomeEnum.FAILED

    async def test_probability_zero_always_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        service, _ = _build_service(
            monkeypatch,
            config=_config(CONSUMER_SUCCESS_PROBABILITY=0.0),
            rng=ScriptedRng(uniform=3.0, random=0.0),
        )
        assert await service.process(payment_id=uuid4()) == ProcessingOutcomeEnum.FAILED

    async def test_probability_one_always_succeeds(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        service, _ = _build_service(
            monkeypatch,
            config=_config(CONSUMER_SUCCESS_PROBABILITY=1.0),
            rng=ScriptedRng(uniform=3.0, random=0.999999),
        )
        assert await service.process(payment_id=uuid4()) == ProcessingOutcomeEnum.SUCCEEDED


class TestProcessingDelay:
    async def test_uses_configured_min_max_for_uniform_sample(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = _config(
            CONSUMER_PROCESS_MIN_SECONDS=1.5,
            CONSUMER_PROCESS_MAX_SECONDS=4.5,
        )
        service, rng = _build_service(monkeypatch, config=cfg)

        await service.process(payment_id=uuid4())

        assert rng.uniform_calls == [(1.5, 4.5)]

    async def test_sleeps_for_sampled_delay(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _no_real_sleep: list[float],  # noqa: PT019
    ) -> None:
        service, _ = _build_service(
            monkeypatch,
            rng=ScriptedRng(uniform=2.5, random=0.5),
        )
        await service.process(payment_id=uuid4())
        assert _no_real_sleep == [2.5]

    async def test_calls_random_exactly_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        service, rng = _build_service(monkeypatch)
        await service.process(payment_id=uuid4())
        assert rng.random_calls == 1
