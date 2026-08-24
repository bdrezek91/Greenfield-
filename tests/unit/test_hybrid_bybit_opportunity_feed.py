from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.data.raw_event import parse_bybit_message
from src.data.raw_store import AtomicRawWriter
from src.data.schema import empty_klines_frame
from src.data.storage import write_klines
from src.execution.bybit_demo_opportunity_feed import BybitOpportunityFeedError
from src.execution.demo_opportunity_scanner import BybitOpportunitySnapshot
from src.execution.hybrid_bybit_opportunity_feed import (
    HybridBybitOpportunityFeed,
    HybridOpportunityFeedConfig,
)


class _PublicFeed:
    def __init__(self, snapshot: BybitOpportunitySnapshot) -> None:
        self.snapshot = snapshot

    def fetch(self, *, symbol: str) -> BybitOpportunitySnapshot:
        assert symbol == self.snapshot.symbol
        return self.snapshot


def _live(now: datetime) -> BybitOpportunitySnapshot:
    candles = pd.DataFrame(
        {
            "timestamp": pd.date_range(end=now, periods=200, freq="5min", tz="UTC"),
            "max_source_timestamp": pd.date_range(
                end=now, periods=200, freq="5min", tz="UTC"
            ),
            "open": [100.0] * 200,
            "high": [101.0] * 200,
            "low": [99.0] * 200,
            "close": [100.0] * 200,
            "volume": [1.0] * 200,
        }
    )
    return BybitOpportunitySnapshot(
        symbol="BTCUSDT",
        observed_at_utc=now,
        candles=candles,
        trades=(),
        derivatives=pd.DataFrame({"placeholder": [1]}),
        price_tick=0.1,
    )


def _write_history(data_dir: Path, now: datetime) -> None:
    frame = empty_klines_frame()
    frame.loc[0] = {
        "timestamp": pd.Timestamp(now - timedelta(days=10)),
        "open": 90.0,
        "high": 91.0,
        "low": 89.0,
        "close": 90.5,
        "volume": 10.0,
        "turnover": 905.0,
        "symbol": "BTCUSDT",
        "timeframe": "5m",
    }
    write_klines(frame, data_dir)


def _write_bronze(data_dir: Path, now: datetime, dates: int = 3) -> None:
    events = []
    for index in range(dates):
        timestamp = now - timedelta(days=dates - index - 1, seconds=1)
        payload = json.dumps(
            {
                "topic": "publicTrade.BTCUSDT",
                "type": "snapshot",
                "ts": int(timestamp.timestamp() * 1000),
                "data": [
                    {
                        "T": int(timestamp.timestamp() * 1000),
                        "s": "BTCUSDT",
                        "S": "Buy",
                        "v": "0.01",
                        "p": "100",
                        "i": f"trade-{index}",
                    }
                ],
            }
        )
        events.append(
            parse_bybit_message(
                payload,
                receive_ts_ns=int(timestamp.timestamp() * 1_000_000_000),
                connection_id="test-connection",
                receive_sequence=index + 1,
            )
        )
    AtomicRawWriter(data_dir).write(events)


def test_hybrid_feed_uses_local_history_and_verified_bronze(tmp_path: Path) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    _write_history(tmp_path, now)
    _write_bronze(tmp_path, now)
    feed = HybridBybitOpportunityFeed(
        data_dir=tmp_path,
        public_feed=_PublicFeed(_live(now)),  # type: ignore[arg-type]
        config=HybridOpportunityFeedConfig(
            minimum_bronze_dates=3,
            minimum_bronze_trades=3,
            maximum_bronze_trades=3,
        ),
    )

    snapshot = feed.fetch(symbol="BTCUSDT")

    assert len(snapshot.candles) == 201
    assert [trade.trade_id for trade in snapshot.trades] == [
        "trade-0",
        "trade-1",
        "trade-2",
    ]


def test_hybrid_feed_fails_closed_without_three_bronze_dates(tmp_path: Path) -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    _write_history(tmp_path, now)
    _write_bronze(tmp_path, now, dates=2)
    feed = HybridBybitOpportunityFeed(
        data_dir=tmp_path,
        public_feed=_PublicFeed(_live(now)),  # type: ignore[arg-type]
        config=HybridOpportunityFeedConfig(
            minimum_bronze_dates=3,
            minimum_bronze_trades=2,
            maximum_bronze_trades=2,
        ),
    )

    with pytest.raises(BybitOpportunityFeedError, match="dates"):
        feed.fetch(symbol="BTCUSDT")
