"""DeribitMarketSummaryCollector.poll_once must write the full snapshot
batch each poll (no "newer than last" filter - see
src/data/deribit_market_summary_collector.py's module docstring), tag
every row with the requested kind, and never fabricate option-only fields
(mark_iv/underlying_price/underlying_index) for a future/perpetual row.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.deribit_market_summary_collector import DeribitMarketSummaryCollector
from src.data.deribit_market_summary_storage import read_deribit_market_summary


class FakeClient:
    def __init__(self, response: list[dict]) -> None:
        self.response = response
        self.calls = 0

    def get_book_summary_by_currency(self, currency: str, kind: str) -> list[dict]:
        self.calls += 1
        return self.response


def _option_row(name: str) -> dict:
    return {
        "instrument_name": name,
        "base_currency": "BTC",
        "bid_price": 0.87,
        "ask_price": 0.89,
        "mark_price": 0.88,
        "mid_price": 0.88,
        "last": 1.0,
        "open_interest": 0.1,
        "volume": 0.0,
        "volume_usd": 0.0,
        "mark_iv": 45.22,
        "underlying_price": 80348.03,
        "underlying_index": "BTC-25JUN27",
    }


def _future_row(name: str) -> dict:
    return {
        "instrument_name": name,
        "base_currency": "BTC",
        "bid_price": 77452.5,
        "ask_price": 77467.5,
        "mark_price": 77457.69,
        "mid_price": 77460.0,
        "last": 77440.0,
        "open_interest": 1755930,
        "volume": 28.24,
        "volume_usd": 2173170.0,
        # no mark_iv/underlying_price/underlying_index - futures don't have them
    }


def test_poll_once_writes_the_full_batch_and_tags_the_requested_kind(tmp_path: Path) -> None:
    client = FakeClient([_option_row("BTC-1-C"), _option_row("BTC-1-P")])
    collector = DeribitMarketSummaryCollector("BTC", "option", tmp_path, client=client)

    written = collector.poll_once()

    assert written == 2
    result = read_deribit_market_summary(tmp_path, "BTC", "option")
    assert len(result) == 2
    assert set(result["kind"]) == {"option"}
    assert result["mark_iv"].iloc[0] == 45.22


def test_future_rows_get_no_fabricated_option_fields(tmp_path: Path) -> None:
    client = FakeClient([_future_row("BTC-PERPETUAL")])
    collector = DeribitMarketSummaryCollector("BTC", "future", tmp_path, client=client)

    collector.poll_once()

    result = read_deribit_market_summary(tmp_path, "BTC", "future")
    assert len(result) == 1
    assert pd.isna(result["mark_iv"].iloc[0])
    assert pd.isna(result["underlying_price"].iloc[0])
    assert pd.isna(result["underlying_index"].iloc[0])


def test_poll_once_returns_zero_on_empty_response(tmp_path: Path) -> None:
    client = FakeClient([])
    collector = DeribitMarketSummaryCollector("BTC", "option", tmp_path, client=client)

    assert collector.poll_once() == 0


def test_repeated_polls_each_write_their_own_full_batch(tmp_path: Path) -> None:
    client = FakeClient([_option_row("BTC-1-C")])
    clock_values = iter(
        [pd.Timestamp("2024-01-01T00:00:00Z"), pd.Timestamp("2024-01-01T00:05:00Z")]
    )
    collector = DeribitMarketSummaryCollector(
        "BTC", "option", tmp_path, client=client, clock=lambda: next(clock_values)
    )

    first = collector.poll_once()
    second = collector.poll_once()

    assert first == 1
    assert second == 1
    result = read_deribit_market_summary(tmp_path, "BTC", "option")
    assert len(result) == 2  # both polls kept, different timestamps
