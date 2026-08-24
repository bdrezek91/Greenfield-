"""src.engines.cross_market_evidence's CROSS_MARKET ConfirmationFamily
evidence producer (Cycle 44 - third FamilyEvidence producer). Uses a
real src.features.cross_market.cross_market_context_frame call (not a
hand-shaped fixture) since that function's own multi-asset panel
construction is exactly what this module's dispersion/rank inputs
depend on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.engines.contracts import ConfirmationFamily
from src.engines.cross_market_evidence import cross_market_family_evidence
from src.features.cross_market import cross_market_context_frame


def _panel(
    n: int = 30,
    *,
    final_leader: str | None = "BTC",
    final_dispersed: bool = True,
) -> pd.DataFrame:
    """Three assets, quiet and roughly correlated for the first n-1 bars
    (a real baseline for the dispersion z-score to measure against),
    then on the final bar either one asset breaks away (dispersed) or
    all three move together (not dispersed)."""
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(2)
    base_moves = rng.normal(0, 0.3, size=n)
    prices = {
        "BTC": 100 + np.cumsum(base_moves + rng.normal(0, 0.05, size=n)),
        "ETH": 50 + np.cumsum(base_moves + rng.normal(0, 0.05, size=n)),
        "SOL": 20 + np.cumsum(base_moves + rng.normal(0, 0.05, size=n)),
    }
    if final_dispersed and final_leader is not None:
        for asset in prices:
            bump = 3.0 if asset == final_leader else -1.0
            prices[asset][-1] = prices[asset][-2] + bump
    else:
        # All three move together - low cross-sectional dispersion.
        for asset in prices:
            prices[asset][-1] = prices[asset][-2] + 1.0

    rows = []
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
    return cross_market_context_frame(pd.DataFrame(rows), rolling_window=5)


def _asset_only(panel: pd.DataFrame, asset: str) -> pd.DataFrame:
    return panel[panel["asset"] == asset].drop(columns="asset").reset_index(drop=True)


def test_insufficient_history_returns_none() -> None:
    panel = _panel(n=10)

    assert cross_market_family_evidence(_asset_only(panel, "BTC")) is None


def test_top_ranked_asset_gets_positive_score() -> None:
    panel = _panel(final_leader="BTC", final_dispersed=True)

    evidence = cross_market_family_evidence(_asset_only(panel, "BTC"))

    assert evidence is not None
    assert evidence.family == ConfirmationFamily.CROSS_MARKET
    assert evidence.score > 0


def test_bottom_ranked_asset_gets_negative_score() -> None:
    panel = _panel(final_leader="BTC", final_dispersed=True)

    evidence = cross_market_family_evidence(_asset_only(panel, "SOL"))

    assert evidence is not None
    assert evidence.score < 0


def test_low_dispersion_dampens_conviction_toward_zero() -> None:
    """Same modest rank difference, but everything moves together on the
    final bar - conviction (and therefore |score|) should be smaller
    than a genuinely dispersed move with a similar rank."""
    dispersed = _panel(final_leader="BTC", final_dispersed=True)
    together = _panel(final_leader="BTC", final_dispersed=False)

    dispersed_evidence = cross_market_family_evidence(_asset_only(dispersed, "BTC"))
    together_evidence = cross_market_family_evidence(_asset_only(together, "BTC"))

    assert dispersed_evidence is not None
    assert together_evidence is not None
    assert abs(together_evidence.score) < abs(dispersed_evidence.score)


def test_missing_required_columns_raises() -> None:
    bad = pd.DataFrame({"timestamp": [pd.Timestamp.now(tz="UTC")]})
    with pytest.raises(ValueError, match="missing columns"):
        cross_market_family_evidence(bad)


def test_empty_frame_returns_none() -> None:
    panel = _panel(n=30)
    empty = _asset_only(panel, "BTC").iloc[:0]

    assert cross_market_family_evidence(empty) is None
