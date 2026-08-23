"""Deribit market-summary Parquet storage must round-trip data and merge
repeated writes idempotently - the Deribit counterpart to
test_binance_derivatives_storage.py, adapted for full-snapshot-per-poll
semantics (no "newer than last" filter - see
src/data/deribit_market_summary_storage.py's module docstring).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.deribit_market_summary_storage import (
    read_deribit_market_summary,
    write_deribit_market_summary,
)


def _frame(ts: str, instruments: list[str], kind: str = "option") -> pd.DataFrame:
    n = len(instruments)
    return pd.DataFrame(
        {
            "timestamp": [pd.Timestamp(ts, tz="UTC")] * n,
            "instrument_name": instruments,
            "kind": [kind] * n,
            "base_currency": ["BTC"] * n,
            "bid_price": [1.0] * n,
            "ask_price": [1.1] * n,
            "mark_price": [1.05] * n,
            "mid_price": [1.05] * n,
            "last_price": [1.05] * n,
            "open_interest": [100.0] * n,
            "volume": [10.0] * n,
            "volume_usd": [500.0] * n,
            "mark_iv": [45.0] * n,
            "underlying_price": [80000.0] * n,
            "underlying_index": ["BTC-25JUN27"] * n,
        }
    )


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    df = _frame("2024-01-01T00:00:00Z", ["BTC-1-C", "BTC-1-P"])
    write_deribit_market_summary(df, tmp_path, "BTC", "option")

    result = read_deribit_market_summary(tmp_path, "BTC", "option")

    assert len(result) == 2
    assert set(result["instrument_name"]) == {"BTC-1-C", "BTC-1-P"}


def test_each_poll_is_a_new_full_batch_not_deduped_against_prior_polls(tmp_path: Path) -> None:
    first = _frame("2024-01-01T00:00:00Z", ["BTC-1-C", "BTC-1-P"])
    write_deribit_market_summary(first, tmp_path, "BTC", "option")

    second = _frame("2024-01-01T00:05:00Z", ["BTC-1-C", "BTC-1-P"])  # same instruments
    write_deribit_market_summary(second, tmp_path, "BTC", "option")

    result = read_deribit_market_summary(tmp_path, "BTC", "option")
    assert len(result) == 4  # both polls' rows kept - different timestamps


def test_rerunning_the_exact_same_poll_is_idempotent(tmp_path: Path) -> None:
    df = _frame("2024-01-01T00:00:00Z", ["BTC-1-C"])
    write_deribit_market_summary(df, tmp_path, "BTC", "option")
    write_deribit_market_summary(df, tmp_path, "BTC", "option")  # exact re-run

    result = read_deribit_market_summary(tmp_path, "BTC", "option")
    assert len(result) == 1


def test_currency_and_kind_are_separate_partitions(tmp_path: Path) -> None:
    write_deribit_market_summary(
        _frame("2024-01-01T00:00:00Z", ["BTC-1-C"], "option"), tmp_path, "BTC", "option"
    )
    write_deribit_market_summary(
        _frame("2024-01-01T00:00:00Z", ["BTC-PERPETUAL"], "future"), tmp_path, "BTC", "future"
    )

    assert len(read_deribit_market_summary(tmp_path, "BTC", "option")) == 1
    assert len(read_deribit_market_summary(tmp_path, "BTC", "future")) == 1


def test_read_missing_currency_returns_empty_frame(tmp_path: Path) -> None:
    result = read_deribit_market_summary(tmp_path, "ETH", "option")
    assert result.empty
