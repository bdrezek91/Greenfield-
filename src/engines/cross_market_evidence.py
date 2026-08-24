"""Research-stage v1: build one CROSS_MARKET ConfirmationFamily
FamilyEvidence from src.features.cross_market.cross_market_context_frame's
own output (Cycle 30, pre-filtered by the caller to one asset - same
convention as src.features.pipeline's `cross_market_context` extra,
Cycle 30).

Third of six ConfirmationFamily evidence producers (see
src/engines/derivatives_evidence.py's module docstring for the full
"one family, one established idea, research-stage v1" rationale).

Uses cross-sectional rank, a well-established idea in relative-strength/
cross-sectional momentum trading (rank assets by relative performance;
extreme ranks are the tradeable signal) rather than inventing a new one:

    Direction/magnitude comes directly from `cross_sectional_return_rank`
    (already bounded [0, 1] by construction - a percentile rank of this
    asset's own return within the universe at each timestamp) linearly
    remapped to [-1, 1] - top-ranked assets score near +1, bottom-ranked
    near -1, median near 0. No z-scoring needed: rank is already
    naturally bounded and comparable across assets/regimes, unlike a raw
    return.
    CONVICTION comes from `cross_asset_return_dispersion` (also already
    computed by cross_market_context_frame): a rank signal is more
    meaningful when the cross-section is genuinely differentiating
    (dispersion is currently high relative to its own history) and less
    meaningful when everything is moving in lockstep (low dispersion -
    small, noisy differences producing an arbitrary-looking rank). This
    module z-scores dispersion itself (not provided pre-scored) and maps
    it through a sigmoid - the same smooth zscore-to-[0,1] conviction
    transform src.regimes.multidomain already uses for
    `liquidity_stress_score` (Cycle 37), not a new invented shape.

Deliberately NOT incorporated in this v1: `benchmark_rolling_correlation`/
`benchmark_lead_correlation`/`spot_perpetual_basis_bps` - each is a
plausible refinement (e.g. discount rank signals when correlation with
the benchmark is unusually low/unstable) but stacking more ideas into one
score trades away auditability, the same reasoning as Cycles 42-43's
exclusions. Refining this is exactly the training-data-only research
docs/GREENFIELD_V2_MASTER_PLAN.md section 10.2 describes.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.engines.contracts import ConfirmationFamily, FamilyEvidence


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def cross_market_family_evidence(
    cross_market_context: pd.DataFrame,
    *,
    dispersion_zscore_window: int = 20,
) -> FamilyEvidence | None:
    """Build one FamilyEvidence(family=CROSS_MARKET) from the LATEST row
    of an already-computed, single-asset
    src.features.cross_market.cross_market_context_frame output
    (`cross_market_context`, sorted here by `timestamp`).

    Returns `None` (not a synthetic zero-quality entry) when there isn't
    enough history for `cross_asset_return_dispersion`'s rolling z-score
    to mature or the latest row's inputs are missing - same reasoning as
    src.engines.derivatives_evidence.derivatives_family_evidence.
    """
    required = {
        "timestamp",
        "max_source_timestamp",
        "cross_sectional_return_rank",
        "cross_asset_return_dispersion",
    }
    missing = sorted(required - set(cross_market_context.columns))
    if missing:
        raise ValueError(f"cross-market evidence frame missing columns: {missing}")
    if cross_market_context.empty:
        return None

    ordered = cross_market_context.sort_values("timestamp").reset_index(drop=True)
    dispersion = ordered["cross_asset_return_dispersion"].astype(float)
    window = dispersion.rolling(dispersion_zscore_window, min_periods=dispersion_zscore_window)
    dispersion_zscore = (dispersion - window.mean()) / window.std(ddof=0).replace(0, np.nan)

    latest_rank = ordered["cross_sectional_return_rank"].iloc[-1]
    latest_dispersion_zscore = dispersion_zscore.iloc[-1]

    if pd.isna(latest_rank) or pd.isna(latest_dispersion_zscore):
        return None

    conviction = _sigmoid(float(latest_dispersion_zscore))
    score = max(-1.0, min(1.0, 2.0 * (float(latest_rank) - 0.5) * conviction))
    rationale = (
        f"cross-sectional return rank {latest_rank:.2f} (0=weakest, 1=strongest), "
        f"dispersion z={latest_dispersion_zscore:+.2f} over {dispersion_zscore_window} bars "
        f"(conviction {conviction:.2f})"
    )

    return FamilyEvidence(
        family=ConfirmationFamily.CROSS_MARKET,
        score=score,
        confidence=1.0,
        quality=1.0,
        max_source_timestamp_utc=ordered["max_source_timestamp"].iloc[-1].to_pydatetime(),
        component_ids=("cross_sectional_return_rank", "cross_asset_return_dispersion"),
        rationale=rationale,
    )
