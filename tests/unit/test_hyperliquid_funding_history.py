"""fetch_hyperliquid_funding_history must page forward through
Hyperliquid's 500-row-per-call cap, stop cleanly on genuine exhaustion,
and never loop forever if a page stops making progress - the Hyperliquid
counterpart to test_ingest_funding.py.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.hyperliquid_funding_history import fetch_hyperliquid_funding_history


class FakePagingClient:
    """Two pages of 2 rows each, then exhaustion (empty page)."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int | None]] = []

    def get_funding_history(self, coin, *, start_time_ms, end_time_ms=None):
        self.calls.append((start_time_ms, end_time_ms))
        if start_time_ms == 1_000:
            return [
                {"coin": coin, "fundingRate": "0.0001", "premium": "0.00001", "time": 1_000},
                {"coin": coin, "fundingRate": "0.0001", "premium": "0.00001", "time": 2_000},
            ]
        if start_time_ms == 2_001:
            return [
                {"coin": coin, "fundingRate": "0.0002", "premium": "0.00002", "time": 3_000},
                {"coin": coin, "fundingRate": "0.0002", "premium": "0.00002", "time": 4_000},
            ]
        return []


class FakeStuckClient:
    """Always returns the same page - must not loop forever."""

    def __init__(self) -> None:
        self.call_count = 0

    def get_funding_history(self, coin, *, start_time_ms, end_time_ms=None):
        self.call_count += 1
        return [{"coin": coin, "fundingRate": "0.0001", "premium": "0.0", "time": 1_000}]


def test_pages_forward_until_exhausted() -> None:
    client = FakePagingClient()

    df = fetch_hyperliquid_funding_history(client, coin="BTC", start_ms=1_000, end_ms=10_000)

    assert len(df) == 4
    assert df["timestamp"].is_monotonic_increasing
    assert client.calls[0] == (1_000, 10_000)
    assert client.calls[1] == (2_001, 10_000)


def test_stops_at_end_ms_without_fetching_past_it() -> None:
    client = FakePagingClient()

    df = fetch_hyperliquid_funding_history(client, coin="BTC", start_ms=1_000, end_ms=3_000)

    assert df["timestamp"].max() <= pd.Timestamp(3_000, unit="ms", tz="UTC")


def test_stuck_page_does_not_loop_forever() -> None:
    client = FakeStuckClient()

    df = fetch_hyperliquid_funding_history(client, coin="BTC", start_ms=1_000, end_ms=10_000)

    assert len(df) == 1
    assert client.call_count <= 2


def test_rejects_start_after_end() -> None:
    with pytest.raises(ValueError, match="start_ms must be"):
        fetch_hyperliquid_funding_history(
            FakePagingClient(), coin="BTC", start_ms=2_000, end_ms=1_000
        )


def test_empty_history_returns_empty_frame() -> None:
    class EmptyClient:
        def get_funding_history(self, coin, *, start_time_ms, end_time_ms=None):
            return []

    df = fetch_hyperliquid_funding_history(EmptyClient(), coin="BTC", start_ms=1_000, end_ms=10_000)
    assert df.empty
