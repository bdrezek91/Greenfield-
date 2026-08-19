"""Proves research_protocol.yaml's base/adverse/severe cost scenarios
actually change what the real NautilusTrader engine charges, not just
funding (see docs/AUTONOMOUS_RESEARCH_AUDIT.md and the mandatory-fix
section of the funding_aware_multi_horizon_trend prereg for the audit
trail: fee_multiplier/slippage_multiplier/entry_delay_bars were parsed out
of the protocol but never consumed anywhere in the execution path before
this fix - only funding_multiplier was ever wired, and only for
`adverse`).

Two things are proven separately, deliberately not conflated:

1. `test_fee_slippage_funding_scale_with_scenario_on_identical_trades`:
   with `entry_delay_bars` held at 0 for all three scenarios, the SAME
   deterministic strategy on the SAME synthetic price series produces
   IDENTICAL trades (same entry/exit timestamps and quantities) under
   base/adverse/severe - only what those trades cost differs. This isolates
   the fee/slippage/funding multiplier mechanism from entry timing.
2. `test_entry_delay_bars_actually_shifts_the_fill_price`: entry_delay_bars
   genuinely delays order submission by N bars and fills at that later
   bar's price - not a post-hoc approximation
   (`src.research.orchestrator._entry_lag_return` already documents itself
   as exactly that kind of approximation; this test proves the real thing
   now also exists).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from src.backtesting.annualization import periods_per_year_for_timeframe
from src.backtesting.costs import ExecutionAssumptions
from src.backtesting.funding import FundingAssumptions
from src.backtesting.runner import run_backtest_window
from src.research.config import load_research_protocol
from src.strategies.trend_following import TrendFollowing, TrendFollowingConfig
from tests.integration.helpers import write_synthetic_klines

_STARTING_BALANCE = Decimal(100_000)
_TIMEFRAME = "1h"


def _run_scenario(tmp_path: Path, ts_end, ts_start, scenario_name: str, entry_delay_bars: int = 0):
    protocol = load_research_protocol()
    scenario = getattr(protocol.costs, scenario_name)
    execution = ExecutionAssumptions(
        fee_multiplier=scenario.fee_multiplier,
        slippage_multiplier=scenario.slippage_multiplier,
        entry_delay_bars=entry_delay_bars,
    )
    funding = FundingAssumptions(
        rate_per_interval=FundingAssumptions().rate_per_interval
        * Decimal(str(scenario.funding_multiplier))
    )
    return run_backtest_window(
        strategy_cls=TrendFollowing,
        config_cls=TrendFollowingConfig,
        symbol="BTCUSDT",
        timeframe=_TIMEFRAME,
        start=ts_start,
        end=ts_end,
        data_dir=tmp_path,
        starting_balance=_STARTING_BALANCE,
        periods_per_year=periods_per_year_for_timeframe(_TIMEFRAME),
        funding_assumptions=funding,
        execution=execution,
    )


def test_fee_slippage_funding_scale_with_scenario_on_identical_trades(tmp_path: Path) -> None:
    # 300 hourly bars, monotonic uptrend with small noise - enough round
    # trips (TrendFollowing's default holding_period_bars=24) to span
    # several of Bybit's 0/8/16 UTC funding settlements.
    close = 100 + np.arange(300, dtype=float) + np.random.default_rng(1).normal(0, 0.1, size=300)
    ts = write_synthetic_klines(tmp_path, close)

    base = _run_scenario(tmp_path, ts[-1], ts[0], "base")
    adverse = _run_scenario(tmp_path, ts[-1], ts[0], "adverse")
    severe = _run_scenario(tmp_path, ts[-1], ts[0], "severe")

    assert len(base.trades) > 0, "test needs at least one round trip to be meaningful"

    # Identical transactions: entry_delay_bars=0 in every scenario here, so
    # the strategy's own signal timing is untouched by the cost scenario -
    # same bars, same direction, same order count. Quantity is allowed a
    # small tolerance (not exact equality): a higher slippage_multiplier
    # means a higher probability of a one-tick fill slip
    # (src.backtesting.costs.ExecutionAssumptions.fill_model), which
    # perturbs the fill price and therefore the risk-engine's equity-
    # fraction position size by a few basis points - that tiny variation is
    # itself evidence slippage_multiplier is doing something real, not a
    # test bug to paper over with exact equality.
    for other in (adverse, severe):
        assert list(other.trades["entry_time"]) == list(base.trades["entry_time"])
        assert list(other.trades["exit_time"]) == list(base.trades["exit_time"])
        assert other.trades["quantity"].tolist() == pytest.approx(
            base.trades["quantity"].tolist(), rel=0.01
        )

    base_fees = float(base.trades["fees"].sum())
    adverse_fees = float(adverse.trades["fees"].sum())
    severe_fees = float(severe.trades["fees"].sum())
    assert base_fees > 0, "fee model produced zero fees - test fixture isn't exercising it"
    assert base_fees < adverse_fees < severe_fees, (
        f"fee totals must strictly increase base<adverse<severe, got "
        f"{base_fees}, {adverse_fees}, {severe_fees}"
    )

    base_funding = float(base.trades["funding_cost"].sum())
    adverse_funding = float(adverse.trades["funding_cost"].sum())
    severe_funding = float(severe.trades["funding_cost"].sum())
    assert base_funding != 0.0, "funding model produced zero cost - fixture isn't exercising it"
    # funding_cost sign depends on position direction (long pays or receives
    # depending on the fixed positive baseline rate); compare magnitudes,
    # which must scale with funding_multiplier regardless of sign.
    assert abs(base_funding) < abs(adverse_funding) < abs(severe_funding), (
        f"funding cost magnitude must strictly increase base<adverse<severe, got "
        f"{base_funding}, {adverse_funding}, {severe_funding}"
    )

    base_net = base.metrics.trade_metrics.net_return
    adverse_net = adverse.metrics.trade_metrics.net_return
    severe_net = severe.metrics.trade_metrics.net_return
    assert base_net >= adverse_net >= severe_net, (
        f"net return must never improve as costs get worse, got "
        f"base={base_net}, adverse={adverse_net}, severe={severe_net}"
    )


def test_entry_delay_bars_actually_shifts_the_fill_price(tmp_path: Path) -> None:
    # Strictly increasing by a fixed 1.0/bar - the fill price at bar N+k is
    # exactly base_price(N) + k, so a genuine k-bar delay is directly
    # verifiable, not just "some other number".
    close = 100 + np.arange(300, dtype=float)
    ts = write_synthetic_klines(tmp_path, close)

    immediate = _run_scenario(tmp_path, ts[-1], ts[0], "base", entry_delay_bars=0)
    delayed = _run_scenario(tmp_path, ts[-1], ts[0], "base", entry_delay_bars=2)

    assert len(immediate.trades) > 0
    assert len(delayed.trades) > 0

    # Same signal, later fill: the delayed run's first entry timestamp must
    # be strictly later than the immediate run's, and its entry price must
    # be exactly 2 bars' worth of the deterministic +1.0/bar trend ahead.
    immediate_entry_time = immediate.trades["entry_time"].iloc[0]
    delayed_entry_time = delayed.trades["entry_time"].iloc[0]
    assert delayed_entry_time > immediate_entry_time

    # Within 0.05 of exactly 2 bars ahead on the deterministic +1.0/bar
    # trend - not exact equality, since a one-tick slippage draw
    # (ExecutionAssumptions.fill_model, prob_slippage=0.2 at multiplier=1.0)
    # can still perturb either fill by a fraction of a tick.
    immediate_entry_price = float(immediate.trades["entry_price"].iloc[0])
    delayed_entry_price = float(delayed.trades["entry_price"].iloc[0])
    assert delayed_entry_price == pytest.approx(immediate_entry_price + 2.0, abs=0.05)
