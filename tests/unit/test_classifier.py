"""classify_regimes must correctly label trend/volatility on synthetic
series engineered to be unambiguous, and never guess a regime before enough
history has accumulated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.regimes.classifier import RegimeConfig, classify_regimes


def _df(close: np.ndarray, spread: float = 0.3) -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=len(close), freq="1h", tz="UTC")
    return pd.DataFrame(
        {"timestamp": ts, "high": close + spread, "low": close - spread, "close": close}
    )


def test_warmup_rows_have_na_regime() -> None:
    close = 100 + np.arange(30, dtype=float) * 0.5
    df = _df(close)
    out = classify_regimes(df, RegimeConfig(long_ma_period=50))
    assert out["trend_regime"].isna().all()  # long_ma never warms up in 30 rows


def test_pure_uptrend_is_classified_uptrend() -> None:
    close = 100 + np.arange(150, dtype=float) * 0.5
    df = _df(close)
    out = classify_regimes(df, RegimeConfig(long_ma_period=50, vol_lookback=60))
    tail = out["trend_regime"].iloc[-20:]
    assert (tail == "UPTREND").all()


def test_pure_downtrend_is_classified_downtrend() -> None:
    close = 200 - np.arange(150, dtype=float) * 0.5
    df = _df(close)
    out = classify_regimes(df, RegimeConfig(long_ma_period=50, vol_lookback=60))
    tail = out["trend_regime"].iloc[-20:]
    assert (tail == "DOWNTREND").all()


def test_flat_noise_is_classified_range() -> None:
    close = 100 + np.random.default_rng(0).normal(0, 0.05, size=150)
    df = _df(close)
    out = classify_regimes(df, RegimeConfig(long_ma_period=50, vol_lookback=60))
    tail = out["trend_regime"].iloc[-20:]
    assert (tail == "RANGE").all()


def test_vol_regime_spikes_high_right_after_a_volatility_shift() -> None:
    # vol_regime compares current realized volatility to its OWN trailing
    # window's median (see classifier.py docstring) - a change detector,
    # not an absolute classifier. Deep inside any single homogeneous-
    # volatility stretch it's expected to hover near a 50/50 split (a
    # median split of same-distribution data does that by construction);
    # the real, reliable signal is right after a genuine volatility shift,
    # while the trailing window still reflects the calmer past.
    calm = 100 + np.cumsum(np.random.default_rng(1).normal(0, 0.05, size=150))
    turbulent = calm[-1] + np.cumsum(np.random.default_rng(2).normal(0, 3.0, size=150))
    close = np.concatenate([calm, turbulent])
    df = _df(close)
    out = classify_regimes(df, RegimeConfig(long_ma_period=50, vol_lookback=50))

    calm_steady_state = out["vol_regime"].iloc[69:150]  # warmed up, still within calm
    right_after_shift = out["vol_regime"].iloc[150:200]  # just past the transition
    high_frac_calm = (calm_steady_state == "HIGH_VOL").mean()
    high_frac_after_shift = (right_after_shift == "HIGH_VOL").mean()

    assert high_frac_after_shift > 0.8
    assert high_frac_after_shift > high_frac_calm


def test_default_config_used_when_none_given() -> None:
    close = 100 + np.arange(60, dtype=float) * 0.5
    df = _df(close)
    out = classify_regimes(df)  # no config -> RegimeConfig() defaults
    assert "trend_regime" in out.columns
    assert "vol_regime" in out.columns


def test_output_preserves_original_columns() -> None:
    close = 100 + np.arange(60, dtype=float) * 0.5
    df = _df(close)
    out = classify_regimes(df)
    for col in df.columns:
        assert col in out.columns
