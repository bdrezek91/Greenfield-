"""Crash-safe lifecycle and daily risk ledger for autonomous Bybit Demo."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from src.engines.contracts import SetupAction
from src.execution.demo_autonomous_risk import (
    AutonomousDemoRiskConfig,
    daily_loss_limit_usd,
)

_TRADE_NAMESPACE = uuid.UUID("7f40d3c8-87bb-4a4d-92bd-cb2c43a122c8")


class AutonomousDemoStateError(RuntimeError):
    """A lifecycle transition or daily risk invariant failed closed."""


class AutonomousTradePhase(StrEnum):
    OBSERVED = "OBSERVED"
    ENTRY_SUBMITTED = "ENTRY_SUBMITTED"
    OPEN = "OPEN"
    EXIT_SUBMITTED = "EXIT_SUBMITTED"
    CLOSED = "CLOSED"
    SAFETY_HOLD = "SAFETY_HOLD"


_ACTIVE_PHASES = (
    AutonomousTradePhase.OBSERVED,
    AutonomousTradePhase.ENTRY_SUBMITTED,
    AutonomousTradePhase.OPEN,
    AutonomousTradePhase.EXIT_SUBMITTED,
    AutonomousTradePhase.SAFETY_HOLD,
)


@dataclass(frozen=True, slots=True)
class AutonomousTradeRecord:
    trade_id: str
    observation_id: str
    candidate_id: str
    symbol: str
    action: SetupAction
    phase: AutonomousTradePhase
    target_quantity: Decimal
    reference_price: Decimal
    entry_client_order_id: str | None
    entry_fill_price: Decimal | None
    opened_at_utc: datetime | None
    exit_client_order_id: str | None
    exit_reason: str | None
    realized_pnl_usd: Decimal | None
    closed_at_utc: datetime | None
    safety_reason: str | None
    created_at_utc: datetime
    updated_at_utc: datetime


@dataclass(frozen=True, slots=True)
class AutonomousDailyRiskRecord:
    utc_date: date
    starting_capital_usd: Decimal
    entries: int
    realized_pnl_usd: Decimal
    cooldown_until_utc: datetime | None
    kill_switch_reason: str | None
    updated_at_utc: datetime


class AutonomousDemoStateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS autonomous_demo_trades (
                    trade_id TEXT PRIMARY KEY,
                    observation_id TEXT NOT NULL UNIQUE,
                    candidate_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    target_quantity TEXT NOT NULL,
                    reference_price TEXT NOT NULL,
                    entry_client_order_id TEXT UNIQUE,
                    entry_fill_price TEXT,
                    opened_at_utc TEXT,
                    exit_client_order_id TEXT UNIQUE,
                    exit_reason TEXT,
                    realized_pnl_usd TEXT,
                    closed_at_utc TEXT,
                    safety_reason TEXT,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_autonomous_demo_trade_phase
                ON autonomous_demo_trades(phase);
                CREATE TABLE IF NOT EXISTS autonomous_demo_daily_risk (
                    utc_date TEXT PRIMARY KEY,
                    starting_capital_usd TEXT NOT NULL,
                    entries INTEGER NOT NULL,
                    realized_pnl_usd TEXT NOT NULL,
                    cooldown_until_utc TEXT,
                    kill_switch_reason TEXT,
                    updated_at_utc TEXT NOT NULL
                );
                """
            )

    def begin_trade(
        self,
        *,
        observation_id: str,
        candidate_id: str,
        symbol: str,
        action: SetupAction,
        target_quantity: Decimal,
        reference_price: Decimal,
        now_utc: datetime,
    ) -> AutonomousTradeRecord:
        if action not in {SetupAction.LONG, SetupAction.SHORT}:
            raise ValueError("autonomous Demo trade requires LONG or SHORT")
        if not observation_id.strip() or not candidate_id.strip() or not symbol.strip():
            raise ValueError("autonomous Demo trade identity is incomplete")
        _positive(target_quantity, "target quantity")
        _positive(reference_price, "reference price")
        now = _iso(now_utc)
        trade_id = f"demo-{uuid.uuid5(_TRADE_NAMESPACE, observation_id).hex}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._fetch(connection, trade_id)
            if existing is not None:
                requested = (
                    candidate_id,
                    symbol,
                    action,
                    target_quantity,
                    reference_price,
                )
                actual = (
                    existing.candidate_id,
                    existing.symbol,
                    existing.action,
                    existing.target_quantity,
                    existing.reference_price,
                )
                if actual != requested:
                    raise AutonomousDemoStateError("observation id conflicts with durable trade")
                connection.commit()
                return existing
            if self._fetch_active(connection) is not None:
                raise AutonomousDemoStateError("another autonomous Demo trade is active")
            connection.execute(
                """INSERT INTO autonomous_demo_trades (
                    trade_id, observation_id, candidate_id, symbol, action, phase,
                    target_quantity, reference_price, created_at_utc, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade_id,
                    observation_id,
                    candidate_id,
                    symbol,
                    action.value,
                    AutonomousTradePhase.OBSERVED.value,
                    str(target_quantity),
                    str(reference_price),
                    now,
                    now,
                ),
            )
            record = self._fetch(connection, trade_id)
            connection.commit()
        assert record is not None
        return record

    def mark_entry_submitted(
        self, trade_id: str, *, client_order_id: str, now_utc: datetime
    ) -> AutonomousTradeRecord:
        return self._transition(
            trade_id,
            allowed=(AutonomousTradePhase.OBSERVED, AutonomousTradePhase.ENTRY_SUBMITTED),
            target=AutonomousTradePhase.ENTRY_SUBMITTED,
            updates={"entry_client_order_id": client_order_id},
            now_utc=now_utc,
        )

    def mark_open(
        self,
        trade_id: str,
        *,
        fill_price: Decimal,
        opened_at_utc: datetime,
    ) -> AutonomousTradeRecord:
        _positive(fill_price, "entry fill price")
        opened = _iso(opened_at_utc)
        return self._transition(
            trade_id,
            allowed=(AutonomousTradePhase.ENTRY_SUBMITTED, AutonomousTradePhase.OPEN),
            target=AutonomousTradePhase.OPEN,
            updates={"entry_fill_price": str(fill_price), "opened_at_utc": opened},
            now_utc=opened_at_utc,
        )

    def mark_exit_submitted(
        self,
        trade_id: str,
        *,
        client_order_id: str,
        reason: str,
        now_utc: datetime,
    ) -> AutonomousTradeRecord:
        if not reason.strip():
            raise ValueError("autonomous Demo exit reason is required")
        return self._transition(
            trade_id,
            allowed=(AutonomousTradePhase.OPEN, AutonomousTradePhase.EXIT_SUBMITTED),
            target=AutonomousTradePhase.EXIT_SUBMITTED,
            updates={"exit_client_order_id": client_order_id, "exit_reason": reason},
            now_utc=now_utc,
        )

    def mark_closed(
        self,
        trade_id: str,
        *,
        realized_pnl_usd: Decimal,
        closed_at_utc: datetime,
    ) -> AutonomousTradeRecord:
        if not realized_pnl_usd.is_finite():
            raise ValueError("autonomous Demo realized PnL must be finite")
        return self._transition(
            trade_id,
            allowed=(AutonomousTradePhase.EXIT_SUBMITTED, AutonomousTradePhase.CLOSED),
            target=AutonomousTradePhase.CLOSED,
            updates={
                "realized_pnl_usd": str(realized_pnl_usd),
                "closed_at_utc": _iso(closed_at_utc),
            },
            now_utc=closed_at_utc,
        )

    def mark_safety_hold(
        self, trade_id: str, *, reason: str, now_utc: datetime
    ) -> AutonomousTradeRecord:
        if not reason.strip():
            raise ValueError("autonomous Demo safety reason is required")
        return self._transition(
            trade_id,
            allowed=_ACTIVE_PHASES,
            target=AutonomousTradePhase.SAFETY_HOLD,
            updates={"safety_reason": reason},
            now_utc=now_utc,
        )

    def active_trade(self) -> AutonomousTradeRecord | None:
        with self._connect() as connection:
            return self._fetch_active(connection)

    def authorize_entry(
        self,
        *,
        now_utc: datetime,
        starting_capital_usd: Decimal,
        config: AutonomousDemoRiskConfig | None = None,
    ) -> AutonomousDailyRiskRecord:
        config = config or AutonomousDemoRiskConfig()
        _positive(starting_capital_usd, "daily starting capital")
        now = _utc(now_utc)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            daily = self._ensure_day(connection, now, starting_capital_usd)
            self._validate_entry_authorization(
                daily,
                now=now,
                capital=starting_capital_usd,
                config=config,
            )
            connection.commit()
            return daily

    def record_entry(
        self,
        *,
        now_utc: datetime,
        starting_capital_usd: Decimal,
        config: AutonomousDemoRiskConfig | None = None,
    ) -> AutonomousDailyRiskRecord:
        config = config or AutonomousDemoRiskConfig()
        now = _utc(now_utc)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            daily = self._ensure_day(connection, now, starting_capital_usd)
            self._validate_entry_authorization(
                daily,
                now=now,
                capital=starting_capital_usd,
                config=config,
            )
            connection.execute(
                "UPDATE autonomous_demo_daily_risk SET entries = entries + 1, "
                "updated_at_utc = ? WHERE utc_date = ?",
                (_iso(now), now.date().isoformat()),
            )
            result = self._fetch_day(connection, now.date())
            connection.commit()
        assert result is not None
        return result

    def record_close(
        self,
        *,
        now_utc: datetime,
        starting_capital_usd: Decimal,
        realized_pnl_usd: Decimal,
        config: AutonomousDemoRiskConfig | None = None,
    ) -> AutonomousDailyRiskRecord:
        config = config or AutonomousDemoRiskConfig()
        if not realized_pnl_usd.is_finite():
            raise ValueError("daily realized PnL must be finite")
        now = _utc(now_utc)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            daily = self._ensure_day(connection, now, starting_capital_usd)
            total = daily.realized_pnl_usd + realized_pnl_usd
            kill = daily.kill_switch_reason
            if total <= -daily_loss_limit_usd(daily.starting_capital_usd, config):
                kill = "DAILY_LOSS_LIMIT"
            cooldown = now + timedelta(seconds=config.cooldown_seconds)
            connection.execute(
                """UPDATE autonomous_demo_daily_risk
                SET realized_pnl_usd = ?, cooldown_until_utc = ?,
                    kill_switch_reason = ?, updated_at_utc = ?
                WHERE utc_date = ?""",
                (str(total), _iso(cooldown), kill, _iso(now), now.date().isoformat()),
            )
            result = self._fetch_day(connection, now.date())
            connection.commit()
        assert result is not None
        return result

    def activate_kill_switch(
        self, *, now_utc: datetime, starting_capital_usd: Decimal, reason: str
    ) -> AutonomousDailyRiskRecord:
        if not reason.strip():
            raise ValueError("kill switch reason is required")
        now = _utc(now_utc)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_day(connection, now, starting_capital_usd)
            connection.execute(
                "UPDATE autonomous_demo_daily_risk SET kill_switch_reason = ?, "
                "updated_at_utc = ? WHERE utc_date = ?",
                (reason, _iso(now), now.date().isoformat()),
            )
            result = self._fetch_day(connection, now.date())
            connection.commit()
        assert result is not None
        return result

    def _transition(
        self,
        trade_id: str,
        *,
        allowed: tuple[AutonomousTradePhase, ...],
        target: AutonomousTradePhase,
        updates: dict[str, str],
        now_utc: datetime,
    ) -> AutonomousTradeRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._fetch(connection, trade_id)
            if existing is None:
                raise AutonomousDemoStateError("unknown autonomous Demo trade")
            if existing.phase not in allowed:
                raise AutonomousDemoStateError(
                    f"cannot move autonomous Demo trade from {existing.phase} to {target}"
                )
            for field, value in updates.items():
                current = getattr(existing, field)
                normalized = _field_text(current)
                if existing.phase is target and normalized not in {None, value}:
                    raise AutonomousDemoStateError("idempotent transition payload conflicts")
            assignments = ["phase = ?", "updated_at_utc = ?"]
            values: list[str] = [target.value, _iso(now_utc)]
            for field, value in updates.items():
                assignments.append(f"{field} = ?")
                values.append(value)
            values.append(trade_id)
            connection.execute(
                f"UPDATE autonomous_demo_trades SET {', '.join(assignments)} WHERE trade_id = ?",
                values,
            )
            result = self._fetch(connection, trade_id)
            connection.commit()
        assert result is not None
        return result

    def _ensure_day(
        self, connection: sqlite3.Connection, now: datetime, capital: Decimal
    ) -> AutonomousDailyRiskRecord:
        existing = self._fetch_day(connection, now.date())
        if existing is not None:
            return existing
        connection.execute(
            """INSERT INTO autonomous_demo_daily_risk (
                utc_date, starting_capital_usd, entries, realized_pnl_usd, updated_at_utc
            ) VALUES (?, ?, 0, '0', ?)""",
            (now.date().isoformat(), str(capital), _iso(now)),
        )
        result = self._fetch_day(connection, now.date())
        assert result is not None
        return result

    @staticmethod
    def _validate_entry_authorization(
        daily: AutonomousDailyRiskRecord,
        *,
        now: datetime,
        capital: Decimal,
        config: AutonomousDemoRiskConfig,
    ) -> None:
        if daily.starting_capital_usd != capital:
            raise AutonomousDemoStateError("daily starting capital changed within UTC day")
        if daily.kill_switch_reason is not None:
            raise AutonomousDemoStateError("autonomous Demo daily kill switch is active")
        if daily.entries >= config.maximum_trades_per_utc_day:
            raise AutonomousDemoStateError("autonomous Demo daily trade limit reached")
        if daily.cooldown_until_utc is not None and now < daily.cooldown_until_utc:
            raise AutonomousDemoStateError("autonomous Demo cooldown is active")
        if daily.realized_pnl_usd <= -daily_loss_limit_usd(
            daily.starting_capital_usd, config
        ):
            raise AutonomousDemoStateError("autonomous Demo daily loss limit reached")

    def _fetch_active(self, connection: sqlite3.Connection) -> AutonomousTradeRecord | None:
        placeholders = ",".join("?" for _ in _ACTIVE_PHASES)
        rows = connection.execute(
            f"SELECT * FROM autonomous_demo_trades WHERE phase IN ({placeholders}) "
            "ORDER BY created_at_utc",
            tuple(item.value for item in _ACTIVE_PHASES),
        ).fetchall()
        if len(rows) > 1:
            raise AutonomousDemoStateError("multiple active autonomous Demo trades")
        return _trade(rows[0]) if rows else None

    def _fetch(
        self, connection: sqlite3.Connection, trade_id: str
    ) -> AutonomousTradeRecord | None:
        row = connection.execute(
            "SELECT * FROM autonomous_demo_trades WHERE trade_id = ?", (trade_id,)
        ).fetchone()
        return _trade(row) if row else None

    def _fetch_day(
        self, connection: sqlite3.Connection, utc_date: date
    ) -> AutonomousDailyRiskRecord | None:
        row = connection.execute(
            "SELECT * FROM autonomous_demo_daily_risk WHERE utc_date = ?",
            (utc_date.isoformat(),),
        ).fetchone()
        return _daily(row) if row else None

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


def _trade(row: sqlite3.Row) -> AutonomousTradeRecord:
    return AutonomousTradeRecord(
        trade_id=str(row["trade_id"]),
        observation_id=str(row["observation_id"]),
        candidate_id=str(row["candidate_id"]),
        symbol=str(row["symbol"]),
        action=SetupAction(str(row["action"])),
        phase=AutonomousTradePhase(str(row["phase"])),
        target_quantity=Decimal(str(row["target_quantity"])),
        reference_price=Decimal(str(row["reference_price"])),
        entry_client_order_id=_optional_text(row["entry_client_order_id"]),
        entry_fill_price=_optional_decimal(row["entry_fill_price"]),
        opened_at_utc=_optional_datetime(row["opened_at_utc"]),
        exit_client_order_id=_optional_text(row["exit_client_order_id"]),
        exit_reason=_optional_text(row["exit_reason"]),
        realized_pnl_usd=_optional_decimal(row["realized_pnl_usd"]),
        closed_at_utc=_optional_datetime(row["closed_at_utc"]),
        safety_reason=_optional_text(row["safety_reason"]),
        created_at_utc=_parse(str(row["created_at_utc"])),
        updated_at_utc=_parse(str(row["updated_at_utc"])),
    )


def _daily(row: sqlite3.Row) -> AutonomousDailyRiskRecord:
    return AutonomousDailyRiskRecord(
        utc_date=date.fromisoformat(str(row["utc_date"])),
        starting_capital_usd=Decimal(str(row["starting_capital_usd"])),
        entries=int(row["entries"]),
        realized_pnl_usd=Decimal(str(row["realized_pnl_usd"])),
        cooldown_until_utc=_optional_datetime(row["cooldown_until_utc"]),
        kill_switch_reason=_optional_text(row["kill_switch_reason"]),
        updated_at_utc=_parse(str(row["updated_at_utc"])),
    )


def _positive(value: Decimal, name: str) -> None:
    if not value.is_finite() or value <= 0:
        raise ValueError(f"autonomous Demo {name} must be positive")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("autonomous Demo timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _parse(str(value))


def _field_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _iso(value)
    return str(value)
