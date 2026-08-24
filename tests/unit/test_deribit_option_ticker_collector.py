"""DeribitOptionTickerCollector.poll_once must: fetch the bulk summary,
select the near-ATM subset, fetch each selected instrument's ticker, and
write bid_iv/ask_iv/delta faithfully (never fabricated when Deribit's own
`greeks` object is absent) - mirrors
test_deribit_market_summary_collector.py's fake-client style.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.data.deribit_option_ticker_collector import DeribitOptionTickerCollector
from src.data.deribit_option_ticker_storage import read_deribit_option_ticker


def _summary_rows() -> list[dict]:
    return [
        {"instrument_name": "BTC-24AUG26-100000-C", "underlying_price": 100_500.0},
        {"instrument_name": "BTC-24AUG26-100000-P", "underlying_price": 100_500.0},
        {"instrument_name": "BTC-24AUG26-90000-C", "underlying_price": 100_500.0},
        {"instrument_name": "BTC-24AUG26-90000-P", "underlying_price": 100_500.0},
    ]


class FakeSummaryClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls = 0

    def get_book_summary_by_currency(self, currency: str, kind: str) -> list[dict]:
        self.calls += 1
        assert kind == "option"
        return self.rows


class FakeTickerClient:
    def __init__(self, tickers: dict[str, dict]) -> None:
        self.tickers = tickers
        self.requested: list[str] = []

    def get_ticker(self, instrument_name: str) -> dict:
        self.requested.append(instrument_name)
        return self.tickers[instrument_name]


def _ticker(*, with_greeks: bool = True) -> dict:
    ticker: dict = {
        "mark_price": 0.05,
        "best_bid_price": 0.048,
        "best_ask_price": 0.052,
        "mark_iv": 55.0,
        "bid_iv": 52.0,
        "ask_iv": 58.0,
        "open_interest": 10.0,
        "underlying_price": 100_500.0,
    }
    if with_greeks:
        ticker["greeks"] = {"delta": 0.4}
    return ticker


def test_poll_once_fetches_selected_instruments_and_writes_ticker_fields(
    tmp_path: Path,
) -> None:
    summary_client = FakeSummaryClient(_summary_rows())
    ticker_client = FakeTickerClient(
        {name: _ticker() for name in ("BTC-24AUG26-100000-C", "BTC-24AUG26-100000-P")}
    )
    collector = DeribitOptionTickerCollector(
        "BTC",
        tmp_path,
        expiries_count=1,
        strikes_per_side=1,
        summary_client=summary_client,
        ticker_client=ticker_client,
    )

    written = collector.poll_once()

    assert written == 2
    assert summary_client.calls == 1
    assert set(ticker_client.requested) == {"BTC-24AUG26-100000-C", "BTC-24AUG26-100000-P"}
    result = read_deribit_option_ticker(tmp_path, "BTC")
    assert len(result) == 2
    assert set(result["bid_iv"]) == {52.0}
    assert set(result["delta"]) == {0.4}
    assert set(result["option_right"]) == {"call", "put"}


def test_missing_greeks_object_leaves_delta_nan_not_fabricated(tmp_path: Path) -> None:
    summary_client = FakeSummaryClient(_summary_rows())
    ticker_client = FakeTickerClient(
        {
            "BTC-24AUG26-100000-C": _ticker(with_greeks=False),
            "BTC-24AUG26-100000-P": _ticker(with_greeks=False),
        }
    )
    collector = DeribitOptionTickerCollector(
        "BTC",
        tmp_path,
        expiries_count=1,
        strikes_per_side=1,
        summary_client=summary_client,
        ticker_client=ticker_client,
    )

    collector.poll_once()

    result = read_deribit_option_ticker(tmp_path, "BTC")
    assert result["delta"].isna().all()


def test_poll_once_returns_zero_when_summary_has_no_usable_rows(tmp_path: Path) -> None:
    summary_client = FakeSummaryClient([])
    ticker_client = FakeTickerClient({})
    collector = DeribitOptionTickerCollector(
        "BTC", tmp_path, summary_client=summary_client, ticker_client=ticker_client
    )

    assert collector.poll_once() == 0
    assert ticker_client.requested == []


def test_rejects_non_positive_poll_interval(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="poll_interval_secs must be positive"):
        DeribitOptionTickerCollector("BTC", tmp_path, poll_interval_secs=0)


def test_repeated_polls_each_write_their_own_full_batch(tmp_path: Path) -> None:
    summary_client = FakeSummaryClient(_summary_rows())
    ticker_client = FakeTickerClient(
        {name: _ticker() for name in ("BTC-24AUG26-100000-C", "BTC-24AUG26-100000-P")}
    )
    clock_values = iter(
        [pd.Timestamp("2024-01-01T00:00:00Z"), pd.Timestamp("2024-01-01T00:05:00Z")]
    )
    collector = DeribitOptionTickerCollector(
        "BTC",
        tmp_path,
        expiries_count=1,
        strikes_per_side=1,
        summary_client=summary_client,
        ticker_client=ticker_client,
        clock=lambda: next(clock_values),
    )

    first = collector.poll_once()
    second = collector.poll_once()

    assert first == 2
    assert second == 2
    result = read_deribit_option_ticker(tmp_path, "BTC")
    assert len(result) == 4  # both polls kept, different timestamps
