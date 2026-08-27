"""Hyperliquid Parquet storage must round-trip data and merge incremental
writes without duplicates, and must never collide with another venue's
data - the Hyperliquid counterpart to test_okx_derivatives_storage.py.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.hyperliquid_storage import (
    read_hyperliquid_asset_ctx,
    read_hyperliquid_bbo,
    read_hyperliquid_predicted_funding,
    write_hyperliquid_asset_ctx,
    write_hyperliquid_bbo,
    write_hyperliquid_predicted_funding,
)


def _asset_ctx_frame(start: str, n: int, coin: str = "BTC") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="30s", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "coin": coin,
            "funding": [0.0000125] * n,
            "open_interest": [38000.0] * n,
            "mark_px": [80225.0] * n,
            "oracle_px": [80225.9] * n,
            "mid_px": [80210.5] * n,
            "premium": [-0.0001857256] * n,
            "day_ntl_vlm": [3_421_216_797.8] * n,
        }
    )


def _bbo_frame(start: str, n: int, coin: str = "BTC") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="30s", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "coin": coin,
            "bid_price": [80208.0] * n,
            "bid_size": [0.36] * n,
            "ask_price": [80209.0] * n,
            "ask_size": [4.51] * n,
        }
    )


def _predicted_funding_frame(start: str, n: int, coin: str = "BTC") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="30s", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "coin": coin,
            "venue": ["BybitPerp"] * n,
            "funding_rate": [0.0001] * n,
            "next_funding_time": [1787846400000.0] * n,
            "funding_interval_hours": [8.0] * n,
        }
    )


def test_asset_ctx_write_then_read_round_trip(tmp_path: Path) -> None:
    df = _asset_ctx_frame("2026-01-01", 5)
    write_hyperliquid_asset_ctx(df, tmp_path)

    result = read_hyperliquid_asset_ctx(tmp_path, "BTC")

    assert len(result) == 5
    pd.testing.assert_series_equal(
        result["timestamp"].reset_index(drop=True), df["timestamp"].reset_index(drop=True)
    )


def test_asset_ctx_incremental_write_merges_without_duplicates(tmp_path: Path) -> None:
    first = _asset_ctx_frame("2026-01-01T00:00", 5)
    write_hyperliquid_asset_ctx(first, tmp_path)

    second = _asset_ctx_frame("2026-01-01T00:01:30", 5)  # overlaps by 2 readings
    write_hyperliquid_asset_ctx(second, tmp_path)

    result = read_hyperliquid_asset_ctx(tmp_path, "BTC")
    assert len(result) == 8


def test_asset_ctx_read_missing_coin_returns_empty_frame(tmp_path: Path) -> None:
    result = read_hyperliquid_asset_ctx(tmp_path, "BTC")
    assert result.empty


def test_asset_ctx_does_not_collide_with_other_exchanges(tmp_path: Path) -> None:
    write_hyperliquid_asset_ctx(_asset_ctx_frame("2026-01-01", 3), tmp_path)
    assert not (tmp_path / "open_interest").exists()
    assert not (tmp_path / "okx_open_interest").exists()
    assert (tmp_path / "hyperliquid_asset_ctx").exists()


def test_bbo_write_then_read_round_trip(tmp_path: Path) -> None:
    df = _bbo_frame("2026-01-01", 5)
    write_hyperliquid_bbo(df, tmp_path)

    result = read_hyperliquid_bbo(tmp_path, "BTC")

    assert len(result) == 5
    assert result["ask_price"].gt(result["bid_price"]).all()


def test_predicted_funding_separates_by_venue(tmp_path: Path) -> None:
    bybit_rows = _predicted_funding_frame("2026-01-01", 3, coin="BTC")
    binance_rows = bybit_rows.assign(venue="BinPerp", funding_rate=0.0002)
    write_hyperliquid_predicted_funding(pd.concat([bybit_rows, binance_rows]), tmp_path)

    result = read_hyperliquid_predicted_funding(tmp_path, "BTC")

    assert len(result) == 6
    assert set(result["venue"]) == {"BybitPerp", "BinPerp"}


def test_coins_are_separate_partitions(tmp_path: Path) -> None:
    write_hyperliquid_asset_ctx(_asset_ctx_frame("2026-01-01", 5, coin="BTC"), tmp_path)
    write_hyperliquid_asset_ctx(_asset_ctx_frame("2026-01-01", 3, coin="ETH"), tmp_path)

    assert len(read_hyperliquid_asset_ctx(tmp_path, "BTC")) == 5
    assert len(read_hyperliquid_asset_ctx(tmp_path, "ETH")) == 3
