from __future__ import annotations

import numpy as np
import pandas as pd

from src.research import binance_archive_extended_baselines as baseline


def _bars(last_close: float, *, last_delta: float = 0.0, last_vwap: float = 100.0) -> pd.DataFrame:
    count = baseline.WINDOW + 1
    close = np.full(count, 100.0)
    close[-1] = last_close
    delta = np.zeros(count)
    delta[-1] = last_delta
    vwap = np.full(count, 100.0)
    vwap[-1] = last_vwap
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-06-01", periods=count, freq="1min", tz="UTC"),
            "close": close,
            "volume": np.full(count, 10.0),
            "trade_delta": delta,
            "trade_vwap": vwap,
        }
    )


def test_trend_breakout_uses_only_prior_window() -> None:
    signal = baseline._trend_breakout_signal(_bars(101.0))

    assert signal.iloc[-1]["side"] == 1
    assert not signal.iloc[:-1]["side"].any()


def test_mean_reversion_fades_extreme_price() -> None:
    bars = _bars(105.0)
    bars.loc[: baseline.WINDOW - 1, "close"] = np.linspace(99.9, 100.1, baseline.WINDOW)

    signal = baseline._price_mean_reversion_signal(bars)

    assert signal.iloc[-1]["side"] == -1


def test_order_flow_impulse_follows_extreme_delta() -> None:
    bars = _bars(100.0, last_delta=10.0)
    bars.loc[: baseline.WINDOW - 1, "trade_delta"] = np.linspace(-1.0, 1.0, baseline.WINDOW)

    signal = baseline._order_flow_impulse_signal(bars)

    assert signal.iloc[-1]["side"] == 1


def test_vwap_reversion_fades_extreme_deviation() -> None:
    bars = _bars(101.0, last_vwap=100.0)
    bars.loc[: baseline.WINDOW - 1, "close"] = np.linspace(99.99, 100.01, baseline.WINDOW)

    signal = baseline._vwap_reversion_signal(bars)

    assert signal.iloc[-1]["side"] == -1
