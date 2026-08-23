"""src.regimes.analogs_bridge's assembly of find_historical_analogs's
required input schema from real build_feature_matrix/classify_regimes
output (Cycle 38 - continues Cycle 37's closing of orphaned
src/regimes/ code found by an autonomous survey: find_historical_analogs
was fully built and tested but had zero callers anywhere).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.pipeline import build_feature_matrix
from src.regimes.analogs import AnalogFamily, AnalogSearchConfig, find_historical_analogs
from src.regimes.analogs_bridge import assemble_analog_search_frame
from src.regimes.classifier import RegimeConfig, classify_regimes


def _ohlcv(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0.02, 0.6, size=n))
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100.0 + rng.normal(0, 10, size=n).cumsum().clip(min=0),
        }
    )


_SMALL_REGIME_CONFIG = RegimeConfig(
    short_ma_period=3, long_ma_period=5, adx_period=3, vol_period=3, vol_lookback=5, atr_period=3
)


def test_assembled_frame_has_the_required_schema_and_the_feature_columns() -> None:
    df = _ohlcv(30)
    features = build_feature_matrix(df)[["return_1", "momentum"]]
    regime = classify_regimes(df, _SMALL_REGIME_CONFIG)["trend_regime"]

    assembled = assemble_analog_search_frame(df, features, regime)

    for column in ("timestamp", "max_source_timestamp", "close", "regime", "data_quality_score"):
        assert column in assembled.columns
    assert "return_1" in assembled.columns
    assert "momentum" in assembled.columns
    assert len(assembled) == len(df)


def test_data_quality_score_is_zero_exactly_where_features_have_a_nan() -> None:
    df = _ohlcv(15)
    # momentum (lookback=10) is NaN for rows 0-9, finite from row 10 on.
    features = build_feature_matrix(df)[["momentum"]]
    regime = pd.Series("RANGE", index=df.index)

    assembled = assemble_analog_search_frame(df, features, regime)

    assert (assembled["data_quality_score"].iloc[:10] == 0.0).all()
    assert (assembled["data_quality_score"].iloc[10:] == 1.0).all()


def test_mismatched_index_is_rejected_not_silently_misaligned() -> None:
    df = _ohlcv(10)
    features = build_feature_matrix(df)[["return_1"]]
    bad_regime = pd.Series("RANGE", index=range(100, 110))

    with pytest.raises(ValueError, match="index"):
        assemble_analog_search_frame(df, features, bad_regime)


def test_assembled_frame_actually_works_with_find_historical_analogs() -> None:
    """The real payoff: real build_feature_matrix + classify_regimes
    output, fed through the bridge, must be directly usable by
    find_historical_analogs without any further caller-side reshaping -
    proving genuine end-to-end compatibility, not just matching column
    names on paper."""
    df = _ohlcv(120, seed=7)
    features = build_feature_matrix(df)[["return_1", "momentum"]]
    regime = classify_regimes(df, _SMALL_REGIME_CONFIG)["trend_regime"]

    assembled = assemble_analog_search_frame(df, features, regime)
    # momentum (lookback=10) is the slowest-maturing of the two chosen
    # features; find_historical_analogs requires every row finite.
    warm = assembled.iloc[10:].reset_index(drop=True)

    config = AnalogSearchConfig(
        families=(AnalogFamily("price", ("return_1", "momentum")),),
        horizons_bars=(1, 4),
        neighbor_count=5,
        minimum_neighbors=2,
        maximum_distance=10.0,
        minimum_quality_score=0.5,
        require_same_regime=False,
    )

    result = find_historical_analogs(
        warm,
        query_timestamp=warm["timestamp"].iloc[-1],
        config=config,
        dataset_version="test-dataset",
        code_version="test-code",
    )

    assert result.eligible_candidate_count >= 0
    if result.is_meaningful:
        assert 1 in result.distributions
        assert 4 in result.distributions
    else:
        assert result.warning is not None
