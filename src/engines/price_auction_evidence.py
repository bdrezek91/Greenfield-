"""Research-stage v1: build one PRICE_AUCTION ConfirmationFamily
FamilyEvidence from src.features.auction.rolling_volume_profile_frame's
own POC/VAH/VAL output (Cycle 27), merged with the caller's own `close`
price series (rolling_volume_profile_frame's output has no `close` -
same "caller pre-builds the exact required, already-aligned frame, not
computed here" convention as every other bridge in this project since
Cycle 26).

Fourth of six ConfirmationFamily evidence producers (see
src/engines/derivatives_evidence.py's module docstring for the full
"one family, one established idea, research-stage v1" rationale).

Uses classic Market Profile / auction-market-theory value-area breakout
logic (Steidlmayer), the literal textbook meaning of "price structure and
auction" (docs/GREENFIELD_V2_MASTER_PLAN.md section 10.2's family #1):
price closing ABOVE the value area (VAH) means the market is finding
acceptance at higher prices than its recent balance - excess/rejection
of the old range, a bullish auction signal. Closing BELOW the value area
(VAL) is the bearish mirror. Closing INSIDE the value area means the
market is still in balance - no directional auction edge, score exactly
0, not a small nonzero number pretending to know a direction.

    Direction AND magnitude both come from ONE self-contained quantity:
    how far outside the value area `close` is, expressed as a fraction
    of the value area's own width (`(vah - val)`, the same scale-
    invariant normalization src.features.pipeline.build_feature_matrix's
    `poc_distance`/`value_area_width` extras already use, Cycle 27) and
    tanh-bounded. Unlike derivatives/order-flow's separate direction +
    confirmation-series structure, auction theory gives both from the
    same POC/VAH/VAL reading - there is no second, independent
    "conviction" series to gate against.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.engines.contracts import ConfirmationFamily, FamilyEvidence


def price_auction_family_evidence(context: pd.DataFrame) -> FamilyEvidence | None:
    """Build one FamilyEvidence(family=PRICE_AUCTION) from the LATEST row
    of a caller-merged frame with `timestamp`, `poc`, `vah`, `val` (from
    src.features.auction.rolling_volume_profile_frame) and `close` (the
    caller's own OHLCV, as-of aligned to the same timestamps).

    Returns `None` (not a synthetic zero-quality entry) when the latest
    row's inputs are missing/NaN (the volume profile's own trailing
    window hasn't matured yet) or the value area is degenerate
    (`vah <= val`, which never happens with a real profile but is
    guarded against rather than dividing by a non-positive width).
    """
    required = {"timestamp", "poc", "vah", "val", "close"}
    missing = sorted(required - set(context.columns))
    if missing:
        raise ValueError(f"price-auction evidence frame missing columns: {missing}")
    if context.empty:
        return None

    ordered = context.sort_values("timestamp").reset_index(drop=True)
    latest = ordered.iloc[-1]
    vah, val, close = latest["vah"], latest["val"], latest["close"]

    if pd.isna(vah) or pd.isna(val) or pd.isna(close):
        return None
    width = vah - val
    if not width > 0:
        return None

    if close > vah:
        excess = (close - vah) / width
        location = "above the value area (VAH)"
    elif close < val:
        excess = (close - val) / width
        location = "below the value area (VAL)"
    else:
        excess = 0.0
        location = "inside the value area - market in balance"

    score = max(-1.0, min(1.0, float(np.tanh(excess))))
    rationale = (
        f"close is {location}, {abs(excess):.2f}x the value-area width "
        f"(vah={vah:.4f}, val={val:.4f})"
    )

    return FamilyEvidence(
        family=ConfirmationFamily.PRICE_AUCTION,
        score=score,
        confidence=1.0,
        quality=1.0,
        max_source_timestamp_utc=latest["timestamp"].to_pydatetime(),
        component_ids=("close", "vah", "val"),
        rationale=rationale,
    )
