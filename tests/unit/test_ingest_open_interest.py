"""fetch_open_interest must page forward through cursors, dedupe, and stay
within [start, end].
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.data import ingest_open_interest


class FakeOpenInterestClient:
    """Simulates Bybit's open-interest endpoint: forward cursor pagination,
    capped at `limit` per page.
    """

    def __init__(self, rows: list[tuple[int, float]]) -> None:
        self.rows = sorted(rows, key=lambda r: r[0])
        self.calls: list[dict] = []

    def get_open_interest_page(
        self,
        *,
        category: str,
        symbol: str,
        interval_time: str,
        start_ms: int,
        end_ms: int,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[dict[str, str]], str | None]:
        self.calls.append({"cursor": cursor, "limit": limit})
        offset = int(cursor) if cursor else 0
        candidates = [r for r in self.rows if start_ms <= r[0] <= end_ms]
        page = candidates[offset : offset + limit]
        next_offset = offset + limit
        next_cursor = str(next_offset) if next_offset < len(candidates) else None
        rows = [{"openInterest": str(oi), "timestamp": str(ts)} for ts, oi in page]
        return rows, next_cursor


def _oi_rows(n: int, start: str = "2024-01-01") -> list[tuple[int, float]]:
    ts = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return [(int(t.value // 1_000_000), 1000.0 + i) for i, t in enumerate(ts)]


def test_single_page_fetch_returns_full_range() -> None:
    rows = _oi_rows(5)
    client = FakeOpenInterestClient(rows)
    start_ms, end_ms = rows[0][0], rows[-1][0]

    df = ingest_open_interest.fetch_open_interest(
        client,
        category="linear",
        symbol="BTCUSDT",
        interval_time="1h",
        start_ms=start_ms,
        end_ms=end_ms,
    )

    assert len(df) == 5
    assert df["timestamp"].is_monotonic_increasing
    assert len(client.calls) == 1


def test_multi_page_fetch_follows_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_open_interest, "MAX_LIMIT", 2)
    rows = _oi_rows(5)
    client = FakeOpenInterestClient(rows)
    start_ms, end_ms = rows[0][0], rows[-1][0]

    df = ingest_open_interest.fetch_open_interest(
        client,
        category="linear",
        symbol="BTCUSDT",
        interval_time="1h",
        start_ms=start_ms,
        end_ms=end_ms,
    )

    assert len(df) == 5
    assert df["timestamp"].is_monotonic_increasing
    assert df["timestamp"].duplicated().sum() == 0
    assert len(client.calls) == 3  # ceil(5 / 2)


def test_fetch_empty_range_returns_empty_frame() -> None:
    client = FakeOpenInterestClient([])
    df = ingest_open_interest.fetch_open_interest(
        client, category="linear", symbol="BTCUSDT", interval_time="1h", start_ms=0, end_ms=1
    )
    assert df.empty


def test_start_after_end_raises() -> None:
    client = FakeOpenInterestClient([])
    with pytest.raises(ValueError):
        ingest_open_interest.fetch_open_interest(
            client,
            category="linear",
            symbol="BTCUSDT",
            interval_time="1h",
            start_ms=100,
            end_ms=0,
        )
