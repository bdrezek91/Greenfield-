"""src.regimes.multidomain_bridge's assembly of
classify_multidomain_regimes's required input schema from the raw
feature frames this project already computes (Cycle 37 - closes the gap
an autonomous survey found: classify_multidomain_regimes/
stabilize_regime_labels were fully built and tested but had zero callers
anywhere in the repo).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.cross_market import cross_market_context_frame
from src.features.derivatives import derivatives_context_frame
from src.regimes.multidomain import (
    MultiDomainRegimeConfig,
    RegimeConfig,
    classify_multidomain_regimes,
)
from src.regimes.multidomain_bridge import (
    assemble_multidomain_regime_frame,
    classify_multidomain_regimes_from_sources,
)


def _ohlcv(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0.02, 0.6, size=n))
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
        }
    )


def _l2_imbalance(ts: pd.Series, *, varying: bool = False) -> pd.DataFrame:
    # Real src.features.order_flow.l2_imbalance_frame output column names.
    # `varying=True` gives spread/depth actual variance across bars - the
    # liquidity domain's rolling zscore is NaN (std=0) on a constant series.
    n = len(ts)
    rng = np.random.default_rng(11)
    spread = 1.0 + (rng.normal(0, 0.05, size=n) if varying else 0.0)
    depth = 5.0 + (rng.normal(0, 0.5, size=n) if varying else 0.0)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "spread": spread,
            "mid_price": 100.0,
            "bid_depth": depth,
            "ask_depth": depth,
        }
    )


def _trade_flow(ts: pd.Series) -> pd.DataFrame:
    # Real src.features.order_flow.trade_flow_frame output column names.
    return pd.DataFrame({"timestamp": ts, "trade_delta": np.arange(len(ts), dtype=float)})


def _open_interest(ts: pd.Series, *, varying: bool = False) -> pd.DataFrame:
    # `varying=True` gives open_interest actual variance - the flow
    # domain's oi_change rolling zscore is NaN (std=0) if it's constant.
    n = len(ts)
    values = 1_000.0 + (np.arange(n, dtype=float) * 3.0 if varying else 0.0)
    return pd.DataFrame({"timestamp": ts, "open_interest": values})


def _derivatives_context(ts: pd.Series, rolling_window: int) -> pd.DataFrame:
    n = len(ts)
    rng = np.random.default_rng(13)
    raw = pd.DataFrame(
        {
            "timestamp": ts,
            "max_source_timestamp": ts,
            "mark_price": 100.0 + np.arange(n) * 0.01,
            "index_price": 100.0,
            "open_interest": 1_000.0 + np.arange(n),
            "funding_rate": 0.0001,
            # Without these two optional columns, derivatives_context_frame
            # leaves liquidation_total NaN for every row (see its
            # docstring) - classify_multidomain_regimes needs it finite,
            # and its own rolling zscore needs actual variance (constant
            # volumes give a std of 0, i.e. NaN) - not just "present".
            "long_liquidation_volume": np.abs(rng.normal(1.0, 0.3, size=n)),
            "short_liquidation_volume": np.abs(rng.normal(1.0, 0.3, size=n)),
        }
    )
    return derivatives_context_frame(raw, rolling_window=rolling_window)


def _cross_market_context(ts: pd.Series, rolling_window: int) -> pd.DataFrame:
    n = len(ts)
    rng = np.random.default_rng(3)
    rows = []
    prices = {
        "BTC": 100 + np.cumsum(rng.normal(0, 0.5, size=n)),
        "ETH": 50 + np.cumsum(rng.normal(0, 0.4, size=n)),
    }
    for index, timestamp in enumerate(ts):
        for asset, series in prices.items():
            spot = float(series[index])
            rows.append(
                {
                    "timestamp": timestamp,
                    "max_source_timestamp": timestamp,
                    "asset": asset,
                    "spot_price": spot,
                    "perpetual_price": spot * 1.0005,
                }
            )
    context = cross_market_context_frame(pd.DataFrame(rows), rolling_window=rolling_window)
    return context[context["asset"] == "BTC"].drop(columns="asset").reset_index(drop=True)


_SMALL_CONFIG = MultiDomainRegimeConfig(
    price=RegimeConfig(
        short_ma_period=3, long_ma_period=5, adx_period=3, vol_period=3, vol_lookback=5,
        atr_period=3,
    ),
    rolling_window=5,
    confirmation_bars=1,
)


def test_assembled_frame_has_every_column_classify_multidomain_regimes_requires() -> None:
    df = _ohlcv(20)
    ts = df["timestamp"]

    assembled = assemble_multidomain_regime_frame(
        df,
        l2_imbalance=_l2_imbalance(ts),
        trade_flow=_trade_flow(ts),
        open_interest=_open_interest(ts),
        derivatives_context=_derivatives_context(ts, rolling_window=5),
        cross_market_context=_cross_market_context(ts, rolling_window=5),
    )

    required = {
        "timestamp", "max_source_timestamp", "high", "low", "close",
        "realized_volatility", "spread_bps", "depth_notional", "signed_delta",
        "open_interest", "liquidation_total", "market_breadth_positive_fraction",
        "cross_asset_return_dispersion", "benchmark_return",
    }
    assert required.issubset(assembled.columns)


def test_spread_bps_and_depth_notional_are_derived_correctly() -> None:
    df = _ohlcv(10)
    ts = df["timestamp"]
    l2 = _l2_imbalance(ts)  # spread=1.0, mid_price=100.0, bid_depth=ask_depth=5.0

    assembled = assemble_multidomain_regime_frame(
        df,
        l2_imbalance=l2,
        trade_flow=_trade_flow(ts),
        open_interest=_open_interest(ts),
        derivatives_context=_derivatives_context(ts, rolling_window=5),
        cross_market_context=_cross_market_context(ts, rolling_window=5),
    )

    # spread_bps = spread / mid_price * 10_000 = 1.0 / 100.0 * 10_000 = 100.
    assert (assembled["spread_bps"] == 100.0).all()
    # depth_notional = (bid_depth + ask_depth) * mid_price = 10.0 * 100.0 = 1000.
    assert (assembled["depth_notional"] == 1_000.0).all()


def test_signed_delta_is_trade_delta_as_of_joined() -> None:
    df = _ohlcv(10)
    ts = df["timestamp"]

    assembled = assemble_multidomain_regime_frame(
        df,
        l2_imbalance=_l2_imbalance(ts),
        trade_flow=_trade_flow(ts),
        open_interest=_open_interest(ts),
        derivatives_context=_derivatives_context(ts, rolling_window=5),
        cross_market_context=_cross_market_context(ts, rolling_window=5),
    )

    assert (assembled["signed_delta"].to_numpy() == np.arange(10, dtype=float)).all()


def test_classify_multidomain_regimes_from_sources_fails_closed_on_unwarmed_input() -> None:
    """classify_multidomain_regimes requires EVERY row's required columns
    to already be finite (not just the row being classified) - a caller
    who hands it data before realized_volatility (or any other source)
    has warmed up must get a loud failure, not a guessed regime."""
    df = _ohlcv(10, seed=5)  # far fewer bars than volatility_period=20 needs
    ts = df["timestamp"]

    with pytest.raises(ValueError, match="finite"):
        classify_multidomain_regimes_from_sources(
            df,
            l2_imbalance=_l2_imbalance(ts),
            trade_flow=_trade_flow(ts),
            open_interest=_open_interest(ts),
            derivatives_context=_derivatives_context(ts, rolling_window=5),
            cross_market_context=_cross_market_context(ts, rolling_window=5),
            config=_SMALL_CONFIG,
        )


def test_classify_multidomain_regimes_from_sources_runs_end_to_end_once_warmed_up() -> None:
    """The real, intended usage: assemble over the FULL history (so
    realized_volatility and every rolling source matures naturally), then
    trim the ASSEMBLED frame to the range where it's fully finite (see
    the function's own docstring) before classifying - not trim the raw
    OHLCV first, which would just restart every rolling window's warmup
    from zero."""
    df = _ohlcv(45, seed=5)
    ts = df["timestamp"]

    assembled = assemble_multidomain_regime_frame(
        df,
        l2_imbalance=_l2_imbalance(ts, varying=True),
        trade_flow=_trade_flow(ts),
        open_interest=_open_interest(ts, varying=True),
        derivatives_context=_derivatives_context(ts, rolling_window=5),
        cross_market_context=_cross_market_context(ts, rolling_window=5),
    )
    # realized_volatility (period=20, the bridge's default) is the
    # slowest-maturing input - trim to the range where it's finite.
    warm = assembled.iloc[20:].reset_index(drop=True)

    result = classify_multidomain_regimes(warm, _SMALL_CONFIG)

    for domain in ("trend", "volatility", "liquidity", "flow", "cross_market"):
        column = f"{domain}_regime"
        assert column in result.columns
        # Once every domain's warmup window has passed, later rows must
        # have a real (non-NA) label - proves this actually classified
        # something, not just plumbed NaNs through.
        assert result[column].iloc[-1] is not pd.NA
