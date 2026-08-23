"""Durable risk state must be atomic, checksummed, and fail closed."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.risk.portfolio_engine import PortfolioPosition, PortfolioRiskSnapshot
from src.risk.portfolio_state_store import (
    PortfolioRiskStateError,
    PortfolioRiskStateStore,
)

NOW = datetime(2026, 8, 23, 14, tzinfo=UTC)


def _snapshot() -> PortfolioRiskSnapshot:
    return PortfolioRiskSnapshot(
        positions=(
            PortfolioPosition(
                key="btc-long",
                symbol="BTCUSDT",
                venue="bybit",
                strategy="directional-v1",
                engine="directional",
                signed_notional=12_500.0,
                committed_risk_fraction=0.006,
                opened_at_utc=NOW,
            ),
        ),
        peak_equity=101_000.0,
        daily_realized_pnl=-250.0,
        current_day=NOW.date(),
        kill_switch_reason="operator hold",
    )


def test_atomic_round_trip_and_required_load(tmp_path: Path) -> None:
    path = tmp_path / "risk" / "portfolio-state.json"
    store = PortfolioRiskStateStore(path)
    assert store.load() is None
    with pytest.raises(PortfolioRiskStateError, match="is absent"):
        store.load_required()

    store.save(_snapshot(), saved_at_utc=NOW)

    assert store.load_required() == _snapshot()
    assert list(path.parent.glob("*.tmp")) == []
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == 1
    assert len(envelope["sha256"]) == 64


def test_checksum_detects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    store = PortfolioRiskStateStore(path)
    store.save(_snapshot(), saved_at_utc=NOW)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["snapshot"]["peak_equity"] = 999_999.0
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(PortfolioRiskStateError, match="checksum mismatch"):
        store.load_required()


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        "[]",
        '{"schema_version":999,"sha256":"' + "0" * 64 + '"}',
        '{"schema_version":1,"sha256":"short"}',
    ],
)
def test_malformed_or_incompatible_state_fails_closed(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(PortfolioRiskStateError):
        PortfolioRiskStateStore(path).load_required()


def test_save_rejects_naive_checkpoint_time(tmp_path: Path) -> None:
    store = PortfolioRiskStateStore(tmp_path / "state.json")
    with pytest.raises(ValueError, match="timezone-aware"):
        store.save(_snapshot(), saved_at_utc=datetime(2026, 8, 23, 14))


def test_failed_atomic_replace_preserves_previous_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    store = PortfolioRiskStateStore(path)
    store.save(_snapshot(), saved_at_utc=NOW)
    original = path.read_bytes()

    def _fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr("src.risk.portfolio_state_store.os.replace", _fail_replace)
    with pytest.raises(OSError, match="simulated disk failure"):
        store.save(_snapshot(), saved_at_utc=NOW)

    assert path.read_bytes() == original
    assert list(path.parent.glob("*.tmp")) == []
