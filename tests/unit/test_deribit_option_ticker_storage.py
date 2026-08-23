"""src.data.deribit_option_ticker_storage's write/read roundtrip and
(timestamp, instrument_name) dedup - the option-ticker counterpart to
test_deribit_market_summary_storage.py.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.deribit_option_ticker_storage import (
    read_deribit_option_ticker,
    write_deribit_option_ticker,
)
from src.data.schema_deribit_option_ticker import DERIBIT_OPTION_TICKER_COLUMNS


def _frame(ts: pd.Timestamp, instrument_names: list[str]) -> pd.DataFrame:
    expiry = pd.Timestamp("2026-08-24T08:00:00Z")
    rows = [
        {
            "timestamp": ts,
            "instrument_name": name,
            "base_currency": "BTC",
            "expiry_utc": expiry,
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
        for name in instrument_names
    ]
    return pd.DataFrame(rows, columns=list(DERIBIT_OPTION_TICKER_COLUMNS))


def test_write_then_read_roundtrips(tmp_path: Path) -> None:
    df = _frame(pd.Timestamp("2026-08-23T00:00:00Z"), ["BTC-24AUG26-100000-C"])

    written = write_deribit_option_ticker(df, tmp_path, "BTC")

    assert len(written) == 1
    result = read_deribit_option_ticker(tmp_path, "BTC")
    assert len(result) == 1
    assert result["instrument_name"].iloc[0] == "BTC-24AUG26-100000-C"
    assert result["bid_iv"].iloc[0] == 52.0


def test_write_is_empty_noop(tmp_path: Path) -> None:
    empty = _frame(pd.Timestamp("2026-08-23T00:00:00Z"), [])

    written = write_deribit_option_ticker(empty, tmp_path, "BTC")

    assert written == []
    assert read_deribit_option_ticker(tmp_path, "BTC").empty


def test_dedup_on_exact_timestamp_and_instrument(tmp_path: Path) -> None:
    ts = pd.Timestamp("2026-08-23T00:00:00Z")
    df = _frame(ts, ["BTC-24AUG26-100000-C"])

    write_deribit_option_ticker(df, tmp_path, "BTC")
    write_deribit_option_ticker(df, tmp_path, "BTC")  # exact re-run

    result = read_deribit_option_ticker(tmp_path, "BTC")
    assert len(result) == 1


def test_read_missing_currency_returns_empty_frame(tmp_path: Path) -> None:
    result = read_deribit_option_ticker(tmp_path, "ETH")

    assert result.empty
    assert list(result.columns) == list(DERIBIT_OPTION_TICKER_COLUMNS)


def test_read_can_be_sliced_by_start_end(tmp_path: Path) -> None:
    early = _frame(pd.Timestamp("2026-08-01T00:00:00Z"), ["BTC-24AUG26-100000-C"])
    late = _frame(pd.Timestamp("2026-08-20T00:00:00Z"), ["BTC-24AUG26-100000-C"])
    write_deribit_option_ticker(early, tmp_path, "BTC")
    write_deribit_option_ticker(late, tmp_path, "BTC")

    result = read_deribit_option_ticker(tmp_path, "BTC", start=pd.Timestamp("2026-08-10T00:00:00Z"))

    assert len(result) == 1
    assert result["timestamp"].iloc[0] == pd.Timestamp("2026-08-20T00:00:00Z")
