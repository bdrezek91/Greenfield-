from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.regimes.analogs import (
    AnalogFamily,
    AnalogSearchConfig,
    find_historical_analogs,
)


def _config(**changes: object) -> AnalogSearchConfig:
    base = AnalogSearchConfig(
        families=(
            AnalogFamily("price_auction", ("momentum", "volatility")),
            AnalogFamily("flow", ("signed_flow",)),
            AnalogFamily("derivatives", ("funding", "oi_change")),
        ),
        horizons_bars=(2, 6),
        neighbor_count=8,
        minimum_neighbors=3,
        maximum_distance=1.5,
        minimum_quality_score=0.8,
    )
    return replace(base, **changes)


def _frame(periods: int = 120) -> pd.DataFrame:
    index = np.arange(periods)
    timestamps = pd.date_range("2025-01-01", periods=periods, freq="h", tz="UTC")
    phase = index % 12
    close = 100 * np.exp(np.cumsum(0.001 + 0.002 * np.sin(index / 4)))
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "max_source_timestamp": timestamps - pd.Timedelta(milliseconds=5),
            "asset": "BTC",
            "close": close,
            "regime": "RANGE",
            "data_quality_score": 1.0,
            "momentum": np.sin(phase / 2),
            "volatility": 0.2 + 0.02 * np.cos(phase / 3),
            "signed_flow": np.cos(phase / 2),
            "funding": 0.0001 * np.sin(phase / 4),
            "oi_change": 0.01 * np.cos(phase / 4),
        }
    )


def _search(frame: pd.DataFrame, **config_changes: object):
    return find_historical_analogs(
        frame,
        query_timestamp=frame["timestamp"].iloc[-1],
        config=_config(**config_changes),
        dataset_version="dataset-sha256",
        code_version="commit-sha",
    )


def test_returns_transparent_neighbors_and_forward_risk_distributions() -> None:
    frame = _frame()
    result = _search(frame)

    assert result.is_meaningful
    assert result.warning is None
    assert result.dataset_version == "dataset-sha256"
    assert result.code_version == "commit-sha"
    assert len(result.configuration_fingerprint) == 64
    assert len(result.neighbors) == 8
    assert [neighbor.distance for neighbor in result.neighbors] == sorted(
        neighbor.distance for neighbor in result.neighbors
    )
    assert set(result.neighbors[0].family_distances) == {
        "price_auction",
        "flow",
        "derivatives",
    }
    latest_eligible = frame["timestamp"].iloc[-1 - max(_config().horizons_bars)]
    assert all(neighbor.timestamp_utc <= latest_eligible for neighbor in result.neighbors)
    timestamp_to_index = {timestamp: index for index, timestamp in enumerate(frame["timestamp"])}
    neighbor_indices = [timestamp_to_index[neighbor.timestamp_utc] for neighbor in result.neighbors]
    assert all(
        abs(left - right) > max(_config().horizons_bars)
        for position, left in enumerate(neighbor_indices)
        for right in neighbor_indices[position + 1 :]
    )
    for horizon, distribution in result.distributions.items():
        assert horizon in {2, 6}
        assert distribution.sample_size == 8
        assert 0 <= distribution.positive_probability <= 1
        assert distribution.return_q10 <= distribution.return_q90
        assert distribution.adverse_return_q10 <= distribution.favorable_return_q90


def test_appended_future_rows_cannot_change_historical_query() -> None:
    frame = _frame()
    query_timestamp = frame["timestamp"].iloc[89]
    baseline = find_historical_analogs(
        frame.iloc[:90],
        query_timestamp=query_timestamp,
        config=_config(),
        dataset_version="v1",
        code_version="c1",
    )
    revised = find_historical_analogs(
        frame,
        query_timestamp=query_timestamp,
        config=_config(),
        dataset_version="v1",
        code_version="c1",
    )

    assert revised == baseline


def test_configuration_fingerprint_changes_with_search_contract() -> None:
    frame = _frame()
    baseline = _search(frame)
    changed = _search(frame, maximum_distance=2.0)

    assert changed.configuration_fingerprint != baseline.configuration_fingerprint


def test_regime_quality_and_distance_gates_return_explicit_no_analog() -> None:
    frame = _frame()
    incompatible = frame.copy()
    incompatible.loc[incompatible.index[-1], "regime"] = "LIQUIDATION_CASCADE"
    result = _search(incompatible)
    assert not result.is_meaningful
    assert result.warning == "no_regime_and_quality_compatible_history"

    low_quality = frame.copy()
    low_quality.loc[low_quality.index[-1], "data_quality_score"] = 0.1
    result = _search(low_quality)
    assert result.warning == "query_quality_below_threshold"

    distant = frame.copy()
    distant.loc[distant.index[-1], "momentum"] = 1_000
    result = _search(distant, maximum_distance=0.001)
    assert not result.is_meaningful
    assert result.warning == "insufficient_similar_neighbors"
    assert result.distributions == {}


def test_insufficient_history_respects_forward_outcome_embargo() -> None:
    frame = _frame(periods=6)
    result = _search(frame)

    assert not result.is_meaningful
    assert result.warning == "insufficient_history_for_outcome_embargo"
    assert result.neighbors == ()


def test_rejects_future_sources_duplicates_mixed_assets_and_bad_versions() -> None:
    frame = _frame()
    future = frame.copy()
    future.loc[0, "max_source_timestamp"] = future.loc[0, "timestamp"] + pd.Timedelta(seconds=1)
    with pytest.raises(ValueError, match="future source"):
        _search(future)

    with pytest.raises(ValueError, match="duplicate timestamps"):
        _search(pd.concat([frame, frame.iloc[[0]]]))

    mixed = frame.copy()
    mixed.loc[0, "asset"] = "ETH"
    with pytest.raises(ValueError, match="cannot mix assets"):
        _search(mixed)

    with pytest.raises(ValueError, match="dataset and code versions"):
        find_historical_analogs(
            frame,
            query_timestamp=frame["timestamp"].iloc[-1],
            config=_config(),
            dataset_version=" ",
            code_version="c1",
        )


def test_configuration_prevents_duplicate_family_evidence() -> None:
    with pytest.raises(ValueError, match="multiple analog families"):
        AnalogSearchConfig(
            families=(
                AnalogFamily("price", ("momentum",)),
                AnalogFamily("flow", ("momentum",)),
            )
        )
    with pytest.raises(ValueError, match="positive ascending"):
        replace(_config(), horizons_bars=(6, 2))
