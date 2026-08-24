"""Research-stage v1: build one DERIVATIVES ConfirmationFamily FamilyEvidence
from src.features.derivatives.derivatives_context_frame's own output
(Cycle 29).

This is the first of six ConfirmationFamily evidence producers - the
missing layer an autonomous survey found before Cycle 37 (nothing in
this repo produced FamilyEvidence at all, so src/engines/'s fully-built,
fully-tested Setup/Directional/Neutral/Meta engines were entirely
unreachable). Unlike Cycles 26-41's mechanical bridges (rename a column,
convert units, as-of join an already-defined quantity), a FamilyEvidence
score/confidence/quality genuinely has to MEAN something about trade
direction - this module makes that meaning explicit and traceable to
ONE established, uncontroversial idea, not a stack of several invented
heuristics, and stays deliberately narrow:

    Direction comes from price (mark_return, z-scored over
    `mark_return_zscore_window` bars so its magnitude is comparable
    across symbols/regimes, then tanh-bounded to [-1, 1]).
    CONVICTION comes from whether open interest CONFIRMS that move
    (`oi_price_confirmation`, already computed by derivatives_context_
    frame: +1 when OI moves with price - real new positioning behind the
    move - 0 when one side didn't move, -1 when OI moves AGAINST price -
    a short-covering rally or a long-liquidation selloff, i.e. the move
    lacks real conviction). Score is fully zeroed when OI contradicts
    price - a well-established "smart money confirmation" heuristic
    (real positioning behind a move vs. a move driven by closing
    existing positions), not a data-mined threshold.

Deliberately NOT incorporated into score in this v1: funding_zscore,
basis_zscore, derivatives_crowding_score, liquidation_imbalance. Each of
those could plausibly refine or contradict the price/OI signal above
(e.g. extreme crowding as a contrarian dampener is a real, common
heuristic too) - but stacking multiple interacting, less-established
ideas into one opaque score in a single autonomous pass would trade
away exactly the auditability every other cycle in this project has
insisted on. Per docs/GREENFIELD_V2_MASTER_PLAN.md section 10.2,
"confirmation thresholds and weights are fit without access to holdout
data" - refining this scoring rule (or adding the other components) is
exactly the kind of training-data-only research this module's docstring
flags as the natural next step, not something to rush here.

This module does not wire into any live/paper path, does not touch
capital, and produces evidence usable only in a backtest/research
context via src.engines.directional.evaluate_directional_setup - it is
Research-stage input to that engine's own promotion pipeline (Research
-> OOS candidate -> Shadow -> Paper -> LIVE_SMALL -> LIVE, master plan
section 14), not something already validated by it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.engines.contracts import ConfirmationFamily, FamilyEvidence


def derivatives_family_evidence(
    context: pd.DataFrame,
    *,
    mark_return_zscore_window: int = 20,
) -> FamilyEvidence | None:
    """Build one FamilyEvidence(family=DERIVATIVES) from the LATEST row of
    an already-computed src.features.derivatives.derivatives_context_frame
    output (`context`, sorted or unsorted - sorted here by `timestamp`).

    Returns `None` (not a synthetic zero-quality entry) when there isn't
    enough history for the rolling z-score to mature or the latest row's
    inputs are missing - the caller simply omits this family's vote for
    that decision, rather than every decision being forced to WAIT by an
    included-but-useless placeholder (see
    src.engines.directional.evaluate_directional_setup's own
    "STALE_OR_LOW_QUALITY_EVIDENCE" path, which fires whenever ANY
    included evidence item fails its quality gate - a caller should
    never hand it evidence it already knows is unusable).
    """
    required = {"timestamp", "max_source_timestamp", "mark_return", "oi_price_confirmation"}
    missing = sorted(required - set(context.columns))
    if missing:
        raise ValueError(f"derivatives evidence frame missing columns: {missing}")
    if context.empty:
        return None

    ordered = context.sort_values("timestamp").reset_index(drop=True)
    mark_return = ordered["mark_return"].astype(float)
    window = mark_return.rolling(mark_return_zscore_window, min_periods=mark_return_zscore_window)
    mean = window.mean()
    std = window.std(ddof=0)
    zscore = (mark_return - mean) / std.replace(0, np.nan)

    latest = ordered.iloc[-1]
    latest_zscore = zscore.iloc[-1]
    oi_confirmation = latest["oi_price_confirmation"]
    latest_return = latest["mark_return"]

    if pd.isna(latest_zscore) or pd.isna(oi_confirmation) or pd.isna(latest_return):
        return None

    conviction = 1.0 if oi_confirmation > 0 else (0.0 if oi_confirmation < 0 else 0.5)
    score = max(-1.0, min(1.0, float(np.tanh(latest_zscore)) * conviction))
    confidence = 1.0 if oi_confirmation != 0 else 0.5
    direction = "up" if latest_return > 0 else ("down" if latest_return < 0 else "flat")
    if oi_confirmation > 0:
        confirm_word = "confirmed"
    elif oi_confirmation < 0:
        confirm_word = "contradicted"
    else:
        confirm_word = "ambiguous"
    rationale = (
        f"mark price {direction} ({latest_return:+.4%}, z={latest_zscore:+.2f} over "
        f"{mark_return_zscore_window} bars), open interest {confirm_word} the move"
    )

    return FamilyEvidence(
        family=ConfirmationFamily.DERIVATIVES,
        score=score,
        confidence=confidence,
        quality=1.0,
        max_source_timestamp_utc=latest["max_source_timestamp"].to_pydatetime(),
        component_ids=("mark_return", "oi_price_confirmation"),
        rationale=rationale,
    )
