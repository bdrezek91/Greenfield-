"""Durable, idempotent evidence journal for experimental Demo scalp scans."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.execution.demo_opportunity_scanner import DemoOpportunityScan


class DemoSignalJournalError(RuntimeError):
    """A journal write conflicts with already-recorded decision evidence."""


@dataclass(frozen=True, slots=True)
class DemoSignalJournalEntry:
    observation_id: str
    observed_at_utc: datetime
    symbol: str
    market_price: float | None
    experimental_action: str
    directional_action: str
    momentum_veto: str
    evidence_json: str
    reason_codes_json: str
    execution_status: str
    execution_detail: str
    trade_id: str | None
    operator_forced: bool

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.symbol.strip():
            raise ValueError("journal entry requires observation and symbol")
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("journal timestamp must be timezone-aware")
        if self.market_price is not None and (
            not math.isfinite(self.market_price) or self.market_price <= 0
        ):
            raise ValueError("journal market price must be positive and finite")

    @classmethod
    def from_scan(
        cls,
        *,
        observation_id: str,
        observed_at_utc: datetime,
        symbol: str,
        market_price: float | None,
        scan: DemoOpportunityScan | None,
        experimental_action: str,
        execution_status: str,
        execution_detail: str,
        trade_id: str | None,
        operator_forced: bool,
    ) -> DemoSignalJournalEntry:
        if observed_at_utc.tzinfo is None:
            raise ValueError("journal timestamp must be timezone-aware")
        evidence = []
        if scan is not None:
            evidence = [
                {
                    "family": item.family.value,
                    "score": item.score,
                    "confidence": item.confidence,
                    "quality": item.quality,
                    "effective_score": item.effective_score,
                    "max_source_timestamp_utc": item.max_source_timestamp_utc.astimezone(
                        UTC
                    ).isoformat(),
                    "component_ids": list(item.component_ids),
                    "rationale": item.rationale,
                }
                for item in scan.evidence
            ]
        return cls(
            observation_id=observation_id,
            observed_at_utc=observed_at_utc.astimezone(UTC),
            symbol=symbol,
            market_price=market_price,
            experimental_action=experimental_action,
            directional_action=scan.decision.action.value if scan else "WAIT",
            momentum_veto=scan.momentum_veto.value if scan else "WAIT",
            evidence_json=json.dumps(evidence, sort_keys=True, separators=(",", ":")),
            reason_codes_json=json.dumps(
                list(scan.decision.reason_codes) if scan else [],
                sort_keys=True,
                separators=(",", ":"),
            ),
            execution_status=execution_status,
            execution_detail=execution_detail,
            trade_id=trade_id,
            operator_forced=operator_forced,
        )


class DemoSignalJournal:
    """Append-only SQLite decision evidence with replay conflict detection."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS demo_signal_journal (
                    observation_id TEXT PRIMARY KEY,
                    observed_at_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    market_price REAL,
                    experimental_action TEXT NOT NULL,
                    directional_action TEXT NOT NULL,
                    momentum_veto TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    reason_codes_json TEXT NOT NULL,
                    execution_status TEXT NOT NULL,
                    execution_detail TEXT NOT NULL,
                    trade_id TEXT,
                    operator_forced INTEGER NOT NULL CHECK (operator_forced IN (0, 1))
                )
                """
            )

    def record(self, entry: DemoSignalJournalEntry) -> None:
        values = _values(entry)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM demo_signal_journal WHERE observation_id = ?",
                (entry.observation_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values:
                    raise DemoSignalJournalError(
                        "observation id conflicts with durable Demo signal evidence"
                    )
                return
            connection.execute(
                "INSERT INTO demo_signal_journal VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )

    def entries(self) -> tuple[DemoSignalJournalEntry, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM demo_signal_journal ORDER BY observed_at_utc, observation_id"
            ).fetchall()
        return tuple(_entry(tuple(row)) for row in rows)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
            connection.commit()
        finally:
            connection.close()


def _values(entry: DemoSignalJournalEntry) -> tuple[object, ...]:
    return (
        entry.observation_id,
        entry.observed_at_utc.astimezone(UTC).isoformat(),
        entry.symbol,
        entry.market_price,
        entry.experimental_action,
        entry.directional_action,
        entry.momentum_veto,
        entry.evidence_json,
        entry.reason_codes_json,
        entry.execution_status,
        entry.execution_detail,
        entry.trade_id,
        int(entry.operator_forced),
    )


def _entry(row: tuple[object, ...]) -> DemoSignalJournalEntry:
    return DemoSignalJournalEntry(
        observation_id=str(row[0]),
        observed_at_utc=datetime.fromisoformat(str(row[1])),
        symbol=str(row[2]),
        market_price=float(str(row[3])) if row[3] is not None else None,
        experimental_action=str(row[4]),
        directional_action=str(row[5]),
        momentum_veto=str(row[6]),
        evidence_json=str(row[7]),
        reason_codes_json=str(row[8]),
        execution_status=str(row[9]),
        execution_detail=str(row[10]),
        trade_id=str(row[11]) if row[11] is not None else None,
        operator_forced=bool(row[12]),
    )
