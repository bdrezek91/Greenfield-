"""Fixed-fraction-of-equity position sizing.

This is a deliberate placeholder, not the Risk Engine. Position sizing,
portfolio-level risk limits, and "should we even take this trade" decisions
belong to src/risk (Phase 9) - see docs/PHASE_0_ARCHITECTURE_RESEARCH.md,
section 29. Every benchmark strategy in this package uses this same sizing
rule so that entry-signal differences, not sizing differences, are what
drive any performance gap between them.
"""

from __future__ import annotations

from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Money, Quantity


def position_size(
    equity: Money, price: float, fraction: float, instrument: Instrument
) -> Quantity:
    """`fraction` of current equity, converted to instrument units at `price`,
    rounded down to the instrument's size increment. Returns zero if the
    inputs don't allow a valid (nonzero) size.
    """
    if price <= 0 or fraction <= 0:
        return instrument.make_qty(0)
    notional = equity.as_double() * fraction
    return instrument.make_qty(notional / price, round_down=True)
