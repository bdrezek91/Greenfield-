"""src.data.deribit_option_quotes's bridge from stored Deribit
option-ticker rows to src.features.options.OptionQuote objects (Cycle 36).
"""

from __future__ import annotations

import pandas as pd

from src.data.deribit_option_quotes import option_quotes_from_ticker_rows
from src.data.schema_deribit_option_ticker import DERIBIT_OPTION_TICKER_COLUMNS


def _row(**overrides: object) -> dict:
    base = {
        "timestamp": pd.Timestamp("2026-08-23T00:00:00Z"),
        "instrument_name": "BTC-24AUG26-100000-C",
        "base_currency": "BTC",
        "expiry_utc": pd.Timestamp("2026-08-24T08:00:00Z"),
        "option_strike": 100_000.0,
        "option_right": "call",
        "mark_price": 0.05,
        "bid_price": 0.048,
        "ask_price": 0.052,
        "mark_iv": 55.0,
        "bid_iv": 52.0,
        "ask_iv": 58.0,
        "delta": 0.4,
        "open_interest": 10.0,
        "underlying_price": 100_500.0,
    }
    base.update(overrides)
    return base


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(DERIBIT_OPTION_TICKER_COLUMNS))


def test_builds_one_option_quote_per_row_with_correct_identity() -> None:
    df = _frame([_row()])

    quotes = option_quotes_from_ticker_rows(df)

    assert len(quotes) == 1
    quote = quotes[0]
    assert quote.instrument.exchange == "deribit"
    assert quote.instrument.venue_symbol == "BTC-24AUG26-100000-C"
    assert quote.instrument.option_right == "call"
    assert quote.instrument.option_strike == "100000.0"
    assert quote.bid_iv == 52.0
    assert quote.ask_iv == 58.0
    assert quote.delta == 0.4
    assert quote.event_at_utc == quote.received_at_utc


def test_nan_bid_ask_iv_and_delta_become_none_not_zero() -> None:
    df = _frame([_row(bid_iv=float("nan"), ask_iv=float("nan"), delta=float("nan"))])

    quotes = option_quotes_from_ticker_rows(df)

    assert len(quotes) == 1
    assert quotes[0].bid_iv is None
    assert quotes[0].ask_iv is None
    assert quotes[0].delta is None


def test_a_row_with_nan_mark_iv_is_skipped_not_raised() -> None:
    """OptionQuote's own validation requires mark_iv to be finite and
    positive - a row that fails it (e.g. a transient gap in a real poll)
    must be silently skipped, not crash the whole batch."""
    df = _frame([_row(instrument_name="BTC-24AUG26-90000-C", mark_iv=float("nan")), _row()])

    quotes = option_quotes_from_ticker_rows(df)

    assert len(quotes) == 1
    assert quotes[0].instrument.venue_symbol == "BTC-24AUG26-100000-C"


def test_empty_frame_returns_empty_list() -> None:
    assert option_quotes_from_ticker_rows(_frame([])) == []
