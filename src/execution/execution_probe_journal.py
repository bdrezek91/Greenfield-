"""Durable PAPER/TCA journal for `PaperExecutionProbeExecutor` evidence.

`src.execution.calibration` already defines `PaperOrderObservation` and
`TopOfBookQuote` - the exact shapes `compute_markout_calibration()` and
`compare_predicted_to_realized()` consume - but as pure, in-memory dataclasses
with no durable store. This module is that store: every execution-probe
order and every quote sampled around its fill is written here so a later,
separate calibration job can load many probe runs across many days, rebuild
the `(PaperOrderObservation, ...)` / `(TopOfBookQuote, ...)` tuples those
functions expect, and feed them in directly.

This journal is intentionally probe-only. It is never read by research
profitability code, and every row carries `probe_mode` (MAKER/TAKER) plus the
`EXECUTION_PROBE` tag baked into the caller's `observation_id`/`candidate_id`
upstream (see `paper_execution_probe.py`) so a forced execution-quality probe
can never be mistaken for a naturally occurring strategy signal.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from src.execution.calibration import PaperOrderObservation, TopOfBookQuote
from src.execution.intent import IntentSide


class ExecutionProbeJournal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS execution_probe_orders (
                    order_id TEXT PRIMARY KEY,
                    probe_trade_id TEXT NOT NULL,
                    probe_mode TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    side TEXT NOT NULL,
                    requested_quantity REAL NOT NULL,
                    decision_timestamp_utc TEXT NOT NULL,
                    submitted_at_utc TEXT NOT NULL,
                    resolved_at_utc TEXT NOT NULL,
                    filled_price REAL NOT NULL,
                    filled_quantity REAL NOT NULL,
                    rejected INTEGER NOT NULL,
                    fee_cost_quote REAL NOT NULL,
                    funding_cost_quote REAL NOT NULL,
                    recorded_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_execution_probe_orders_symbol_venue
                ON execution_probe_orders(symbol, venue);
                CREATE TABLE IF NOT EXISTS execution_probe_quotes (
                    probe_trade_id TEXT NOT NULL,
                    horizon_label TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    venue TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    source_sequence INTEGER NOT NULL,
                    bid_price REAL NOT NULL,
                    ask_price REAL NOT NULL,
                    bid_quantity REAL NOT NULL,
                    ask_quantity REAL NOT NULL,
                    PRIMARY KEY (probe_trade_id, horizon_label)
                );
                CREATE INDEX IF NOT EXISTS idx_execution_probe_quotes_symbol_venue
                ON execution_probe_quotes(symbol, venue, timestamp_utc);
                """
            )

    def record_order_observation(
        self,
        *,
        probe_trade_id: str,
        probe_mode: str,
        request_id: str,
        observation: PaperOrderObservation,
        now_utc: datetime,
    ) -> None:
        if not probe_trade_id.strip() or not probe_mode.strip() or not request_id.strip():
            raise ValueError("execution probe journal order identity is incomplete")
        values = (
            observation.order_id, probe_trade_id, probe_mode, request_id,
            observation.symbol, observation.venue, observation.side.value,
            observation.requested_quantity, _iso(observation.decision_timestamp_utc),
            _iso(observation.submitted_at_utc), _iso(observation.resolved_at_utc),
            observation.filled_price, observation.filled_quantity,
            int(observation.rejected), observation.fee_cost_quote,
            observation.funding_cost_quote, _iso(_utc(now_utc)),
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM execution_probe_orders WHERE order_id = ?",
                (observation.order_id,),
            ).fetchone()
            if existing is not None:
                stored = tuple(existing[key] for key in existing.keys() if key != "recorded_at_utc")
                if stored != values[:-1]:
                    raise ValueError(
                        f"execution probe order_id conflict for {observation.order_id!r}"
                    )
                return
            connection.execute(
                """INSERT INTO execution_probe_orders (
                    order_id, probe_trade_id, probe_mode, request_id, symbol, venue, side,
                    requested_quantity, decision_timestamp_utc, submitted_at_utc,
                    resolved_at_utc, filled_price, filled_quantity, rejected,
                    fee_cost_quote, funding_cost_quote, recorded_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            connection.commit()

    def record_quote(
        self,
        *,
        probe_trade_id: str,
        horizon_label: str,
        quote: TopOfBookQuote,
    ) -> None:
        if not probe_trade_id.strip() or not horizon_label.strip():
            raise ValueError("execution probe journal quote identity is incomplete")
        values = (
            probe_trade_id, horizon_label, quote.symbol, quote.venue,
            _iso(quote.timestamp_utc), quote.source_sequence, quote.bid_price,
            quote.ask_price, quote.bid_quantity, quote.ask_quantity,
        )
        with self._connect() as connection:
            existing = connection.execute(
                """SELECT * FROM execution_probe_quotes
                WHERE probe_trade_id = ? AND horizon_label = ?""",
                (probe_trade_id, horizon_label),
            ).fetchone()
            if existing is not None:
                stored = tuple(existing[key] for key in existing.keys())
                if stored != values:
                    raise ValueError(
                        "execution probe quote identity conflict for "
                        f"{probe_trade_id!r}/{horizon_label!r}"
                    )
                return
            connection.execute(
                """INSERT INTO execution_probe_quotes (
                    probe_trade_id, horizon_label, symbol, venue, timestamp_utc,
                    source_sequence, bid_price, ask_price, bid_quantity, ask_quantity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            connection.commit()

    def load_observations(
        self, *, since_utc: datetime | None = None
    ) -> tuple[PaperOrderObservation, ...]:
        query = "SELECT * FROM execution_probe_orders"
        params: tuple[object, ...] = ()
        if since_utc is not None:
            query += " WHERE decision_timestamp_utc >= ?"
            params = (_iso(_utc(since_utc)),)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(_observation(row) for row in rows)

    def load_quotes(self, *, since_utc: datetime | None = None) -> tuple[TopOfBookQuote, ...]:
        query = "SELECT * FROM execution_probe_quotes"
        params: tuple[object, ...] = ()
        if since_utc is not None:
            query += " WHERE timestamp_utc >= ?"
            params = (_iso(_utc(since_utc)),)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(_quote(row) for row in rows)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
        finally:
            connection.close()


def _observation(row: sqlite3.Row) -> PaperOrderObservation:
    return PaperOrderObservation(
        order_id=str(row["order_id"]),
        symbol=str(row["symbol"]),
        venue=str(row["venue"]),
        side=IntentSide(str(row["side"])),
        requested_quantity=float(row["requested_quantity"]),
        decision_timestamp_utc=_parse(str(row["decision_timestamp_utc"])),
        submitted_at_utc=_parse(str(row["submitted_at_utc"])),
        resolved_at_utc=_parse(str(row["resolved_at_utc"])),
        filled_price=float(row["filled_price"]),
        filled_quantity=float(row["filled_quantity"]),
        rejected=bool(row["rejected"]),
        fee_cost_quote=float(row["fee_cost_quote"]),
        funding_cost_quote=float(row["funding_cost_quote"]),
    )


def _quote(row: sqlite3.Row) -> TopOfBookQuote:
    return TopOfBookQuote(
        symbol=str(row["symbol"]),
        venue=str(row["venue"]),
        timestamp_utc=_parse(str(row["timestamp_utc"])),
        source_sequence=int(row["source_sequence"]),
        bid_price=float(row["bid_price"]),
        ask_price=float(row["ask_price"]),
        bid_quantity=float(row["bid_quantity"]),
        ask_quantity=float(row["ask_quantity"]),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("execution probe journal timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)
