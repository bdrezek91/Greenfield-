"""Research-stage v1: build one VOLATILITY_OPTIONS ConfirmationFamily
FamilyEvidence from src.features.options.build_option_surface_snapshot's
own output (Cycle 36).

Sixth and last of six ConfirmationFamily evidence producers (see
src/engines/derivatives_evidence.py's module docstring for the full
"one family, one established idea, research-stage v1" rationale).

Uses 25-delta risk reversal, THE standard directional options-market
skew reading (FX and equity vol desks alike): `risk_reversal_25d` is
defined (src/features/options.py) as call_25d_iv - put_25d_iv. A
POSITIVE risk reversal means 25-delta calls are relatively more
expensive than 25-delta puts - the market paying up for upside exposure/
protection, read as a bullish skew. A NEGATIVE risk reversal is the
bearish mirror (puts bid up - downside fear/hedging demand). This is the
nearest expiry's own already-computed field, not a new formula.

    Direction/magnitude: risk_reversal_25d normalized by that expiry's
    own atm_iv (so a given number of vol points of skew means the same
    thing whether ambient volatility is 20 or 80) and tanh-bounded.
    CONFIDENCE: `accepted_quote_count / (accepted_quote_count +
    rejected_quote_count)` - the surface's own quality-gate pass rate,
    already computed by build_option_surface_snapshot. A mechanical
    "how much of the raw quote universe survived quality gates" measure,
    not a new heuristic.

Only the NEAREST expiry (`snapshot.expiries[0]`, already the near-dated
one - build_option_surface_snapshot sorts them) is used - near-dated
skew is where short-term directional options-market signal
conventionally concentrates; using every expiry's skew, or the
term-structure slope, or implied-vs-realized spread, would each be a
plausible refinement but (as in every prior family) stacking more ideas
into one score trades away auditability. Refining this is exactly the
training-data-only research docs/GREENFIELD_V2_MASTER_PLAN.md section
10.2 describes.
"""

from __future__ import annotations

import numpy as np

from src.engines.contracts import ConfirmationFamily, FamilyEvidence
from src.features.options import OptionSurfaceSnapshot


def volatility_options_family_evidence(
    snapshot: OptionSurfaceSnapshot,
) -> FamilyEvidence | None:
    """Build one FamilyEvidence(family=VOLATILITY_OPTIONS) from a
    src.features.options.build_option_surface_snapshot result.

    Returns `None` (not a synthetic zero-quality entry) when the surface
    has no expiries, or the nearest expiry's `risk_reversal_25d` is
    `None` (not enough 25-delta call/put coverage near that target delta
    to compute one - live-verified in Cycle 36 to happen often with a
    narrow near-ATM instrument selection).
    """
    if not snapshot.expiries:
        return None
    nearest = snapshot.expiries[0]
    if nearest.risk_reversal_25d is None:
        return None

    denom = nearest.atm_iv if nearest.atm_iv > 0 else 1.0
    score = max(-1.0, min(1.0, float(np.tanh(nearest.risk_reversal_25d / denom))))
    total_quotes = snapshot.accepted_quote_count + snapshot.rejected_quote_count
    confidence = snapshot.accepted_quote_count / total_quotes if total_quotes > 0 else 0.0
    direction = "bullish" if nearest.risk_reversal_25d > 0 else "bearish"
    rationale = (
        f"25-delta risk reversal {nearest.risk_reversal_25d:+.2f} vol points "
        f"({direction} skew) on the {nearest.days_to_expiry:.1f}-day expiry, "
        f"atm_iv={nearest.atm_iv:.2f}"
    )

    return FamilyEvidence(
        family=ConfirmationFamily.VOLATILITY_OPTIONS,
        score=score,
        confidence=confidence,
        quality=1.0,
        max_source_timestamp_utc=snapshot.max_source_timestamp_utc,
        component_ids=("risk_reversal_25d", "atm_iv"),
        rationale=rationale,
    )
