"""fetch_klines must page correctly (forward, ccxt-style), dedupe, and stay
within [start, end]."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data import ingest


class FakeKrakenClient:
    """Simulates Kraken/ccxt's OHLC endpoint: oldest-first pages starting at
    `start_ms`, capped at `limit`."""

    def __init__(self, rows: list[tuple[int, float, float, float, float, float, float]]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    def get_kline_page(
        self, *, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int
    ) -> list[list[str]]:
        self.calls.append({"start_ms": start_ms, "end_ms": end_ms, "limit": limit})
        candidates = [r for r in self.rows if start_ms <= r[0] <= end_ms]
        candidates.sort(key=lambda r: r[0])
        page = candidates[:limit]
        return [[str(v) for v in row] for row in page]


def _hourly_rows(n: int, start: str = "2024-01-01") -> list[tuple]:
    ts = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return [
        (int(t.value // 1_000_000), 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 10.0, 1000.0)
        for i, t in enumerate(ts)
    ]


def test_single_page_fetch_returns_full_range() -> None:
    rows = _hourly_rows(5)
    client = FakeKrakenClient(rows)
    start_ms, end_ms = rows[0][0], rows[-1][0]

    df = ingest.fetch_klines(
        client,
        symbol="BTCUSD",
        interval="1h",
        timeframe="1h",
        start_ms=start_ms,
        end_ms=end_ms,
    )

    assert len(df) == 5
    assert df["timestamp"].is_monotonic_increasing
    assert len(client.calls) == 1


def test_multi_page_fetch_pages_forwards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest, "MAX_LIMIT", 2)
    rows = _hourly_rows(5)
    client = FakeKrakenClient(rows)
    start_ms, end_ms = rows[0][0], rows[-1][0]

    df = ingest.fetch_klines(
        client,
        symbol="BTCUSD",
        interval="1h",
        timeframe="1h",
        start_ms=start_ms,
        end_ms=end_ms,
    )

    assert len(df) == 5
    assert df["timestamp"].is_monotonic_increasing
    assert df["timestamp"].duplicated().sum() == 0
    assert len(client.calls) == 3  # ceil(5 / 2)


def test_fetch_respects_start_end_bounds() -> None:
    rows = _hourly_rows(10)
    client = FakeKrakenClient(rows)
    # Ask for only the middle 3 candles.
    start_ms, end_ms = rows[3][0], rows[5][0]

    df = ingest.fetch_klines(
        client,
        symbol="BTCUSD",
        interval="1h",
        timeframe="1h",
        start_ms=start_ms,
        end_ms=end_ms,
    )

    assert len(df) == 3
    assert df["timestamp"].min() == pd.Timestamp(start_ms, unit="ms", tz="UTC")
    assert df["timestamp"].max() == pd.Timestamp(end_ms, unit="ms", tz="UTC")


def test_fetch_empty_range_returns_empty_frame() -> None:
    client = FakeKrakenClient([])
    df = ingest.fetch_klines(
        client,
        symbol="BTCUSD",
        interval="1h",
        timeframe="1h",
        start_ms=0,
        end_ms=1,
    )
    assert df.empty


def test_start_after_end_raises() -> None:
    client = FakeKrakenClient([])
    with pytest.raises(ValueError):
        ingest.fetch_klines(
            client,
            symbol="BTCUSD",
            interval="1h",
            timeframe="1h",
            start_ms=100,
            end_ms=0,
        )
