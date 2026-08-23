"""Durable PAPER order/fill/position reconciliation (Cycle 3).

`src.execution.adapter.ExecutionAdapter.submit()` is synchronous and
in-memory: call it, get a `Fill` back. That is correct for the
deterministic offline backtest/calibration path, but not for a real
(paper) exchange conversation, where the process can crash between
"we sent the order" and "we know what happened to it" - the exchange may
have accepted it, rejected it, or the process may simply not know
("ambiguous ACK"). This module adds the write-ahead state that survives
that crash: an order is durably recorded as intended before it is ever
submitted, using an idempotent client_order_id derived from a caller
-supplied idempotency key, so a retried submission after a restart maps
onto the *same* order instead of risking a duplicate.

State machine (rejects illegal transitions rather than silently
overwriting):

    PENDING_SUBMIT --mark_submitted--> SUBMITTED
    SUBMITTED --mark_submitted (retry)--> SUBMITTED (attempts += 1)
    SUBMITTED --apply_fill_result(rejected)--> REJECTED
    PENDING_SUBMIT --apply_fill_result(rejected)--> REJECTED
    SUBMITTED --apply_fill_result(fill)--> PARTIALLY_FILLED | FILLED
    PARTIALLY_FILLED --apply_fill_result(fill)--> PARTIALLY_FILLED | FILLED

Any order still SUBMITTED after a restart is, by definition, ambiguous:
the process does not know whether the exchange ever received it, filled
it, or lost it. `list_in_state(SUBMITTED)` finds them; `reconcile_
ambiguous_order`/`reconcile_ambiguous_orders` resolve each one against an
injected `query_fn` (in production, a real exchange order-status lookup
by client_order_id) rather than guessing - an order `query_fn` cannot yet
resolve is left SUBMITTED for the next reconciliation pass, fail-closed.

Position state is a weighted-average-cost ledger maintained transactionally
alongside every applied fill (open/add/partial-close/full-close/flip all
handled - see `_apply_fill_to_position`), so it can never drift out of sync
with the fills that produced it.

Multi-leg setups (e.g. Neutral/Arbitrage) share a `leg_group_id`;
`leg_group_status` reports ORPHANED when some legs filled while others were
rejected or remain ambiguous, so that state is surfaced rather than silently
left as a naked, unhedged position.
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from src.execution.adapter import Fill
from src.execution.intent import IntentSide

_CLIENT_ORDER_ID_NAMESPACE = uuid.UUID("6e1f7e2a-6c1e-4a3a-9c1a-3b1f2e5d7a10")


class PaperOrderState(StrEnum):
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


class LegGroupStatus(StrEnum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    CLEANLY_REJECTED = "CLEANLY_REJECTED"
    ORPHANED = "ORPHANED"


class PaperReconciliationError(RuntimeError):
    """Raised on an illegal state transition, overfill, or unknown order."""


@dataclass(frozen=True, slots=True)
class PaperOrderRecord:
    client_order_id: str
    idempotency_key: str
    leg_group_id: str | None
    symbol: str
    side: IntentSide
    quantity: float
    reference_price: float
    state: PaperOrderState
    filled_quantity: float
    average_fill_price: float | None
    spread_cost_quote: float
    slippage_cost_quote: float
    fee_cost_quote: float
    funding_cost_quote: float
    reject_reason: str | None
    submit_attempts: int
    created_at_utc: datetime
    updated_at_utc: datetime


@dataclass(frozen=True, slots=True)
class PaperPositionRecord:
    symbol: str
    net_quantity: float
    average_price: float
    realized_pnl_quote: float
    updated_at_utc: datetime


def client_order_id_for(idempotency_key: str) -> str:
    """Deterministic: the same idempotency key always yields the same id,
    so a producer can safely call `begin_order` again after a crash without
    tracking whether its previous attempt reached this store.
    """
    if not idempotency_key.strip():
        raise ValueError("paper order idempotency key must be non-empty")
    return f"paper-{uuid.uuid5(_CLIENT_ORDER_ID_NAMESPACE, idempotency_key).hex}"


class PaperOrderStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_orders (
                    client_order_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    leg_group_id TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    reference_price REAL NOT NULL,
                    state TEXT NOT NULL,
                    filled_quantity REAL NOT NULL DEFAULT 0,
                    filled_notional REAL NOT NULL DEFAULT 0,
                    spread_cost_quote REAL NOT NULL DEFAULT 0,
                    slippage_cost_quote REAL NOT NULL DEFAULT 0,
                    fee_cost_quote REAL NOT NULL DEFAULT 0,
                    funding_cost_quote REAL NOT NULL DEFAULT 0,
                    reject_reason TEXT,
                    submit_attempts INTEGER NOT NULL DEFAULT 0,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_paper_orders_state
                ON paper_orders(state);
                CREATE INDEX IF NOT EXISTS idx_paper_orders_leg_group
                ON paper_orders(leg_group_id);
                CREATE TABLE IF NOT EXISTS paper_positions (
                    symbol TEXT PRIMARY KEY,
                    net_quantity REAL NOT NULL,
                    average_price REAL NOT NULL,
                    realized_pnl_quote REAL NOT NULL DEFAULT 0,
                    updated_at_utc TEXT NOT NULL
                );
                """
            )

    def begin_order(
        self,
        *,
        idempotency_key: str,
        symbol: str,
        side: IntentSide,
        quantity: float,
        reference_price: float,
        leg_group_id: str | None,
        now_utc: datetime,
    ) -> PaperOrderRecord:
        if not symbol.strip():
            raise ValueError("paper order symbol must be non-empty")
        if not math.isfinite(quantity) or quantity <= 0:
            raise ValueError("paper order quantity must be finite and positive")
        if not math.isfinite(reference_price) or reference_price <= 0:
            raise ValueError("paper order reference price must be finite and positive")
        client_order_id = client_order_id_for(idempotency_key)
        now = _iso(now_utc, "paper order created_at")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._fetch(connection, client_order_id)
            if existing is not None:
                connection.commit()
                return existing
            connection.execute(
                """
                INSERT INTO paper_orders (
                    client_order_id, idempotency_key, leg_group_id, symbol, side,
                    quantity, reference_price, state, created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_order_id,
                    idempotency_key,
                    leg_group_id,
                    symbol,
                    side.value,
                    quantity,
                    reference_price,
                    PaperOrderState.PENDING_SUBMIT.value,
                    now,
                    now,
                ),
            )
            record = self._fetch(connection, client_order_id)
            connection.commit()
        assert record is not None
        return record

    def mark_submitted(self, client_order_id: str, *, now_utc: datetime) -> PaperOrderRecord:
        now = _iso(now_utc, "paper order submitted_at")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._fetch(connection, client_order_id)
            if existing is None:
                raise PaperReconciliationError(f"unknown paper order: {client_order_id}")
            if existing.state not in (PaperOrderState.PENDING_SUBMIT, PaperOrderState.SUBMITTED):
                raise PaperReconciliationError(
                    f"cannot submit paper order {client_order_id} from state {existing.state}"
                )
            connection.execute(
                """
                UPDATE paper_orders
                SET state = ?, submit_attempts = submit_attempts + 1, updated_at_utc = ?
                WHERE client_order_id = ?
                """,
                (PaperOrderState.SUBMITTED.value, now, client_order_id),
            )
            record = self._fetch(connection, client_order_id)
            connection.commit()
        assert record is not None
        return record

    def apply_fill_result(self, client_order_id: str, fill: Fill) -> PaperOrderRecord:
        if fill.rejected:
            return self._record_rejection(
                client_order_id, reason=fill.reject_reason or "rejected", now_utc=fill.filled_at
            )
        return self._record_fill(client_order_id, fill)

    def get(self, client_order_id: str) -> PaperOrderRecord | None:
        with self._connect() as connection:
            return self._fetch(connection, client_order_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> PaperOrderRecord | None:
        return self.get(client_order_id_for(idempotency_key))

    def list_in_state(self, state: PaperOrderState) -> tuple[PaperOrderRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT client_order_id FROM paper_orders WHERE state = ? ORDER BY created_at_utc",
                (state.value,),
            ).fetchall()
            return tuple(
                record
                for client_order_id, in rows
                if (record := self._fetch(connection, client_order_id)) is not None
            )

    def reconcile_ambiguous_order(
        self, client_order_id: str, query_fn: Callable[[str], Fill | None]
    ) -> PaperOrderRecord:
        record = self.get(client_order_id)
        if record is None:
            raise PaperReconciliationError(f"unknown paper order: {client_order_id}")
        if record.state is not PaperOrderState.SUBMITTED:
            return record
        resolution = query_fn(client_order_id)
        if resolution is None:
            return record  # still unknown; fail closed, leave SUBMITTED for the next pass
        return self.apply_fill_result(client_order_id, resolution)

    def reconcile_ambiguous_orders(
        self, query_fn: Callable[[str], Fill | None]
    ) -> tuple[PaperOrderRecord, ...]:
        ambiguous = self.list_in_state(PaperOrderState.SUBMITTED)
        return tuple(
            self.reconcile_ambiguous_order(record.client_order_id, query_fn)
            for record in ambiguous
        )

    def leg_group_status(self, leg_group_id: str) -> LegGroupStatus:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT client_order_id FROM paper_orders WHERE leg_group_id = ?",
                (leg_group_id,),
            ).fetchall()
        if not rows:
            raise PaperReconciliationError(f"unknown paper leg group: {leg_group_id}")
        records = [self.get(client_order_id) for client_order_id, in rows]
        states = {record.state for record in records if record is not None}
        if states <= {PaperOrderState.REJECTED}:
            return LegGroupStatus.CLEANLY_REJECTED
        if states <= {PaperOrderState.FILLED}:
            return LegGroupStatus.SETTLED
        has_exposure = bool(
            states & {PaperOrderState.FILLED, PaperOrderState.PARTIALLY_FILLED}
        )
        has_unresolved_or_failed = bool(
            states
            & {
                PaperOrderState.REJECTED,
                PaperOrderState.SUBMITTED,
                PaperOrderState.PENDING_SUBMIT,
            }
        )
        if has_exposure and has_unresolved_or_failed:
            return LegGroupStatus.ORPHANED
        return LegGroupStatus.PENDING

    def get_position(self, symbol: str) -> PaperPositionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT symbol, net_quantity, average_price, realized_pnl_quote, updated_at_utc "
                "FROM paper_positions WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        if row is None:
            return None
        return PaperPositionRecord(
            symbol=str(row[0]),
            net_quantity=float(row[1]),
            average_price=float(row[2]),
            realized_pnl_quote=float(row[3]),
            updated_at_utc=_parse(str(row[4])),
        )

    def _record_rejection(
        self, client_order_id: str, *, reason: str, now_utc: datetime
    ) -> PaperOrderRecord:
        now = _iso(now_utc, "paper order rejected_at")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._fetch(connection, client_order_id)
            if existing is None:
                raise PaperReconciliationError(f"unknown paper order: {client_order_id}")
            if existing.state not in (PaperOrderState.PENDING_SUBMIT, PaperOrderState.SUBMITTED):
                raise PaperReconciliationError(
                    f"cannot reject paper order {client_order_id} from state {existing.state}"
                )
            connection.execute(
                """
                UPDATE paper_orders
                SET state = ?, reject_reason = ?, updated_at_utc = ?
                WHERE client_order_id = ?
                """,
                (PaperOrderState.REJECTED.value, reason, now, client_order_id),
            )
            record = self._fetch(connection, client_order_id)
            connection.commit()
        assert record is not None
        return record

    def _record_fill(self, client_order_id: str, fill: Fill) -> PaperOrderRecord:
        if not math.isfinite(fill.filled_quantity) or fill.filled_quantity <= 0:
            raise ValueError("paper fill quantity must be finite and positive")
        if not math.isfinite(fill.filled_price) or fill.filled_price <= 0:
            raise ValueError("paper fill price must be finite and positive")
        now = _iso(fill.filled_at, "paper fill filled_at")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._fetch(connection, client_order_id)
            if existing is None:
                raise PaperReconciliationError(f"unknown paper order: {client_order_id}")
            if existing.state not in (
                PaperOrderState.SUBMITTED,
                PaperOrderState.PARTIALLY_FILLED,
            ):
                raise PaperReconciliationError(
                    f"cannot fill paper order {client_order_id} from state {existing.state}"
                )
            new_filled_quantity = existing.filled_quantity + fill.filled_quantity
            if new_filled_quantity > existing.quantity + 1e-9:
                raise PaperReconciliationError(
                    f"paper order {client_order_id} overfilled: "
                    f"{new_filled_quantity} > {existing.quantity}"
                )
            new_state = (
                PaperOrderState.FILLED
                if new_filled_quantity >= existing.quantity - 1e-9
                else PaperOrderState.PARTIALLY_FILLED
            )
            existing_notional = (existing.average_fill_price or 0.0) * existing.filled_quantity
            new_notional = existing_notional + fill.filled_price * fill.filled_quantity
            connection.execute(
                """
                UPDATE paper_orders
                SET state = ?, filled_quantity = ?, filled_notional = ?,
                    spread_cost_quote = spread_cost_quote + ?,
                    slippage_cost_quote = slippage_cost_quote + ?,
                    fee_cost_quote = fee_cost_quote + ?,
                    funding_cost_quote = funding_cost_quote + ?,
                    updated_at_utc = ?
                WHERE client_order_id = ?
                """,
                (
                    new_state.value,
                    new_filled_quantity,
                    new_notional,
                    fill.spread_cost_quote,
                    fill.slippage_cost_quote,
                    fill.fee_cost_quote,
                    fill.funding_cost_quote,
                    now,
                    client_order_id,
                ),
            )
            _apply_fill_to_position(
                connection,
                symbol=existing.symbol,
                side=existing.side,
                filled_quantity=fill.filled_quantity,
                filled_price=fill.filled_price,
                now_iso=now,
            )
            record = self._fetch(connection, client_order_id)
            connection.commit()
        assert record is not None
        return record

    def _fetch(
        self, connection: sqlite3.Connection, client_order_id: str
    ) -> PaperOrderRecord | None:
        row = connection.execute(
            """
            SELECT client_order_id, idempotency_key, leg_group_id, symbol, side, quantity,
                   reference_price, state, filled_quantity, filled_notional,
                   spread_cost_quote, slippage_cost_quote, fee_cost_quote, funding_cost_quote,
                   reject_reason, submit_attempts, created_at_utc, updated_at_utc
            FROM paper_orders WHERE client_order_id = ?
            """,
            (client_order_id,),
        ).fetchone()
        if row is None:
            return None
        filled_quantity = float(row[8])
        return PaperOrderRecord(
            client_order_id=str(row[0]),
            idempotency_key=str(row[1]),
            leg_group_id=str(row[2]) if row[2] is not None else None,
            symbol=str(row[3]),
            side=IntentSide(str(row[4])),
            quantity=float(row[5]),
            reference_price=float(row[6]),
            state=PaperOrderState(str(row[7])),
            filled_quantity=filled_quantity,
            average_fill_price=(float(row[9]) / filled_quantity) if filled_quantity > 0 else None,
            spread_cost_quote=float(row[10]),
            slippage_cost_quote=float(row[11]),
            fee_cost_quote=float(row[12]),
            funding_cost_quote=float(row[13]),
            reject_reason=str(row[14]) if row[14] is not None else None,
            submit_attempts=int(row[15]),
            created_at_utc=_parse(str(row[16])),
            updated_at_utc=_parse(str(row[17])),
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


def _apply_fill_to_position(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    side: IntentSide,
    filled_quantity: float,
    filled_price: float,
    now_iso: str,
) -> None:
    row = connection.execute(
        "SELECT net_quantity, average_price, realized_pnl_quote FROM paper_positions "
        "WHERE symbol = ?",
        (symbol,),
    ).fetchone()
    signed_delta = filled_quantity if side == IntentSide.BUY else -filled_quantity

    if row is None:
        net_quantity = signed_delta
        average_price = filled_price
        realized_pnl = 0.0
    else:
        old_quantity, old_average_price, realized_pnl = (
            float(row[0]),
            float(row[1]),
            float(row[2]),
        )
        same_direction = old_quantity == 0 or (old_quantity > 0) == (signed_delta > 0)
        if same_direction:
            new_quantity = old_quantity + signed_delta
            average_price = (
                (old_average_price * abs(old_quantity) + filled_price * abs(signed_delta))
                / abs(new_quantity)
                if new_quantity != 0
                else old_average_price
            )
            net_quantity = new_quantity
        else:
            closing_quantity = min(abs(old_quantity), abs(signed_delta))
            direction = 1 if old_quantity > 0 else -1
            realized_pnl += closing_quantity * (filled_price - old_average_price) * direction
            remainder = abs(signed_delta) - closing_quantity
            net_quantity = old_quantity + signed_delta
            average_price = filled_price if remainder > 1e-12 else old_average_price

    connection.execute(
        """
        INSERT INTO paper_positions
            (symbol, net_quantity, average_price, realized_pnl_quote, updated_at_utc)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(symbol) DO UPDATE SET
            net_quantity = excluded.net_quantity,
            average_price = excluded.average_price,
            realized_pnl_quote = excluded.realized_pnl_quote,
            updated_at_utc = excluded.updated_at_utc
        """,
        (symbol, net_quantity, average_price, realized_pnl, now_iso),
    )


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime, name: str) -> str:
    return _utc(value, name).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
