"""label_trades_with_regime must attach the regime at-or-before each trade's
entry (never a future one), and metrics_by_regime must bucket correctly.
"""

from __future__ import annotations

import pandas as pd

from src.regimes.analysis import label_trades_with_regime, metrics_by_regime


def _regimes() -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=6, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "trend_regime": [pd.NA, pd.NA, "UPTREND", "UPTREND", "DOWNTREND", "DOWNTREND"],
            "vol_regime": [pd.NA, "LOW_VOL", "LOW_VOL", "HIGH_VOL", "HIGH_VOL", "HIGH_VOL"],
        }
    )


def test_label_trades_uses_backward_as_of_regime() -> None:
    ts = pd.date_range("2024-01-01", periods=6, freq="1h", tz="UTC")
    trades = pd.DataFrame(
        {
            "entry_time": [ts[2], ts[3] + pd.Timedelta(minutes=30), ts[5]],
            "exit_time": [ts[3], ts[4], ts[5] + pd.Timedelta(hours=1)],
            "quantity": [1.0, 1.0, 1.0],
            "entry_price": [100.0, 100.0, 100.0],
            "exit_price": [101.0, 99.0, 102.0],
            "fees": [0.0, 0.0, 0.0],
        }
    )
    labeled = label_trades_with_regime(trades, _regimes())

    assert labeled["trend_regime"].tolist() == ["UPTREND", "UPTREND", "DOWNTREND"]
    # Entry at ts[3]+30min falls back to the ts[3] row (UPTREND/HIGH_VOL),
    # not ts[4] which is in the future relative to that entry.
    assert labeled["vol_regime"].tolist() == ["LOW_VOL", "HIGH_VOL", "HIGH_VOL"]


def test_label_trades_before_any_regime_data_is_na() -> None:
    ts = pd.date_range("2024-01-01", periods=6, freq="1h", tz="UTC")
    trades = pd.DataFrame(
        {
            "entry_time": [ts[0]],
            "exit_time": [ts[1]],
            "quantity": [1.0],
            "entry_price": [100.0],
            "exit_price": [101.0],
            "fees": [0.0],
        }
    )
    labeled = label_trades_with_regime(trades, _regimes())
    assert pd.isna(labeled["trend_regime"].iloc[0])


def test_label_trades_empty_input() -> None:
    empty = pd.DataFrame(
        columns=["entry_time", "exit_time", "quantity", "entry_price", "exit_price", "fees"]
    )
    labeled = label_trades_with_regime(empty, _regimes())
    assert labeled.empty
    assert "trend_regime" in labeled.columns
    assert "vol_regime" in labeled.columns


def test_metrics_by_regime_buckets_correctly() -> None:
    trades = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01"] * 4, utc=True),
            "exit_time": pd.to_datetime(["2024-01-02"] * 4, utc=True),
            "quantity": [1.0, 1.0, 1.0, 1.0],
            "entry_price": [100.0, 100.0, 100.0, 100.0],
            "exit_price": [110.0, 105.0, 90.0, 95.0],
            "fees": [0.0, 0.0, 0.0, 0.0],
            "trend_regime": ["UPTREND", "UPTREND", "DOWNTREND", "DOWNTREND"],
        }
    )
    result = metrics_by_regime(trades, "trend_regime")

    assert set(result.keys()) == {"UPTREND", "DOWNTREND"}
    assert result["UPTREND"].trades == 2
    assert result["UPTREND"].net_return == 15.0
    assert result["DOWNTREND"].trades == 2
    assert result["DOWNTREND"].net_return == -15.0


def test_metrics_by_regime_excludes_unlabeled_trades() -> None:
    trades = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01"] * 2, utc=True),
            "exit_time": pd.to_datetime(["2024-01-02"] * 2, utc=True),
            "quantity": [1.0, 1.0],
            "entry_price": [100.0, 100.0],
            "exit_price": [110.0, 90.0],
            "fees": [0.0, 0.0],
            "trend_regime": ["UPTREND", pd.NA],
        }
    )
    result = metrics_by_regime(trades, "trend_regime")
    assert set(result.keys()) == {"UPTREND"}
