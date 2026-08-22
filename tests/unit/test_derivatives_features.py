from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.derivatives import derivatives_context_frame


def _derivatives(rows: int = 120) -> pd.DataFrame:
    timestamp = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    trend = np.linspace(100, 110, rows)
    cycle = np.sin(np.arange(rows) / 5.0)
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "max_source_timestamp": timestamp,
            "mark_price": trend + cycle + 0.05,
            "index_price": trend + cycle,
            "open_interest": 1_000 + np.arange(rows) * 2 + cycle * 5,
            "funding_rate": 0.0001 + cycle * 0.00002,
            "long_short_ratio": 1.1 + cycle * 0.05,
            "long_liquidation_volume": np.arange(rows) % 7,
            "short_liquidation_volume": np.arange(rows) % 5,
        }
    )


def test_derivatives_context_is_causal_and_finite_after_warmup() -> None:
    result = derivatives_context_frame(_derivatives(), rolling_window=20)
    mature = result.iloc[20:]

    assert (result["max_source_timestamp"] <= result["timestamp"]).all()
    assert np.isfinite(mature.select_dtypes(include="number").to_numpy()).all()
    assert result["liquidation_imbalance"].between(-1, 1).all()
    assert result["basis_bps"].abs().max() < 100
    assert "derivatives_crowding_score" in result


def test_derivatives_context_does_not_change_with_future_rows() -> None:
    frame = _derivatives()
    short = derivatives_context_frame(frame.iloc[:80], rolling_window=20)
    full = derivatives_context_frame(frame, rolling_window=20).iloc[:80]

    pd.testing.assert_frame_equal(short.reset_index(drop=True), full.reset_index(drop=True))


def test_derivatives_context_supports_missing_optional_positioning() -> None:
    frame = _derivatives().drop(
        columns=[
            "long_short_ratio",
            "long_liquidation_volume",
            "short_liquidation_volume",
        ]
    )
    result = derivatives_context_frame(frame, rolling_window=20)

    assert result["liquidation_total"].isna().all()
    assert result["derivatives_crowding_score"].iloc[20:].notna().all()


def test_derivatives_context_fails_closed_on_invalid_lineage_or_values() -> None:
    frame = _derivatives(10)
    future = frame.copy()
    future.loc[0, "max_source_timestamp"] = future.loc[1, "timestamp"]
    with pytest.raises(ValueError, match="future source"):
        derivatives_context_frame(future, rolling_window=3)
    with pytest.raises(ValueError, match="missing columns"):
        derivatives_context_frame(frame.drop(columns="open_interest"), rolling_window=3)
    invalid = frame.copy()
    invalid.loc[0, "long_short_ratio"] = 0
    with pytest.raises(ValueError, match="must be positive"):
        derivatives_context_frame(invalid, rolling_window=3)
