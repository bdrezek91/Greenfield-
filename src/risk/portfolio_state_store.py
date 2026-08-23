"""Atomic, checksummed persistence for the shared portfolio safety state."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from src.risk.portfolio_engine import PortfolioPosition, PortfolioRiskSnapshot

SCHEMA_VERSION = 1


class PortfolioRiskStateError(RuntimeError):
    """Raised when durable risk state is absent, corrupt, or incompatible."""


class PortfolioRiskStateStore:
    """Persist risk state before acknowledging an exposure-changing action."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(
        self,
        snapshot: PortfolioRiskSnapshot,
        *,
        saved_at_utc: datetime | None = None,
    ) -> None:
        saved_at = _utc(saved_at_utc or datetime.now(UTC), "risk state timestamp")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "saved_at_utc": saved_at.isoformat(),
            "snapshot": _snapshot_to_dict(snapshot),
        }
        envelope = {
            **payload,
            "sha256": _digest(payload),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(envelope, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            _fsync_parent(self.path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self) -> PortfolioRiskSnapshot | None:
        if not self.path.exists():
            return None
        return self._decode(self.path.read_text(encoding="utf-8"))

    def load_required(self) -> PortfolioRiskSnapshot:
        snapshot = self.load()
        if snapshot is None:
            raise PortfolioRiskStateError(
                f"required portfolio risk state is absent: {self.path}"
            )
        return snapshot

    @staticmethod
    def _decode(value: str) -> PortfolioRiskSnapshot:
        try:
            envelope = json.loads(value)
        except json.JSONDecodeError as exc:
            raise PortfolioRiskStateError("portfolio risk state is not valid JSON") from exc
        if not isinstance(envelope, dict):
            raise PortfolioRiskStateError("portfolio risk state must be a JSON object")
        if envelope.get("schema_version") != SCHEMA_VERSION:
            raise PortfolioRiskStateError("unsupported portfolio risk state schema")
        checksum = envelope.get("sha256")
        if not isinstance(checksum, str) or len(checksum) != 64:
            raise PortfolioRiskStateError("portfolio risk state checksum is missing")
        payload = {key: value for key, value in envelope.items() if key != "sha256"}
        if not _constant_time_equal(checksum, _digest(payload)):
            raise PortfolioRiskStateError("portfolio risk state checksum mismatch")
        try:
            _utc(_parse_datetime(payload["saved_at_utc"]), "risk state timestamp")
            raw_snapshot = payload["snapshot"]
            if not isinstance(raw_snapshot, dict):
                raise TypeError("snapshot is not an object")
            return _snapshot_from_dict(raw_snapshot)
        except (KeyError, TypeError, ValueError) as exc:
            raise PortfolioRiskStateError("portfolio risk state payload is invalid") from exc


def _snapshot_to_dict(snapshot: PortfolioRiskSnapshot) -> dict[str, Any]:
    return {
        "positions": [
            {
                "key": position.key,
                "symbol": position.symbol,
                "venue": position.venue,
                "strategy": position.strategy,
                "engine": position.engine,
                "signed_notional": position.signed_notional,
                "committed_risk_fraction": position.committed_risk_fraction,
                "opened_at_utc": position.opened_at_utc.astimezone(UTC).isoformat(),
            }
            for position in snapshot.positions
        ],
        "peak_equity": snapshot.peak_equity,
        "daily_realized_pnl": snapshot.daily_realized_pnl,
        "current_day": (
            snapshot.current_day.isoformat() if snapshot.current_day is not None else None
        ),
        "kill_switch_reason": snapshot.kill_switch_reason,
    }


def _snapshot_from_dict(value: dict[str, Any]) -> PortfolioRiskSnapshot:
    raw_positions = value["positions"]
    if not isinstance(raw_positions, list):
        raise TypeError("positions must be a list")
    positions = tuple(_position_from_dict(item) for item in raw_positions)
    current_day_value = value["current_day"]
    if current_day_value is not None and not isinstance(current_day_value, str):
        raise TypeError("current day must be a string or null")
    peak_equity = _number(value["peak_equity"], "peak equity")
    daily_pnl = _number(value["daily_realized_pnl"], "daily realized PnL")
    reason = value["kill_switch_reason"]
    if reason is not None and not isinstance(reason, str):
        raise TypeError("kill switch reason must be a string or null")
    return PortfolioRiskSnapshot(
        positions=positions,
        peak_equity=peak_equity,
        daily_realized_pnl=daily_pnl,
        current_day=date.fromisoformat(current_day_value) if current_day_value else None,
        kill_switch_reason=reason,
    )


def _position_from_dict(value: Any) -> PortfolioPosition:
    if not isinstance(value, dict):
        raise TypeError("position must be an object")
    string_fields = ("key", "symbol", "venue", "strategy", "engine")
    if any(not isinstance(value.get(field), str) for field in string_fields):
        raise TypeError("position identifiers must be strings")
    return PortfolioPosition(
        key=value["key"],
        symbol=value["symbol"],
        venue=value["venue"],
        strategy=value["strategy"],
        engine=value["engine"],
        signed_notional=_number(value["signed_notional"], "position notional"),
        committed_risk_fraction=_number(
            value["committed_risk_fraction"], "position committed risk"
        ),
        opened_at_utc=_parse_datetime(value["opened_at_utc"]),
    )


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    return converted


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _fsync_parent(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
