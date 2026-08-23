"""Durability and fail-closed tests for the supervised SHADOW event loop."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from src.engines.contracts import SetupAction
from src.engines.meta import MetaDecision
from src.execution.shadow_loop import (
    DurableShadowQueue,
    ShadowEventLoop,
    ShadowHealthPublisher,
    ShadowIterationResult,
    ShadowLoopConfig,
    ShadowQueueStatus,
    ShadowWork,
)
from src.execution.shadow_runtime import ShadowAuditError, ShadowRuntime

NOW = datetime(2026, 8, 23, 18, tzinfo=UTC)


def _work(observation_id: str = "observation-1") -> ShadowWork:
    return ShadowWork(
        observation_id=observation_id,
        meta=MetaDecision(
            action=SetupAction.WAIT,
            decision_timestamp_utc=NOW,
            selected_engine_id=None,
            selected_setup=None,
            allocated_notional=0.0,
            rankings=(),
            reason_codes=("NO_EDGE",),
        ),
        proposals=(),
        equity=100_000.0,
    )


class _Journal:
    def __init__(self) -> None:
        self.ids: set[str] = set()

    def find(self, observation_id: str) -> object | None:
        return object() if observation_id in self.ids else None


class _Runtime:
    def __init__(self, *, failures: int = 0) -> None:
        self.context = SimpleNamespace(session_id="shadow-session")
        self.journal = _Journal()
        self.risk_engine = SimpleNamespace(kill_switch_active=False)
        self.failures = failures
        self.holds = 0

    def observe(self, _meta: object, *, observation_id: str, **_kwargs: object) -> None:
        if observation_id in self.journal.ids:
            raise ShadowAuditError("duplicate")
        if self.failures:
            self.failures -= 1
            raise RuntimeError("loader downstream failed")
        self.journal.ids.add(observation_id)

    def activate_safety_hold(self, *, observation_id: str, **_kwargs: object) -> None:
        self.journal.ids.add(observation_id)
        self.risk_engine.kill_switch_active = True
        self.holds += 1


def _runtime(fake: _Runtime) -> ShadowRuntime:
    return cast(ShadowRuntime, cast(object, fake))


def test_queue_is_idempotent_and_acknowledges_only_claimed_work(tmp_path: Path) -> None:
    queue = DurableShadowQueue(tmp_path / "shadow.sqlite3")
    assert queue.enqueue(item_id="one", payload_uri="file:///one", available_at_utc=NOW)
    assert not queue.enqueue(item_id="one", payload_uri="file:///one", available_at_utc=NOW)
    with pytest.raises(ValueError, match="another payload"):
        queue.enqueue(item_id="one", payload_uri="file:///two", available_at_utc=NOW)

    item = queue.claim(now_utc=NOW, lease_seconds=30)
    assert item is not None and item.attempts == 1
    assert queue.claim(now_utc=NOW, lease_seconds=30) is None
    queue.acknowledge("one", completed_at_utc=NOW)
    assert queue.get("one").status == ShadowQueueStatus.DONE  # type: ignore[union-attr]


def test_expired_lease_is_reclaimed_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "shadow.sqlite3"
    queue = DurableShadowQueue(path)
    queue.enqueue(item_id="one", payload_uri="file:///one", available_at_utc=NOW)
    assert queue.claim(now_utc=NOW, lease_seconds=30) is not None

    reopened = DurableShadowQueue(path)
    reclaimed = reopened.claim(now_utc=NOW + timedelta(seconds=30), lease_seconds=30)
    assert reclaimed is not None
    assert reclaimed.item_id == "one" and reclaimed.attempts == 2


def test_retry_backoff_then_dead_letters(tmp_path: Path) -> None:
    queue = DurableShadowQueue(tmp_path / "shadow.sqlite3")
    queue.enqueue(item_id="one", payload_uri="file:///one", available_at_utc=NOW)
    assert queue.claim(now_utc=NOW, lease_seconds=30) is not None
    status = queue.retry_or_dead_letter(
        "one",
        error="first",
        failed_at_utc=NOW,
        retry_at_utc=NOW + timedelta(seconds=2),
        maximum_attempts=2,
    )
    assert status == ShadowQueueStatus.PENDING
    assert queue.claim(now_utc=NOW + timedelta(seconds=1), lease_seconds=30) is None
    assert queue.claim(now_utc=NOW + timedelta(seconds=2), lease_seconds=30) is not None
    status = queue.retry_or_dead_letter(
        "one",
        error="second",
        failed_at_utc=NOW + timedelta(seconds=2),
        retry_at_utc=NOW + timedelta(seconds=6),
        maximum_attempts=2,
    )
    assert status == ShadowQueueStatus.DEAD
    assert queue.snapshot()["dead"] == 1


def test_loop_processes_work_and_publishes_health(tmp_path: Path) -> None:
    queue = DurableShadowQueue(tmp_path / "shadow.sqlite3")
    queue.enqueue(item_id="one", payload_uri="file:///one", available_at_utc=NOW)
    fake = _Runtime()
    health = ShadowHealthPublisher(tmp_path / "health.json")
    loop = ShadowEventLoop(
        queue=queue,
        runtime=_runtime(fake),
        work_loader=lambda _uri: _work(),
        health_publisher=health,
        now_fn=lambda: NOW,
    )

    assert loop.run_once() == ShadowIterationResult.PROCESSED
    assert loop.run_once() == ShadowIterationResult.IDLE
    assert '"done": 1' in health.path.read_text(encoding="utf-8")
    assert "greenfield_shadow_done 1" in health.metrics_path.read_text(encoding="utf-8")


def test_duplicate_audit_is_recovered_idempotently(tmp_path: Path) -> None:
    queue = DurableShadowQueue(tmp_path / "shadow.sqlite3")
    queue.enqueue(item_id="one", payload_uri="file:///one", available_at_utc=NOW)
    fake = _Runtime()
    fake.journal.ids.add("observation-1")
    loop = ShadowEventLoop(
        queue=queue,
        runtime=_runtime(fake),
        work_loader=lambda _uri: _work(),
        now_fn=lambda: NOW,
    )

    assert loop.run_once() == ShadowIterationResult.IDEMPOTENT_RECOVERY
    assert queue.snapshot()["done"] == 1


def test_consecutive_failures_engage_one_safety_hold(tmp_path: Path) -> None:
    queue = DurableShadowQueue(tmp_path / "shadow.sqlite3")
    fake = _Runtime(failures=3)
    config = ShadowLoopConfig(maximum_attempts=1, maximum_consecutive_failures=2)
    for number in range(3):
        queue.enqueue(
            item_id=f"item-{number}",
            payload_uri=f"file:///{number}",
            available_at_utc=NOW,
        )
    loop = ShadowEventLoop(
        queue=queue,
        runtime=_runtime(fake),
        work_loader=lambda uri: _work(uri),
        config=config,
        now_fn=lambda: NOW,
    )

    assert loop.run_once() == ShadowIterationResult.DEAD_LETTERED
    assert loop.run_once() == ShadowIterationResult.DEAD_LETTERED
    assert loop.run_once() == ShadowIterationResult.DEAD_LETTERED
    assert fake.holds == 1
    assert fake.risk_engine.kill_switch_active
    assert queue.snapshot()["consecutive_failures"] == 3


def test_invalid_loop_inputs_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        ShadowLoopConfig(lease_seconds=0)
    with pytest.raises(ValueError, match="positive"):
        _work().__class__(
            observation_id="x", meta=_work().meta, proposals=(), equity=0
        )
    queue = DurableShadowQueue(tmp_path / "shadow.sqlite3")
    with pytest.raises(ValueError, match="timezone-aware"):
        queue.enqueue(
            item_id="one",
            payload_uri="file:///one",
            available_at_utc=datetime(2026, 8, 23),
        )
