"""Research-stage v1: build one ORDER_FLOW ConfirmationFamily FamilyEvidence
from src.features.order_flow.trade_flow_frame's own output (Cycle 26).

Second of six ConfirmationFamily evidence producers (see
src/engines/derivatives_evidence.py's module docstring for the full
rationale of this "one family, one established idea, research-stage v1"
approach and why it's a continuation of the master plan's own
Research -> OOS -> Shadow -> Paper promotion sequence, not a shortcut
around it).

Deliberately parallel in structure to derivatives_evidence.py's
price/open-interest confirmation, using order flow's own analogous,
equally well-established idea:

    Direction comes from trade_vwap's own bucket-over-bucket return
    (z-scored over `vwap_return_zscore_window` buckets, tanh-bounded) -
    trade_flow_frame has no separate "price" column, and trade_vwap is
    already this family's own internal notion of price (the same proxy
    src.features.divergence.price_cvd_divergence_frame uses by default,
    Cycle 34).
    CONVICTION comes from whether `trade_delta` (buy_volume -
    sell_volume, already computed per bucket) points the SAME direction
    as that price move - real, one-sided aggressive flow behind the
    move - vs. a move that happened despite roughly balanced or opposing
    trade flow (passive/limit-order-driven, or a squeeze without genuine
    aggressive participation), which gets the score fully zeroed, not
    just dampened - the same "smart money confirmation" pattern as
    open-interest confirmation for derivatives, applied to trade
    aggressor flow instead of positioning.

Deliberately NOT incorporated into score in this v1: `cvd` (the running
cumulative total, a longer-horizon quantity than one bucket's delta) and
book_imbalance/spread/microprice from
src.features.order_flow.l2_imbalance_frame (a genuinely different
Silver stream - trades vs. order-book state - that would need its own
as-of alignment, not something to fold in without that being its own
deliberate step). Refining or extending this scoring rule with those is
exactly the kind of training-data-only research
docs/GREENFIELD_V2_MASTER_PLAN.md section 10.2 describes, not something
to rush here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.engines.contracts import ConfirmationFamily, FamilyEvidence


def order_flow_family_evidence(
    trade_flow: pd.DataFrame,
    *,
    vwap_return_zscore_window: int = 20,
) -> FamilyEvidence | None:
    """Build one FamilyEvidence(family=ORDER_FLOW) from the LATEST bucket
    of an already-computed src.features.order_flow.trade_flow_frame
    output (`trade_flow`, sorted here by `timestamp`).

    Returns `None` (not a synthetic zero-quality entry) when there isn't
    enough history for the rolling z-score to mature or the latest
    bucket's inputs are missing - same reasoning as
    src.engines.derivatives_evidence.derivatives_family_evidence.
    """
    required = {"timestamp", "max_source_timestamp", "trade_vwap", "trade_delta"}
    missing = sorted(required - set(trade_flow.columns))
    if missing:
        raise ValueError(f"order-flow evidence frame missing columns: {missing}")
    if trade_flow.empty:
        return None

    ordered = trade_flow.sort_values("timestamp").reset_index(drop=True)
    vwap_return = ordered["trade_vwap"].astype(float).pct_change(fill_method=None)
    window = vwap_return.rolling(
        vwap_return_zscore_window, min_periods=vwap_return_zscore_window
    )
    zscore = (vwap_return - window.mean()) / window.std(ddof=0).replace(0, np.nan)

    latest_zscore = zscore.iloc[-1]
    latest_return = vwap_return.iloc[-1]
    latest_delta = ordered["trade_delta"].astype(float).iloc[-1]

    if pd.isna(latest_zscore) or pd.isna(latest_return) or pd.isna(latest_delta):
        return None

    flow_confirms = np.sign(latest_delta) == np.sign(latest_return)
    if latest_delta == 0 or latest_return == 0:
        conviction = 0.5
    elif flow_confirms:
        conviction = 1.0
    else:
        conviction = 0.0
    score = max(-1.0, min(1.0, float(np.tanh(latest_zscore)) * conviction))
    confidence = 0.5 if latest_delta == 0 or latest_return == 0 else 1.0
    direction = "up" if latest_return > 0 else ("down" if latest_return < 0 else "flat")
    if conviction == 1.0:
        confirm_word = "confirmed"
    elif conviction == 0.0:
        confirm_word = "contradicted"
    else:
        confirm_word = "ambiguous"
    rationale = (
        f"trade VWAP {direction} ({latest_return:+.4%}, z={latest_zscore:+.2f} over "
        f"{vwap_return_zscore_window} buckets), aggressor flow {confirm_word} the move"
    )

    return FamilyEvidence(
        family=ConfirmationFamily.ORDER_FLOW,
        score=score,
        confidence=confidence,
        quality=1.0,
        max_source_timestamp_utc=ordered["max_source_timestamp"].iloc[-1].to_pydatetime(),
        component_ids=("trade_vwap", "trade_delta"),
        rationale=rationale,
    )
