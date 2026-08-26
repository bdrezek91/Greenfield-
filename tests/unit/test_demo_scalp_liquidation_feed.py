from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.data.raw_event import parse_bybit_message
from src.data.raw_store import AtomicRawWriter
from src.execution.demo_scalp_liquidation_feed import (
    BronzeLiquidationFeedConfig,
    BronzeLiquidationFeedError,
    fetch_recent_liquidations,
)
from src.execution.demo_scalp_liquidation_signal import LiquidatedSide


def _write_liquidations(data_dir: Path, now: datetime, rows: list[dict[str, str]]) -> None:
    timestamp = now - timedelta(seconds=5)
    payload = json.dumps(
        {
            "topic": "allLiquidation.BTCUSDT",
            "type": "snapshot",
            "ts": int(timestamp.timestamp() * 1000),
            "data": rows,
        }
    )
    event = parse_bybit_message(
        payload,
        receive_ts_ns=int(timestamp.timestamp() * 1_000_000_000),
        connection_id="test-connection",
        receive_sequence=1,
    )
    AtomicRawWriter(data_dir).write([event])


def _row(now: datetime, *, side: str, price: str = "80000", size: str = "1") -> dict[str, str]:
    return {
        "T": str(int((now - timedelta(seconds=5)).timestamp() * 1000)),
        "s": "BTCUSDT",
        "S": side,
        "v": size,
        "p": price,
    }


def test_fetch_recent_liquidations_parses_forced_side_correctly(tmp_path: Path) -> None:
    now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    _write_liquidations(
        tmp_path,
        now,
        [_row(now, side="Sell"), _row(now, side="Buy")],
    )

    events = fetch_recent_liquidations(tmp_path, symbol="BTCUSDT", observed_at_utc=now)

    sides = {event.side for event in events}
    assert sides == {LiquidatedSide.LONGS, LiquidatedSide.SHORTS}


def test_fetch_recent_liquidations_fails_closed_when_no_manifests(tmp_path: Path) -> None:
    now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    with pytest.raises(BronzeLiquidationFeedError, match="no Bronze"):
        fetch_recent_liquidations(tmp_path, symbol="BTCUSDT", observed_at_utc=now)


def test_fetch_recent_liquidations_fails_closed_when_collector_looks_dead(
    tmp_path: Path,
) -> None:
    """A quiet liquidation channel is normal (see the module docstring) -
    this only fires when nothing was written for far longer than any
    plausible quiet period, indicating the collector itself is down."""
    now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    _write_liquidations(tmp_path, now, [_row(now, side="Sell")])

    with pytest.raises(BronzeLiquidationFeedError, match="collector may be dead"):
        fetch_recent_liquidations(
            tmp_path,
            symbol="BTCUSDT",
            observed_at_utc=now + timedelta(hours=1),
            config=BronzeLiquidationFeedConfig(maximum_age_seconds=60.0),
        )


def test_fetch_recent_liquidations_excludes_events_outside_the_fetch_window(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    _write_liquidations(tmp_path, now, [_row(now, side="Sell")])

    events = fetch_recent_liquidations(
        tmp_path,
        symbol="BTCUSDT",
        observed_at_utc=now,
        config=BronzeLiquidationFeedConfig(fetch_window_seconds=1.0, maximum_age_seconds=60.0),
    )
    assert events == ()


def test_a_quiet_liquidation_channel_is_not_treated_as_stale(tmp_path: Path) -> None:
    """Regression: the previous 360s default treated a merely-quiet BTC
    liquidation channel (no manifest flushed in the last few minutes,
    which bybit_raw_collector.py's non-empty-batch-only flush makes
    routine) as data staleness, blocking the scanner from ever running."""
    now = datetime(2026, 8, 26, 12, tzinfo=UTC)
    _write_liquidations(tmp_path, now, [_row(now, side="Sell")])

    events = fetch_recent_liquidations(
        tmp_path,
        symbol="BTCUSDT",
        observed_at_utc=now + timedelta(minutes=10),
    )
    assert len(events) == 1
