from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.regimes.classifier import RegimeConfig
from src.regimes.multidomain import (
    MultiDomainRegimeConfig,
    classify_multidomain_regimes,
    stabilize_regime_labels,
)


def _config() -> MultiDomainRegimeConfig:
    return MultiDomainRegimeConfig(
        price=RegimeConfig(
            short_ma_period=3,
            long_ma_period=5,
            adx_period=3,
            vol_period=3,
            vol_lookback=5,
            atr_period=3,
        ),
        rolling_window=5,
        confirmation_bars=2,
        liquidity_stress_z=0.5,
        flow_state_z=0.3,
        liquidation_cascade_z=0.5,
        fragmentation_z=0.5,
    )


def _frame(periods: int = 60) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
    calm_count = periods // 2
    stress_count = periods - calm_count
    calm_close = 100 + np.arange(calm_count) * 0.1
    stress_steps = np.linspace(0.2, 2.0, stress_count)
    stress_close = calm_close[-1] - np.cumsum(stress_steps)
    close = np.concatenate([calm_close, stress_close])
    volatility = np.concatenate(
        [np.linspace(0.10, 0.12, calm_count), np.geomspace(0.2, 2.0, stress_count)]
    )
    spread = np.concatenate(
        [np.linspace(2.0, 2.2, calm_count), np.geomspace(3.0, 30.0, stress_count)]
    )
    depth = np.concatenate(
        [np.linspace(1_000, 1_050, calm_count), np.geomspace(900, 100, stress_count)]
    )
    signed_delta = np.concatenate(
        [np.linspace(10, 12, calm_count), -np.geomspace(20, 500, stress_count)]
    )
    open_interest = np.concatenate(
        [np.linspace(10_000, 10_500, calm_count), np.geomspace(10_000, 4_000, stress_count)]
    )
    liquidations = np.concatenate(
        [np.linspace(1, 1.2, calm_count), np.geomspace(5, 5_000, stress_count)]
    )
    breadth = np.concatenate([np.full(calm_count, 1.0), np.zeros(stress_count)])
    dispersion = np.concatenate(
        [np.linspace(0.001, 0.0012, calm_count), np.geomspace(0.003, 0.3, stress_count)]
    )
    benchmark_return = pd.Series(close).pct_change().fillna(0).to_numpy()
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "max_source_timestamp": timestamps - pd.Timedelta(milliseconds=10),
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "realized_volatility": volatility,
            "spread_bps": spread,
            "depth_notional": depth,
            "signed_delta": signed_delta,
            "open_interest": open_interest,
            "liquidation_total": liquidations,
            "market_breadth_positive_fraction": breadth,
            "cross_asset_return_dispersion": dispersion,
            "benchmark_return": benchmark_return,
        }
    )


def test_classifies_stressed_high_volatility_cascade_and_fragmentation() -> None:
    result = classify_multidomain_regimes(_frame(), _config())
    stressed = result.iloc[35:]

    assert "HIGH_VOL" in set(stressed["volatility_regime"].dropna())
    assert "STRESSED" in set(stressed["liquidity_regime"].dropna())
    assert "LIQUIDATION_CASCADE" in set(stressed["flow_regime"].dropna())
    assert "FRAGMENTED" in set(stressed["cross_market_regime"].dropna())
    assert "DOWNTREND" in set(stressed["trend_regime"].dropna())
    assert stressed["liquidity_stress_score"].between(0, 1).all()


def test_warmup_is_unknown_instead_of_guessed() -> None:
    result = classify_multidomain_regimes(_frame(), _config())

    assert result["volatility_regime"].iloc[:5].isna().all()
    assert result["liquidity_regime"].iloc[:5].isna().all()
    assert result["flow_regime"].iloc[:6].isna().all()
    assert result["cross_market_regime"].iloc[:5].isna().all()


def test_switch_confirmation_retains_previous_stable_state() -> None:
    candidates = pd.Series([pd.NA, "A", "A", "B", "A", "B", "B", "B"])

    result = stabilize_regime_labels(candidates, confirmation_bars=2)

    assert result.tolist() == [pd.NA, pd.NA, "A", "A", "A", "A", "B", "B"]


def test_missing_candidate_clears_state_and_requires_fresh_confirmation() -> None:
    candidates = pd.Series(["A", "A", pd.NA, "A", "A"])

    result = stabilize_regime_labels(candidates, confirmation_bars=2)

    assert result.tolist() == [pd.NA, "A", pd.NA, pd.NA, "A"]


def test_appending_future_rows_cannot_change_past_regimes() -> None:
    full = _frame()
    cutoff = 40
    complete = classify_multidomain_regimes(full, _config()).iloc[:cutoff]
    prefix = classify_multidomain_regimes(full.iloc[:cutoff], _config())

    columns = [
        "trend_regime",
        "volatility_regime",
        "liquidity_regime",
        "flow_regime",
        "cross_market_regime",
    ]
    pd.testing.assert_frame_equal(
        complete[columns].reset_index(drop=True), prefix[columns].reset_index(drop=True)
    )


def test_supports_independent_per_asset_state() -> None:
    btc = _frame().assign(asset="btc")
    eth = _frame().assign(asset="eth")
    eth["close"] *= 2
    eth["high"] *= 2
    eth["low"] *= 2

    result = classify_multidomain_regimes(pd.concat([eth, btc]), _config())

    assert set(result["asset"]) == {"BTC", "ETH"}
    assert len(result) == len(btc) + len(eth)
    assert not result.duplicated(["timestamp", "asset"]).any()


def test_rejects_future_duplicate_naive_and_invalid_inputs() -> None:
    frame = _frame()
    future = frame.copy()
    future.loc[0, "max_source_timestamp"] = future.loc[0, "timestamp"] + pd.Timedelta(seconds=1)
    with pytest.raises(ValueError, match="future source"):
        classify_multidomain_regimes(future, _config())

    with pytest.raises(ValueError, match="duplicate"):
        classify_multidomain_regimes(pd.concat([frame, frame.iloc[[0]]]), _config())

    naive = frame.copy()
    naive["timestamp"] = naive["timestamp"].dt.tz_localize(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        classify_multidomain_regimes(naive, _config())

    bad = frame.copy()
    bad.loc[0, "depth_notional"] = 0
    with pytest.raises(ValueError, match="must be positive"):
        classify_multidomain_regimes(bad, _config())

    bad_breadth = frame.copy()
    bad_breadth.loc[0, "market_breadth_positive_fraction"] = 1.1
    with pytest.raises(ValueError, match="between zero and one"):
        classify_multidomain_regimes(bad_breadth, _config())

    with pytest.raises(ValueError, match="window configuration"):
        replace(_config(), rolling_window=2)
