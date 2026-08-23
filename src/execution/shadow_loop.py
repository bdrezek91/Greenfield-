"""Durable SQLite work queue and supervised event loop for SHADOW decisions."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from src.engines.meta import MetaDecision
from src.execution.shadow_runtime import ShadowAuditError, ShadowRuntime
from src.risk.portfolio_engine import PortfolioEntryProposal


class ShadowQueueStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    DEAD = "DEAD"


@dataclass(frozen=True, slots=True)
class ShadowQueueItem:
    item_id: str
    payload_uri: str
    status: ShadowQueueStatus
    attempts: int
    available_at_utc: datetime
    lease_until_utc: datetime | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class ShadowWork:
    observation_id: str
    meta: MetaDecision
    proposals: tuple[PortfolioEntryProposal, ...]
    equity: float

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise ValueError("shadow work requires an observation id")
        if not math.isfinite(self.equity) or self.equity <= 0:
            raise ValueError("shadow work equity must be finite and positive")


@dataclass(frozen=True, slots=True)
class ShadowLoopConfig:
    lease_seconds: float = 60.0
    poll_interval_seconds: float = 1.0
    maximum_attempts: int = 5
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 300.0
    maximum_consecutive_failures: int = 3

    def __post_init__(self) -> None:
        durations = (
            self.lease_seconds,
            self.poll_interval_seconds,
            self.retry_base_seconds,
            self.retry_max_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in durations):
            raise ValueError("shadow loop durations must be finite and positive")
        if self.maximum_attempts < 1 or self.maximum_consecutive_failures < 1:
            raise ValueError("shadow loop attempt and failure limits must be positive")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("shadow retry maximum cannot be below its base")


class ShadowIterationResult(StrEnum):
    IDLE = "IDLE"
    PROCESSED = "PROCESSED"
    IDEMPOTENT_RECOVERY = "IDEMPOTENT_RECOVERY"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    DEAD_LETTERED = "DEAD_LETTERED"


class ShadowLoopFatalError(RuntimeError):
    """Raised when the loop cannot persist or audit its own safety hold."""


class DurableShadowQueue:
    """Lease-based, crash-recoverable, idempotent SQLite queue."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS shadow_queue (
                    item_id TEXT PRIMARY KEY,
                    payload_uri TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    available_at_utc TEXT NOT NULL,
                    lease_until_utc TEXT,
                    last_error TEXT,
                    created_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_shadow_queue_claim
                ON shadow_queue(status, available_at_utc, lease_until_utc, created_at_utc);
                CREATE TABLE IF NOT EXISTS shadow_loop_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    status TEXT NOT NULL,
                    consecutive_failures INTEGER NOT NULL,
                    total_processed INTEGER NOT NULL,
                    total_failures INTEGER NOT NULL,
                    heartbeat_at_utc TEXT,
                    last_error TEXT
                );
                INSERT OR IGNORE INTO shadow_loop_state VALUES
                    (1, 'STARTING', 0, 0, 0, NULL, NULL);
                """
            )

    def enqueue(
        self,
        *,
        item_id: str,
        payload_uri: str,
        available_at_utc: datetime,
    ) -> bool:
        if not item_id.strip() or not payload_uri.strip():
            raise ValueError("shadow queue item and payload URI must be non-empty")
        available = _iso(available_at_utc, "queue availability timestamp")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_uri FROM shadow_queue WHERE item_id = ?", (item_id,)
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != payload_uri:
                    raise ValueError("shadow queue id already belongs to another payload")
                connection.commit()
                return False
            connection.execute(
                """
                INSERT INTO shadow_queue (
                    item_id, payload_uri, status, attempts, available_at_utc,
                    lease_until_utc, last_error, created_at_utc, completed_at_utc
                ) VALUES (?, ?, ?, 0, ?, NULL, NULL, ?, NULL)
                """,
                (
                    item_id,
                    payload_uri,
                    ShadowQueueStatus.PENDING.value,
                    available,
                    available,
                ),
            )
            connection.commit()
            return True

    def claim(self, *, now_utc: datetime, lease_seconds: float) -> ShadowQueueItem | None:
        now = _utc(now_utc, "queue claim timestamp")
        if not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("queue lease must be finite and positive")
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT item_id FROM shadow_queue
                WHERE
                    (status = ? AND available_at_utc <= ?)
                    OR (status = ? AND lease_until_utc <= ?)
                ORDER BY available_at_utc, created_at_utc, item_id
                LIMIT 1
                """,
                (
                    ShadowQueueStatus.PENDING.value,
                    now.isoformat(),
                    ShadowQueueStatus.PROCESSING.value,
                    now.isoformat(),
                ),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            item_id = str(row[0])
            connection.execute(
                """
                UPDATE shadow_queue
                SET status = ?, attempts = attempts + 1, lease_until_utc = ?
                WHERE item_id = ?
                """,
                (
                    ShadowQueueStatus.PROCESSING.value,
                    lease_until.isoformat(),
                    item_id,
                ),
            )
            claimed = self._fetch(connection, item_id)
            connection.commit()
            return claimed

    def acknowledge(self, item_id: str, *, completed_at_utc: datetime) -> None:
        completed = _iso(completed_at_utc, "queue completion timestamp")
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE shadow_queue
                SET status = ?, lease_until_utc = NULL, completed_at_utc = ?, last_error = NULL
                WHERE item_id = ? AND status = ?
                """,
                (
                    ShadowQueueStatus.DONE.value,
                    completed,
                    item_id,
                    ShadowQueueStatus.PROCESSING.value,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("only a processing shadow item can be acknowledged")

    def retry_or_dead_letter(
        self,
        item_id: str,
        *,
        error: str,
        failed_at_utc: datetime,
        retry_at_utc: datetime,
        maximum_attempts: int,
    ) -> ShadowQueueStatus:
        if not error.strip() or maximum_attempts < 1:
            raise ValueError("shadow retry requires error and attempt limit")
        failed_at = _iso(failed_at_utc, "queue failure timestamp")
        retry_at = _iso(retry_at_utc, "queue retry timestamp")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT attempts, status FROM shadow_queue WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            if row is None or row[1] != ShadowQueueStatus.PROCESSING.value:
                raise ValueError("only a processing shadow item can be retried")
            status = (
                ShadowQueueStatus.DEAD
                if int(row[0]) >= maximum_attempts
                else ShadowQueueStatus.PENDING
            )
            connection.execute(
                """
                UPDATE shadow_queue
                SET status = ?, available_at_utc = ?, lease_until_utc = NULL,
                    last_error = ?, completed_at_utc = ?
                WHERE item_id = ?
                """,
                (
                    status.value,
                    retry_at,
                    error,
                    failed_at if status == ShadowQueueStatus.DEAD else None,
                    item_id,
                ),
            )
            connection.commit()
            return status

    def record_success(self, *, now_utc: datetime) -> None:
        self._update_loop_state(now_utc=now_utc, success=True, error=None)

    def record_failure(self, *, now_utc: datetime, error: str) -> int:
        if not error.strip():
            raise ValueError("shadow loop failure requires an error")
        return self._update_loop_state(now_utc=now_utc, success=False, error=error)

    def record_heartbeat(self, *, now_utc: datetime, status: str = "IDLE") -> None:
        now = _iso(now_utc, "shadow loop heartbeat")
        with self._connect() as connection:
            connection.execute(
                "UPDATE shadow_loop_state SET status = ?, heartbeat_at_utc = ? WHERE singleton = 1",
                (status, now),
            )

    def snapshot(self) -> dict[str, object]:
        with self._connect() as connection:
            counts = {
                str(status): int(count)
                for status, count in connection.execute(
                    "SELECT status, COUNT(*) FROM shadow_queue GROUP BY status"
                ).fetchall()
            }
            state = connection.execute(
                """
                SELECT status, consecutive_failures, total_processed,
                       total_failures, heartbeat_at_utc, last_error
                FROM shadow_loop_state WHERE singleton = 1
                """
            ).fetchone()
        assert state is not None
        return {
            "schema_version": 1,
            "status": str(state[0]),
            "consecutive_failures": int(state[1]),
            "total_processed": int(state[2]),
            "total_failures": int(state[3]),
            "heartbeat_at_utc": state[4],
            "last_error": state[5],
            "pending": counts.get(ShadowQueueStatus.PENDING.value, 0),
            "processing": counts.get(ShadowQueueStatus.PROCESSING.value, 0),
            "done": counts.get(ShadowQueueStatus.DONE.value, 0),
            "dead": counts.get(ShadowQueueStatus.DEAD.value, 0),
        }

    def get(self, item_id: str) -> ShadowQueueItem | None:
        with self._connect() as connection:
            return self._fetch(connection, item_id)

    def _update_loop_state(
        self, *, now_utc: datetime, success: bool, error: str | None
    ) -> int:
        now = _iso(now_utc, "shadow loop result timestamp")
        with self._connect() as connection:
            if success:
                connection.execute(
                    """
                    UPDATE shadow_loop_state
                    SET status = 'RUNNING', consecutive_failures = 0,
                        total_processed = total_processed + 1,
                        heartbeat_at_utc = ?, last_error = NULL
                    WHERE singleton = 1
                    """,
                    (now,),
                )
            else:
                connection.execute(
                    """
                    UPDATE shadow_loop_state
                    SET status = 'DEGRADED',
                        consecutive_failures = consecutive_failures + 1,
                        total_failures = total_failures + 1,
                        heartbeat_at_utc = ?, last_error = ?
                    WHERE singleton = 1
                    """,
                    (now, error),
                )
            row = connection.execute(
                "SELECT consecutive_failures FROM shadow_loop_state WHERE singleton = 1"
            ).fetchone()
        assert row is not None
        return int(row[0])

    def _fetch(
        self, connection: sqlite3.Connection, item_id: str
    ) -> ShadowQueueItem | None:
        row = connection.execute(
            """
            SELECT item_id, payload_uri, status, attempts, available_at_utc,
                   lease_until_utc, last_error
            FROM shadow_queue WHERE item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return ShadowQueueItem(
            item_id=str(row[0]),
            payload_uri=str(row[1]),
            status=ShadowQueueStatus(str(row[2])),
            attempts=int(row[3]),
            available_at_utc=_parse(str(row[4])),
            lease_until_utc=_parse(str(row[5])) if row[5] is not None else None,
            last_error=str(row[6]) if row[6] is not None else None,
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class ShadowHealthPublisher:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.metrics_path = self.path.with_suffix(".prom")

    def publish(self, snapshot: dict[str, object]) -> None:
        _atomic_write(self.path, json.dumps(snapshot, sort_keys=True, indent=2) + "\n")
        numeric = (
            "consecutive_failures",
            "total_processed",
            "total_failures",
            "pending",
            "processing",
            "done",
            "dead",
        )
        lines: list[str] = []
        for name in numeric:
            value = snapshot[name]
            if not isinstance(value, int):
                raise ValueError(f"shadow health metric {name} must be an integer")
            lines.extend(
                (
                    f"# TYPE greenfield_shadow_{name} gauge",
                    f"greenfield_shadow_{name} {value}",
                )
            )
        _atomic_write(self.metrics_path, "\n".join(lines) + "\n")


class ShadowEventLoop:
    def __init__(
        self,
        *,
        queue: DurableShadowQueue,
        runtime: ShadowRuntime,
        work_loader: Callable[[str], ShadowWork],
        config: ShadowLoopConfig | None = None,
        health_publisher: ShadowHealthPublisher | None = None,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.queue = queue
        self.runtime = runtime
        self.work_loader = work_loader
        self.config = config or ShadowLoopConfig()
        self.health_publisher = health_publisher
        self._now_fn = now_fn
        self._sleep_fn = sleep_fn

    def run_once(self) -> ShadowIterationResult:
        now = _utc(self._now_fn(), "shadow loop clock")
        item = self.queue.claim(now_utc=now, lease_seconds=self.config.lease_seconds)
        if item is None:
            self.queue.record_heartbeat(now_utc=now)
            self._publish()
            return ShadowIterationResult.IDLE
        work: ShadowWork | None = None
        try:
            work = self.work_loader(item.payload_uri)
            self.runtime.observe(
                work.meta,
                observation_id=work.observation_id,
                proposals=work.proposals,
                equity=work.equity,
            )
            self.queue.acknowledge(item.item_id, completed_at_utc=now)
            self.queue.record_success(now_utc=now)
            result = ShadowIterationResult.PROCESSED
        except ShadowAuditError as exc:
            if work is not None and self.runtime.journal.find(work.observation_id) is not None:
                self.queue.acknowledge(item.item_id, completed_at_utc=now)
                self.queue.record_success(now_utc=now)
                result = ShadowIterationResult.IDEMPOTENT_RECOVERY
            else:
                result = self._handle_failure(item, now=now, error=repr(exc))
        except Exception as exc:  # noqa: BLE001 - malformed work is retry/dead-letter input
            result = self._handle_failure(item, now=now, error=repr(exc))
        self._publish()
        return result

    def run_until(self, stop_requested: Callable[[], bool]) -> None:
        while not stop_requested():
            result = self.run_once()
            if result in {
                ShadowIterationResult.IDLE,
                ShadowIterationResult.RETRY_SCHEDULED,
            }:
                self._sleep_fn(self.config.poll_interval_seconds)

    def _handle_failure(
        self, item: ShadowQueueItem, *, now: datetime, error: str
    ) -> ShadowIterationResult:
        delay = min(
            self.config.retry_base_seconds * (2 ** max(0, item.attempts - 1)),
            self.config.retry_max_seconds,
        )
        status = self.queue.retry_or_dead_letter(
            item.item_id,
            error=error,
            failed_at_utc=now,
            retry_at_utc=now + timedelta(seconds=delay),
            maximum_attempts=self.config.maximum_attempts,
        )
        consecutive = self.queue.record_failure(now_utc=now, error=error)
        if (
            consecutive >= self.config.maximum_consecutive_failures
            and not self.runtime.risk_engine.kill_switch_active
        ):
            hold_id = (
                f"{self.runtime.context.session_id}:loop-safety-hold:"
                f"{item.item_id}:{item.attempts}"
            )
            try:
                if self.runtime.journal.find(hold_id) is None:
                    self.runtime.activate_safety_hold(
                        observation_id=hold_id,
                        reason=f"shadow event loop failure threshold: {error}",
                        activated_at_utc=now,
                    )
            except Exception as exc:  # noqa: BLE001 - safety persistence is fatal
                raise ShadowLoopFatalError(
                    "failed to persist shadow event-loop safety hold"
                ) from exc
        return (
            ShadowIterationResult.DEAD_LETTERED
            if status == ShadowQueueStatus.DEAD
            else ShadowIterationResult.RETRY_SCHEDULED
        )

    def _publish(self) -> None:
        if self.health_publisher is not None:
            self.health_publisher.publish(self.queue.snapshot())


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime, name: str) -> str:
    return _utc(value, name).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
