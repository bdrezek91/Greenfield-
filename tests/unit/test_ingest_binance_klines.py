"""fetch_binance_klines must page FORWARD (unlike Bybit's backward
pagination - see test_ingest.py), dedupe, and stay within [start, end].
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.data import ingest_binance_klines


class FakeBinanceClient:
    """Simulates Binance's kline endpoint: oldest-first pages, capped at `limit`."""

    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    def get_kline_page(
        self, *, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int
    ) -> list[list]:
        self.calls.append({"start_ms": start_ms, "end_ms": end_ms, "limit": limit})
        candidates = [r for r in self.rows if start_ms <= r[0] <= end_ms]
        candidates.sort(key=lambda r: r[0])  # ascending, oldest-first
        page = candidates[:limit]
        return [list(row) for row in page]


def _hourly_rows(n: int, start: str = "2024-01-01") -> list[tuple]:
    ts = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    rows = []
    for i, t in enumerate(ts):
        open_ms = int(t.value // 1_000_000)
        rows.append(
            (
                open_ms,
                str(100.0 + i),
                str(101.0 + i),
                str(99.0 + i),
                str(100.5 + i),
                str(10.0),
                open_ms + 3_599_999,
                str(1000.0),
                42,
                str(5.0),
                str(500.0),
                "0",
            )
        )
    return rows


def test_single_page_fetch_returns_full_range() -> None:
    rows = _hourly_rows(5)
    client = FakeBinanceClient(rows)
    start_ms, end_ms = rows[0][0], rows[-1][0]

    df = ingest_binance_klines.fetch_binance_klines(
        client, symbol="BTCUSDT", interval="1h", timeframe="1h", start_ms=start_ms, end_ms=end_ms
    )

    assert len(df) == 5
    assert df["timestamp"].is_monotonic_increasing
    assert len(client.calls) == 1


def test_multi_page_fetch_pages_forward(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_binance_klines, "MAX_LIMIT", 2)
    rows = _hourly_rows(5)
    client = FakeBinanceClient(rows)
    start_ms, end_ms = rows[0][0], rows[-1][0]

    df = ingest_binance_klines.fetch_binance_klines(
        client, symbol="BTCUSDT", interval="1h", timeframe="1h", start_ms=start_ms, end_ms=end_ms
    )

    assert len(df) == 5
    assert df["timestamp"].is_monotonic_increasing
    assert df["timestamp"].duplicated().sum() == 0
    assert len(client.calls) == 3  # ceil(5 / 2)


def test_fetch_respects_start_end_bounds() -> None:
    rows = _hourly_rows(10)
    client = FakeBinanceClient(rows)
    start_ms, end_ms = rows[2][0], rows[6][0]

    df = ingest_binance_klines.fetch_binance_klines(
        client, symbol="BTCUSDT", interval="1h", timeframe="1h", start_ms=start_ms, end_ms=end_ms
    )

    assert len(df) == 5
    assert df["timestamp"].min() == pd.Timestamp(start_ms, unit="ms", tz="UTC")
    assert df["timestamp"].max() == pd.Timestamp(end_ms, unit="ms", tz="UTC")


def test_turnover_uses_quote_volume_field() -> None:
    rows = _hourly_rows(1)
    client = FakeBinanceClient(rows)
    start_ms, end_ms = rows[0][0], rows[0][0]

    df = ingest_binance_klines.fetch_binance_klines(
        client, symbol="BTCUSDT", interval="1h", timeframe="1h", start_ms=start_ms, end_ms=end_ms
    )

    assert df["turnover"].iloc[0] == 1000.0


def test_empty_response_returns_empty_frame() -> None:
    client = FakeBinanceClient([])

    df = ingest_binance_klines.fetch_binance_klines(
        client, symbol="BTCUSDT", interval="1h", timeframe="1h", start_ms=0, end_ms=1000
    )

    assert df.empty


def test_start_after_end_raises() -> None:
    client = FakeBinanceClient([])
    with pytest.raises(ValueError, match="start_ms"):
        ingest_binance_klines.fetch_binance_klines(
            client, symbol="BTCUSDT", interval="1h", timeframe="1h", start_ms=1000, end_ms=0
        )
