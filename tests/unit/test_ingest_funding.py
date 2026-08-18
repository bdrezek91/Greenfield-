"""fetch_funding_rates must page correctly, dedupe, and stay within [start, end]."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data import ingest_funding


class FakeFundingClient:
    """Simulates Bybit's funding-rate-history endpoint: newest-first pages,
    capped at `limit`.
    """

    def __init__(self, rows: list[tuple[int, float]]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    def get_funding_rate_page(
        self, *, category: str, symbol: str, start_ms: int, end_ms: int, limit: int
    ) -> list[dict[str, str]]:
        self.calls.append({"start_ms": start_ms, "end_ms": end_ms, "limit": limit})
        candidates = [r for r in self.rows if start_ms <= r[0] <= end_ms]
        candidates.sort(key=lambda r: r[0], reverse=True)
        page = candidates[:limit]
        return [
            {
                "symbol": symbol,
                "fundingRate": str(rate),
                "fundingRateTimestamp": str(ts),
            }
            for ts, rate in page
        ]


def _funding_rows(n: int, start: str = "2024-01-01") -> list[tuple[int, float]]:
    # Funding settles every 8h.
    ts = pd.date_range(start, periods=n, freq="8h", tz="UTC")
    return [(int(t.value // 1_000_000), 0.0001 * i) for i, t in enumerate(ts)]


def test_single_page_fetch_returns_full_range() -> None:
    rows = _funding_rows(5)
    client = FakeFundingClient(rows)
    start_ms, end_ms = rows[0][0], rows[-1][0] + 8 * 60 * 60 * 1000

    df = ingest_funding.fetch_funding_rates(
        client, category="linear", symbol="BTCUSDT", start_ms=start_ms, end_ms=end_ms
    )

    assert len(df) == 5
    assert df["timestamp"].is_monotonic_increasing
    assert len(client.calls) == 1


def test_multi_page_fetch_pages_backwards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_funding, "MAX_LIMIT", 2)
    rows = _funding_rows(5)
    client = FakeFundingClient(rows)
    start_ms, end_ms = rows[0][0], rows[-1][0] + 8 * 60 * 60 * 1000

    df = ingest_funding.fetch_funding_rates(
        client, category="linear", symbol="BTCUSDT", start_ms=start_ms, end_ms=end_ms
    )

    assert len(df) == 5
    assert df["timestamp"].is_monotonic_increasing
    assert df["timestamp"].duplicated().sum() == 0


def test_fetch_empty_range_returns_empty_frame() -> None:
    client = FakeFundingClient([])
    df = ingest_funding.fetch_funding_rates(
        client, category="linear", symbol="BTCUSDT", start_ms=0, end_ms=1
    )
    assert df.empty


def test_start_after_end_raises() -> None:
    client = FakeFundingClient([])
    with pytest.raises(ValueError):
        ingest_funding.fetch_funding_rates(
            client, category="linear", symbol="BTCUSDT", start_ms=100, end_ms=0
        )
