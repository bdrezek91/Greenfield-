from __future__ import annotations

import pandas as pd
import pytest

from src.features.binance_archive_flow import (
    archive_footprint,
    archive_trade_bars,
    archive_volume_profile,
    synchronize_spot_perp_flow,
)


def _trades(*, market: str = "spot", offset: float = 0.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-01-01T00:00:01Z", "2026-01-01T00:00:30Z", "2026-01-01T00:01:01Z"]
            ),
            "exchange": "binance",
            "market": market,
            "dataset": "trades",
            "symbol": "BTCUSDT",
            "trade_id": [1, 2, 3],
            "price": [100.0 + offset, 101.0 + offset, 102.0 + offset],
            "quantity": [2.0, 1.0, 3.0],
            "quote_quantity": [200.0 + 2 * offset, 101.0 + offset, 306.0 + 3 * offset],
            "signed_quantity": [2.0, -1.0, 3.0],
        }
    )


def test_archive_trade_bars_builds_causal_cvd_ohlcv_and_vwap() -> None:
    result = archive_trade_bars(_trades())

    assert list(result["timestamp"]) == list(
        pd.to_datetime(["2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z"])
    )
    assert result["max_source_timestamp"].iloc[0] == pd.Timestamp("2026-01-01T00:00:30Z")
    assert result["trade_delta"].tolist() == [1.0, 3.0]
    assert result["cvd"].tolist() == [1.0, 4.0]
    assert result["buy_volume"].tolist() == [2.0, 3.0]
    assert result["sell_volume"].tolist() == [1.0, 0.0]
    assert result["trade_vwap"].iloc[0] == pytest.approx(301.0 / 3.0)
    assert result[["open", "high", "low", "close"]].iloc[0].tolist() == [
        100.0,
        101.0,
        100.0,
        101.0,
    ]


def test_archive_footprint_and_profile_use_price_time_buckets() -> None:
    result = archive_footprint(_trades(), price_tick=1.0)
    profile = archive_volume_profile(result)

    first = result[result["timestamp"] == pd.Timestamp("2026-01-01T00:01:00Z")]
    assert first["total_volume"].sum() == 3.0
    assert set(first["price_level"]) == {100.0, 101.0}
    assert profile.iloc[0]["poc"] == 100.0
    assert profile.iloc[0]["vah"] == 101.0
    assert profile.iloc[0]["val"] == 100.0


def test_synchronize_spot_perp_uses_only_exact_common_clock() -> None:
    spot = archive_trade_bars(_trades())
    perp_source = _trades(market="futures-um", offset=1.0).iloc[:2]
    perp = archive_trade_bars(perp_source)

    result = synchronize_spot_perp_flow(pd.concat([spot, perp], ignore_index=True))

    assert len(result) == 1
    assert result.iloc[0]["timestamp"] == pd.Timestamp("2026-01-01T00:01:00Z")
    spot_vwap = 301.0 / 3.0
    perp_vwap = 304.0 / 3.0
    assert result.iloc[0]["basis_bps"] == pytest.approx(
        (perp_vwap / spot_vwap - 1) * 10_000
    )
    assert bool(result.iloc[0]["flow_agreement"])


def test_synchronize_rejects_duplicate_bucket_identity() -> None:
    spot = archive_trade_bars(_trades())
    duplicated = pd.concat([spot, spot.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate"):
        synchronize_spot_perp_flow(duplicated)
