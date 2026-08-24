"""src.engines.regime_analog_evidence's REGIME_ANALOG ConfirmationFamily
evidence producer (Cycle 46 - fifth FamilyEvidence producer). Reuses the
same real build_feature_matrix + classify_regimes + find_historical_
analogs pipeline tests/unit/test_analogs_bridge.py (Cycle 38) proved
produces a genuine is_meaningful=True result, rather than a hand-shaped
HistoricalAnalogResult - this family's own quality/causality machinery
is already real, so the evidence-producer test should exercise it for
real too.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.engines.contracts import ConfirmationFamily
from src.engines.regime_analog_evidence import regime_analog_family_evidence
from src.features.pipeline import build_feature_matrix
from src.regimes.analogs import AnalogFamily, AnalogSearchConfig, find_historical_analogs
from src.regimes.analogs_bridge import assemble_analog_search_frame
from src.regimes.classifier import RegimeConfig, classify_regimes

_SMALL_REGIME_CONFIG = RegimeConfig(
    short_ma_period=3, long_ma_period=5, adx_period=3, vol_period=3, vol_lookback=5, atr_period=3
)


def _ohlcv(n: int, seed: int = 7) -> pd.DataFrame:
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


def _real_meaningful_result(horizons_bars: tuple[int, ...] = (1, 4)):
    df = _ohlcv(120)
    features = build_feature_matrix(df)[["return_1", "momentum"]]
    regime = classify_regimes(df, _SMALL_REGIME_CONFIG)["trend_regime"]
    assembled = assemble_analog_search_frame(df, features, regime)
    warm = assembled.iloc[10:].reset_index(drop=True)

    config = AnalogSearchConfig(
        families=(AnalogFamily("price", ("return_1", "momentum")),),
        horizons_bars=horizons_bars,
        neighbor_count=5,
        minimum_neighbors=2,
        maximum_distance=10.0,
        minimum_quality_score=0.5,
        require_same_regime=False,
    )
    return find_historical_analogs(
        warm,
        query_timestamp=warm["timestamp"].iloc[-1],
        config=config,
        dataset_version="test-dataset",
        code_version="test-code",
    )


def test_real_meaningful_result_produces_real_evidence() -> None:
    result = _real_meaningful_result()
    assert result.is_meaningful  # sanity check on the fixture itself

    evidence = regime_analog_family_evidence(result, horizon_bars=1)

    assert evidence is not None
    assert evidence.family == ConfirmationFamily.REGIME_ANALOG
    assert -1.0 <= evidence.score <= 1.0
    assert 0.0 < evidence.confidence <= 1.0
    assert str(result.regime) in evidence.rationale


def test_score_direction_matches_positive_probability() -> None:
    result = _real_meaningful_result()
    distribution = result.distributions[1]

    evidence = regime_analog_family_evidence(result, horizon_bars=1)

    assert evidence is not None
    if distribution.positive_probability > 0.5:
        assert evidence.score > 0
    elif distribution.positive_probability < 0.5:
        assert evidence.score < 0
    else:
        assert evidence.score == 0.0


def test_not_meaningful_result_returns_none() -> None:
    result = _real_meaningful_result()
    not_meaningful = replace(result, is_meaningful=False)

    assert regime_analog_family_evidence(not_meaningful, horizon_bars=1) is None


def test_unrequested_horizon_returns_none() -> None:
    result = _real_meaningful_result(horizons_bars=(1, 4))

    assert regime_analog_family_evidence(result, horizon_bars=99) is None


def test_confidence_scales_with_sample_size() -> None:
    result = _real_meaningful_result()
    distribution = result.distributions[1]

    low_baseline = regime_analog_family_evidence(
        result, horizon_bars=1, confidence_full_sample_size=distribution.sample_size
    )
    high_baseline = regime_analog_family_evidence(
        result, horizon_bars=1, confidence_full_sample_size=distribution.sample_size * 10
    )

    assert low_baseline is not None
    assert high_baseline is not None
    assert low_baseline.confidence == 1.0
    assert high_baseline.confidence < 1.0


def test_non_positive_confidence_full_sample_size_raises() -> None:
    result = _real_meaningful_result()
    with pytest.raises(ValueError, match="positive"):
        regime_analog_family_evidence(result, horizon_bars=1, confidence_full_sample_size=0)
