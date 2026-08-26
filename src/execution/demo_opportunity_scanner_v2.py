""""Druga proba scalpingu": liquidation-cascade-fade + funding-regime filter.

Deliberately replaces v1's (`demo_opportunity_scanner.py`) three-family
order-flow/price-auction/derivatives confluence + momentum-wave veto, which
this system's own live Demo results (see docs/CLAUDE_CODE_CONTINUATION.md)
showed converging to roughly a 10% win rate against a 40% breakeven
requirement at its 20/30bps stop/target. Two, not three, inputs, each
individually motivated by crypto market-microstructure research rather than
generic lagging technical indicators - see the same doc for the full
writeup and its honest epistemic caveats:

1. A liquidation cascade (mechanical, non-discretionary forced order flow)
   as the entry TRIGGER, faded on the hypothesis that forced liquidation
   overshoots fair value.
2. Extreme funding rate as a regime FILTER, veto-ing a fade direction that
   would add to an already-crowded side.

An order-flow/auction absorption CONFIRMATION layer (the third piece of the
original research proposal) is deliberately NOT implemented here - it
requires live L2 order-book absorption detection that no live feed in this
codebase currently assembles for a continuous decision loop. Left as
documented future work rather than approximated with a weaker proxy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.engines.contracts import SetupAction
from src.execution.demo_scalp_liquidation_signal import (
    FundingRegimeConfig,
    LiquidationCascadeConfig,
    LiquidationCascadeSignal,
    LiquidationEvent,
    detect_liquidation_cascade,
    funding_regime_allows,
)

LIQUIDATION_FADE_CANDIDATE_ID = "EXPERIMENTAL_DEMO_SCALP_V2_LIQUIDATION_FADE_NOT_PROMOTED"


@dataclass(frozen=True, slots=True)
class LiquidationFadeScan:
    symbol: str
    action: SetupAction
    cascade: LiquidationCascadeSignal
    funding_rate: Decimal
    detail: str


def scan_liquidation_fade(
    *,
    symbol: str,
    liquidations: tuple[LiquidationEvent, ...],
    funding_rate: Decimal,
    observed_at_utc: datetime,
    cascade_config: LiquidationCascadeConfig | None = None,
    funding_config: FundingRegimeConfig | None = None,
) -> LiquidationFadeScan:
    if not symbol or symbol != symbol.upper():
        raise ValueError("liquidation-fade scan symbol must be uppercase")
    cascade = detect_liquidation_cascade(
        liquidations, observed_at_utc=observed_at_utc, config=cascade_config
    )
    if not cascade.detected:
        return LiquidationFadeScan(
            symbol=symbol,
            action=SetupAction.WAIT,
            cascade=cascade,
            funding_rate=funding_rate,
            detail="no liquidation cascade detected",
        )
    if not funding_regime_allows(cascade.direction, funding_rate, config=funding_config):
        return LiquidationFadeScan(
            symbol=symbol,
            action=SetupAction.WAIT,
            cascade=cascade,
            funding_rate=funding_rate,
            detail=f"funding regime vetoes {cascade.direction.value} cascade fade",
        )
    return LiquidationFadeScan(
        symbol=symbol,
        action=cascade.direction,
        cascade=cascade,
        funding_rate=funding_rate,
        detail=(
            f"{cascade.liquidated_side.value if cascade.liquidated_side else '?'} "
            f"liquidation cascade (ratio={cascade.notional_ratio:.1f}x), funding regime clear"
        ),
    )
