"""Real-data cross-exchange funding coarse screen: Hyperliquid vs Bybit,
BTC/ETH/SOL, both directions. Uses ONLY existing engines
(src.engines.neutral_market.derive_cross_exchange_funding_edge,
src.engines.neutral.evaluate_neutral_opportunity) - no new carry engine.

Versioned counterpart to the one-off analysis first run 2026-08-27 (see
docs/CLAUDE_CODE_CONTINUATION.md's "Hyperliquid<->Bybit cross-exchange
funding coarse screen" checkpoint) - this script IS that analysis, made
reproducible: parametrized data_dir/out_dir, unit-tested cost/direction
math, and a machine-readable manifest (parameters, data checksums,
period, observation counts, fee schedule) instead of a scratchpad run.

TERMINOLOGY (load-bearing, do not blur): every net-edge figure this
script produces is one of exactly two things, always named accordingly:
  - BASE: the point estimate (expected_gross_edge_bps.base - costs.base).
  - LOW: the conservative lower bound (expected_gross_edge_bps.low -
    costs.high) - what the entry gate actually checks against
    SAFETY_BUFFER_BPS. This is deliberately pessimistic on both sides
    (worst-plausible gross edge, worst-plausible cost).
A number without one of these suffixes is a bug, not a stylistic choice.

DATA WINDOW (disclosed limitation, not hidden): Hyperliquid's
`fundingHistory` covers the full available market history for BTC/ETH/SOL
(live-verified 2023-05-12..present at first run), but `candleSnapshot`
only retains a ROLLING window (live-verified ~209 days at first run,
2026-01-31..2026-08-27) - re-verify both live-checked spans on every run,
never assume they still match this docstring's numbers. Since "funding
payments alone are not profit - basis change between entry and exit must
be included" is a hard requirement, the FULL (funding+basis) net-P&L
simulation is bounded to whatever the price-history intersection turns
out to be on the day this runs. The longer funding-only history is
reported separately, purely as descriptive context, never as a decision
basis (see FUNDING_ONLY_CONTEXT_NOTE below and the printed report).

FIXED, PRE-STATED PARAMETERS (frozen 2026-08-27, do not retune after
seeing results - see the standing instruction this script implements):
  - HORIZON_HOURS = 24
  - SAFETY_BUFFER_BPS = 10.0 (the entry gate: LOW must exceed this)
  - ASSUMED_LEVERAGE = 3.0 (for margin/liquidation stress bounds only -
    conservative for a market-neutral carry trade, not this project's
    maximum available leverage)
  - Fee schedule (verified 2026-08-27, base/non-VIP tier, not any
    particular account's negotiated tier):
        Bybit:       maker 2.0 bps   taker 5.5 bps
        Hyperliquid: maker 1.5 bps   taker 4.5 bps (no maker rebate at
                     base tier)
  - Entry gate fee scenario: taker/taker (never assume a maker fill) -
    all 4 scenarios (maker/maker, maker/taker, taker/taker, adverse) are
    still computed and reported for every opportunity.
  - Spread/slippage/capacity proxy: no historical tick-level BBO exists
    for either venue over the full window, so entry/exit quotes use each
    venue's own hourly candle CLOSE price plus half of that venue's
    CURRENT (live, observed at run time) spread, held constant
    historically. Capacity likewise uses a live-observed top-of-book
    notional, held constant. Both are disclosed simplifications, not a
    claim that spreads/depth never varied historically.

Usage:
    python scripts/screen_hyperliquid_bybit_funding_carry.py \
        --data-dir /opt/greenfield-v2/data \
        --out-dir reports/hyperliquid-bybit-funding-carry
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.data.hyperliquid_storage import read_hyperliquid_funding_history
from src.engines.contracts import (
    ConfirmationFamily,
    DataQualityStatus,
    EngineGateState,
    FamilyEvidence,
    NumericRange,
)
from src.engines.neutral import (
    LegExecutionPolicy,
    NeutralCostBreakdown,
    NeutralEngineConfig,
    NeutralInventoryState,
    NeutralMechanism,
    NeutralOpportunityRequest,
    NeutralStressBounds,
    evaluate_neutral_opportunity,
)
from src.engines.neutral_market import ExecutablePerpetualQuote, derive_cross_exchange_funding_edge

log = structlog.get_logger()
app = typer.Typer(add_completion=False)

HORIZON_HOURS = 24
SAFETY_BUFFER_BPS = 10.0
ASSUMED_LEVERAGE = 3.0

# (maker_bps, taker_bps) per venue - verified 2026-08-27, base tier.
BYBIT_FEES = (2.0, 5.5)
HL_FEES = (1.5, 4.5)
# (bybit_entry, hl_entry, bybit_exit, hl_exit) fee bps per leg-pair.
FEE_SCENARIOS = {
    "maker_maker": (BYBIT_FEES[0], HL_FEES[0], BYBIT_FEES[0], HL_FEES[0]),
    "maker_taker": (BYBIT_FEES[0], HL_FEES[0], BYBIT_FEES[1], HL_FEES[1]),
    "taker_taker": (BYBIT_FEES[1], HL_FEES[1], BYBIT_FEES[1], HL_FEES[1]),
    "adverse": (BYBIT_FEES[1], HL_FEES[1], BYBIT_FEES[1], HL_FEES[1]),  # + extra slippage
}
ENTRY_GATE_SCENARIO = "taker_taker"

SYMBOLS = ("BTC", "ETH", "SOL")

FUNDING_ONLY_CONTEXT_NOTE = (
    "Funding-only differential statistics below (no basis, no costs) are "
    "descriptive context over the LONGER funding-history window only - "
    "NEVER a decision basis. In particular any annualized-equivalent "
    "figure is informational only; see this script's module docstring "
    "and the entry gate, which never uses an annualized number."
)


def _hl_symbol(coin: str) -> str:
    return coin


def _bybit_symbol(coin: str) -> str:
    return f"{coin}USDT"


@dataclass
class Episode:
    coin: str
    direction: str  # "long_bybit_short_hl" | "long_hl_short_bybit"
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_basis_bps: float
    exit_basis_bps: float
    funding_differential_bps_at_entry: float
    realized_funding_pnl_bps: float
    realized_basis_pnl_bps: float
    fees_bps: dict
    slippage_bps: float
    net_pnl_bps: dict  # per fee scenario - realized, not BASE/LOW (this is a completed trade)
    capacity_notional: float


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def load_funding(data_dir: Path, coin: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    hl = read_hyperliquid_funding_history(data_dir, _hl_symbol(coin))
    bybit_dir = data_dir / "funding" / _bybit_symbol(coin)
    frames = [pd.read_parquet(p) for p in sorted(bybit_dir.glob("*.parquet"))]
    bybit = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    return hl.sort_values("timestamp").reset_index(drop=True), bybit


def load_prices(
    data_dir: Path, price_cache_dir: Path, coin: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    hl = pd.read_parquet(price_cache_dir / f"hl_candles_{coin}.parquet")
    bybit_dir = data_dir / "klines" / _bybit_symbol(coin) / "1h"
    frames = [pd.read_parquet(p) for p in sorted(bybit_dir.glob("*.parquet"))]
    bybit = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    return hl, bybit


def hourly_hl_funding_rate(hl_funding: pd.DataFrame, hour: pd.Timestamp) -> float:
    """As-of hourly rate (HL's own fundingHistory rows ARE hourly)."""
    idx = hl_funding["timestamp"].searchsorted(hour, side="right") - 1
    if idx < 0:
        return float("nan")
    return float(hl_funding["funding_rate"].iloc[idx])


def hourly_bybit_funding_rate(bybit_funding: pd.DataFrame, hour: pd.Timestamp) -> float:
    """As-of Bybit 8h rate, amortized to an hourly rate (rate/8) for
    normalization purposes only. The realized-P&L simulation
    (simulate_episode) uses the TRUE 8h lump-sum settlement instead."""
    idx = bybit_funding["timestamp"].searchsorted(hour, side="right") - 1
    if idx < 0:
        return float("nan")
    return float(bybit_funding["funding_rate"].iloc[idx]) / 8.0


def price_at(prices: pd.DataFrame, hour: pd.Timestamp) -> float | None:
    idx = prices["timestamp"].searchsorted(hour, side="right") - 1
    if idx < 0:
        return None
    return float(prices["close"].iloc[idx])


def build_quote(
    venue: str,
    coin: str,
    price: float,
    funding_rate_hourly: float,
    capacity: float,
    spread_bps: dict,
    ts: datetime,
) -> ExecutablePerpetualQuote:
    half = price * (spread_bps[coin][venue] / 2) / 10_000
    return ExecutablePerpetualQuote(
        venue=venue,
        symbol=coin,
        bid=price - half,
        ask=price + half,
        funding_rate_per_period=funding_rate_hourly,
        executable_capacity_notional=capacity,
        received_at_utc=ts,
    )


def cost_breakdown(scenario: str, coin: str, spread_bps: dict) -> NeutralCostBreakdown:
    bybit_entry, hl_entry, bybit_exit, hl_exit = FEE_SCENARIOS[scenario]
    total_fees = bybit_entry + hl_entry + bybit_exit + hl_exit
    base_spread = spread_bps[coin]["bybit"] + spread_bps[coin]["hyperliquid"]
    adverse = scenario == "adverse"
    slippage_low = 0.5
    slippage_base = 1.5 + (5.0 if adverse else 0.0)
    slippage_high = 4.0 + (10.0 if adverse else 0.0)
    return NeutralCostBreakdown(
        fees_bps=NumericRange(total_fees, total_fees, total_fees),
        spread_bps=NumericRange(base_spread * 0.5, base_spread, base_spread * 1.5),
        slippage_bps=NumericRange(slippage_low, slippage_base, slippage_high),
        # Funding differential is already captured inside expected_gross_edge_bps
        # (derive_cross_exchange_funding_edge) - counting it again here would
        # double-count the single largest input to this whole screen.
        funding_bps=NumericRange(0.0, 0.0, 0.0),
        borrow_bps=NumericRange(0.0, 0.0, 0.0),  # perpetuals, no asset borrow
        transfer_bps=NumericRange(0.0, 0.0, 0.0),  # prefunded on both venues, assumed
        orphan_hedge_bps=NumericRange(0.0, 1.0, 3.0),
    )


def basis_bps(hl_price: float, bybit_price: float) -> float:
    """Positive means Bybit trades above Hyperliquid."""
    mid = (hl_price + bybit_price) / 2
    return (bybit_price - hl_price) / mid * 10_000


def realized_basis_pnl_bps(direction: str, entry_basis: float, exit_basis: float) -> float:
    """Price-leg P&L for long_bybit_short_hl = (bybit_exit - bybit_entry) +
    (hl_entry - hl_exit), which algebraically equals exit_basis -
    entry_basis given basis_bps's (bybit - hl)/mid definition. The mirror
    direction is the negation."""
    delta = exit_basis - entry_basis
    return delta if direction == "long_bybit_short_hl" else -delta


def realized_funding_pnl_bps(
    direction: str, hl_funding_sum_bps: float, bybit_funding_sum_bps: float
) -> float:
    """Perpetual convention: positive funding_rate means longs pay shorts.
    long_bybit_short_hl: we pay bybit's funding (long leg), receive hl's
    (short leg) -> hl_sum - bybit_sum. Mirror direction is the negation."""
    if direction == "long_bybit_short_hl":
        return hl_funding_sum_bps - bybit_funding_sum_bps
    return bybit_funding_sum_bps - hl_funding_sum_bps


def make_request(
    coin: str,
    long_venue: str,
    short_venue: str,
    long_quote: ExecutablePerpetualQuote,
    short_quote: ExecutablePerpetualQuote,
    ts: datetime,
    scenario: str,
    spread_bps: dict,
) -> NeutralOpportunityRequest:
    edge = derive_cross_exchange_funding_edge(
        long_quote,
        short_quote,
        as_of_utc=ts,
        funding_periods=HORIZON_HOURS,
        model_uncertainty_bps=5.0,
        maximum_quote_age_seconds=3600.0,  # backtest: quotes are "as of" ts by construction
    )
    derivatives_evidence = FamilyEvidence(
        family=ConfirmationFamily.DERIVATIVES,
        score=max(-1.0, min(1.0, edge.funding_differential_bps / 50.0)),
        confidence=1.0,
        quality=1.0,
        max_source_timestamp_utc=ts,
        component_ids=("hyperliquid_funding", "bybit_funding"),
        rationale="funding differential from real venue funding rates",
    )
    cross_market_evidence = FamilyEvidence(
        family=ConfirmationFamily.CROSS_MARKET,
        score=max(-1.0, min(1.0, edge.entry_basis_bps / 50.0)),
        confidence=1.0,
        quality=1.0,
        max_source_timestamp_utc=ts,
        component_ids=("hyperliquid_bbo", "bybit_bbo"),
        rationale="cross-venue executable basis from real BBO-proxy quotes",
    )
    margin_buffer_bps = (1 - 1 / ASSUMED_LEVERAGE) * 10_000
    liquidation_distance_bps = margin_buffer_bps * 0.9
    return NeutralOpportunityRequest(
        mechanism=NeutralMechanism.CROSS_EXCHANGE_FUNDING,
        symbol=coin,
        long_venue=long_venue,
        short_venue=short_venue,
        decision_timestamp_utc=ts,
        data_cutoff_utc=ts,
        horizon=f"{HORIZON_HOURS}h",
        evidence=(derivatives_evidence, cross_market_evidence),
        # No real regime classification is part of this coarse screen - a
        # single honest placeholder label, required non-empty by
        # SetupDecision's own contract.
        regimes=(("research", "coarse_screen_backtest"),),
        expected_gross_edge_bps=edge.expected_gross_edge_bps,
        costs=cost_breakdown(scenario, coin, spread_bps),
        capacity_notional=edge.capacity_notional,
        data_quality_status=DataQualityStatus.PASS,
        model_version="hl-bybit-funding-carry-screen-v1",
        feature_version="hl-bybit-funding-carry-screen-v1",
        inventory=NeutralInventoryState(
            long_leg_available=True,
            short_leg_available=True,
            short_borrow_required=False,
            short_borrow_confirmed=True,
            transfer_required=False,
            prefunded_inventory=True,
            long_venue_healthy=True,
            short_venue_healthy=True,
        ),
        stresses=NeutralStressBounds(
            one_leg_loss_bps=20.0,
            venue_outage_loss_bps=15.0,
            liquidation_stress_loss_bps=30.0,
            margin_buffer_bps=margin_buffer_bps,
            liquidation_distance_bps=liquidation_distance_bps,
        ),
        execution_policy=LegExecutionPolicy.HEDGE_ON_PARTIAL,
        maximum_unhedged_seconds=5.0,
        entry_condition=(
            f"conservative net edge LOW > {SAFETY_BUFFER_BPS}bps under "
            f"{ENTRY_GATE_SCENARIO} fees, {HORIZON_HOURS}h horizon"
        ),
        invalidation="funding differential or basis reverses sign before exit",
        hedge_logic="atomic-or-cancel entry, hedge-on-partial with 5s max unhedged window",
        gates=EngineGateState(
            kill_switch_active=False,
            operational_healthy=True,
            promotion_eligible=True,
            promotion_state="RESEARCH_BACKTEST",
            risk_approved=True,
            risk_reason="backtest: no live risk engine consulted",
        ),
    )


def net_edge_for_scenario(
    gross_edge_bps: NumericRange, scenario: str, coin: str, spread_bps: dict
) -> NumericRange:
    """Same net-edge arithmetic evaluate_neutral_opportunity uses
    internally (net.low = gross.low - costs.high, net.base = gross.base -
    costs.base, net.high = gross.high - costs.low) - exposed standalone so
    every fee scenario's BASE and LOW can be tracked at every hour without
    a full NeutralOpportunityRequest/gate round-trip per scenario (only
    the entry-gate scenario needs the full gate evaluation; the other
    three are for reporting only)."""
    costs = cost_breakdown(scenario, coin, spread_bps).total()
    return NumericRange(
        low=gross_edge_bps.low - costs.high,
        base=gross_edge_bps.base - costs.base,
        high=gross_edge_bps.high - costs.low,
    )


def engine_config() -> NeutralEngineConfig:
    return NeutralEngineConfig(
        minimum_net_edge_lower_bps=SAFETY_BUFFER_BPS,
        # NeutralEngineConfig.minimum_evidence_strength's 0.25 default has
        # no natural meaning for "how large is a funding differential in
        # bps" the way it does for e.g. an order-flow confidence score -
        # left at its default it becomes the BINDING gate almost always,
        # silently overriding the net-edge threshold this screen is
        # actually supposed to test. Set to the engine's minimum non-zero
        # value so minimum_net_edge_lower_bps is the one binding entry
        # criterion, per the standing instruction that the threshold come
        # from costs/uncertainty, not an unrelated score scale.
        minimum_evidence_strength=0.001,
    )


def simulate_episode(
    coin: str,
    direction: str,
    entry_hour: pd.Timestamp,
    exit_hour: pd.Timestamp,
    hl_funding: pd.DataFrame,
    bybit_funding: pd.DataFrame,
    hl_prices: pd.DataFrame,
    bybit_prices: pd.DataFrame,
    capacity_notional: float,
) -> Episode | None:
    hl_entry = price_at(hl_prices, entry_hour)
    bybit_entry = price_at(bybit_prices, entry_hour)
    hl_exit = price_at(hl_prices, exit_hour)
    bybit_exit = price_at(bybit_prices, exit_hour)
    if hl_entry is None or bybit_entry is None or hl_exit is None or bybit_exit is None:
        return None

    entry_basis = basis_bps(hl_entry, bybit_entry)
    exit_basis = basis_bps(hl_exit, bybit_exit)
    basis_pnl = realized_basis_pnl_bps(direction, entry_basis, exit_basis)

    hl_window = hl_funding[
        (hl_funding["timestamp"] > entry_hour) & (hl_funding["timestamp"] <= exit_hour)
    ]
    bybit_window = bybit_funding[
        (bybit_funding["timestamp"] > entry_hour) & (bybit_funding["timestamp"] <= exit_hour)
    ]
    hl_funding_sum = float(hl_window["funding_rate"].sum()) * 10_000
    bybit_funding_sum = float(bybit_window["funding_rate"].sum()) * 10_000
    funding_pnl = realized_funding_pnl_bps(direction, hl_funding_sum, bybit_funding_sum)

    fees_by_scenario = {}
    net_by_scenario = {}
    for scenario, (be, he, bx, hx) in FEE_SCENARIOS.items():
        total_fee = be + he + bx + hx
        extra_slip = 10.0 if scenario == "adverse" else 0.0
        fees_by_scenario[scenario] = total_fee
        net_by_scenario[scenario] = funding_pnl + basis_pnl - total_fee - extra_slip

    return Episode(
        coin=coin,
        direction=direction,
        entry_time=entry_hour,
        exit_time=exit_hour,
        entry_basis_bps=entry_basis,
        exit_basis_bps=exit_basis,
        funding_differential_bps_at_entry=(
            hourly_bybit_funding_rate(bybit_funding, entry_hour) * 10_000
            - hourly_hl_funding_rate(hl_funding, entry_hour) * 10_000
        ),
        realized_funding_pnl_bps=funding_pnl,
        realized_basis_pnl_bps=basis_pnl,
        fees_bps=fees_by_scenario,
        slippage_bps=2.0,
        net_pnl_bps=net_by_scenario,
        capacity_notional=capacity_notional,
    )


@app.command()
def screen(
    data_dir: str = typer.Option(..., help="Greenfield production data root."),
    price_cache_dir: str = typer.Option(
        ..., help="Directory holding hl_candles_{COIN}.parquet basis-proxy caches."
    ),
    out_dir: str = typer.Option(
        "reports/hyperliquid-bybit-funding-carry", help="Where to write the manifest/report."
    ),
    live_spread_bps: str = typer.Option(
        ...,
        help=(
            "JSON dict of live-observed spreads, e.g. "
            '{"BTC":{"bybit":0.0126,"hyperliquid":0.1257},...} - fetch live '
            "immediately before running; see module docstring."
        ),
    ),
    live_capacity_notional: str = typer.Option(
        ...,
        help='JSON dict of live-observed capacity, e.g. {"BTC":184000.0,...}',
    ),
) -> None:
    data_root = Path(data_dir)
    cache_root = Path(price_cache_dir)
    report_root = Path(out_dir)
    spread_bps: dict = json.loads(live_spread_bps)
    capacity_notional: dict = json.loads(live_capacity_notional)
    config = engine_config()

    checksums: dict[str, dict[str, str]] = {}
    observation_counts: dict[str, int] = {}
    action_counts: dict[str, dict[str, int]] = {}
    all_episodes: list[Episode] = []
    common_windows: dict[str, tuple[str, str]] = {}
    funding_only_windows: dict[str, tuple[str, str]] = {}
    # Best BASE (point estimate) and LOW (conservative bound) ever
    # observed, per fee scenario, across every hour/coin/direction in the
    # full (non-sampled) grid - not just the entry-gate scenario. Exists
    # so the report never has to mix a full-grid search under one
    # scenario with a coarser/sampled search under another (the exact
    # confusion this script's docstring's TERMINOLOGY section exists to
    # prevent).
    best_by_scenario: dict[str, dict[str, dict | None]] = {
        scenario: {"base": None, "low": None} for scenario in FEE_SCENARIOS
    }
    # Count of (coin, direction, hour) observations - across the full,
    # non-sampled grid - where BASE/LOW was positive, per scenario. Not a
    # decision basis (only the entry-gate scenario's LOW vs
    # SAFETY_BUFFER_BPS is), purely descriptive.
    positive_counts: dict[str, dict[str, int]] = {
        scenario: {"base": 0, "low": 0} for scenario in FEE_SCENARIOS
    }
    total_scenario_observations = 0

    for coin in SYMBOLS:
        log.info("screening", coin=coin)
        hl_funding, bybit_funding = load_funding(data_root, coin)
        hl_prices, bybit_prices = load_prices(data_root, cache_root, coin)

        checksums[coin] = {
            "hyperliquid_funding": _sha256_dir_summary(
                data_root / "hyperliquid_funding_history" / _hl_symbol(coin)
            ),
            "bybit_funding": _sha256_dir_summary(data_root / "funding" / _bybit_symbol(coin)),
            "hyperliquid_candles": _sha256(cache_root / f"hl_candles_{coin}.parquet"),
            "bybit_klines": _sha256_dir_summary(data_root / "klines" / _bybit_symbol(coin) / "1h"),
        }
        funding_only_windows[coin] = (
            str(max(hl_funding["timestamp"].min(), bybit_funding["timestamp"].min())),
            str(min(hl_funding["timestamp"].max(), bybit_funding["timestamp"].max())),
        )

        common_start = max(hl_prices["timestamp"].min(), bybit_prices["timestamp"].min())
        common_end = min(hl_prices["timestamp"].max(), bybit_prices["timestamp"].max())
        common_windows[coin] = (str(common_start), str(common_end))

        hours = pd.date_range(common_start, common_end - timedelta(hours=HORIZON_HOURS), freq="1h")
        action_counts[coin] = {"ARBITRAGE": 0, "WAIT": 0}
        n_obs = 0
        next_free = {"long_bybit_short_hl": hours[0], "long_hl_short_bybit": hours[0]}

        for hour in hours:
            hl_price = price_at(hl_prices, hour)
            bybit_price = price_at(bybit_prices, hour)
            if hl_price is None or bybit_price is None:
                continue
            hl_rate = hourly_hl_funding_rate(hl_funding, hour)
            bybit_rate = hourly_bybit_funding_rate(bybit_funding, hour)
            if hl_rate != hl_rate or bybit_rate != bybit_rate:
                continue

            cap = capacity_notional[coin]
            hl_q = build_quote(
                "hyperliquid", coin, hl_price, hl_rate, cap, spread_bps, hour.to_pydatetime()
            )
            by_q = build_quote(
                "bybit", coin, bybit_price, bybit_rate, cap, spread_bps, hour.to_pydatetime()
            )

            decisions = {}
            for direction, (long_q, short_q, long_v, short_v) in {
                "long_bybit_short_hl": (by_q, hl_q, "bybit", "hyperliquid"),
                "long_hl_short_bybit": (hl_q, by_q, "hyperliquid", "bybit"),
            }.items():
                gross_edge = derive_cross_exchange_funding_edge(
                    long_q,
                    short_q,
                    as_of_utc=hour.to_pydatetime(),
                    funding_periods=HORIZON_HOURS,
                    model_uncertainty_bps=5.0,
                    maximum_quote_age_seconds=3600.0,
                )
                for scenario in FEE_SCENARIOS:
                    net = net_edge_for_scenario(
                        gross_edge.expected_gross_edge_bps, scenario, coin, spread_bps
                    )
                    for kind, value in (("base", net.base), ("low", net.low)):
                        current = best_by_scenario[scenario][kind]
                        if current is None or value > current["value"]:
                            best_by_scenario[scenario][kind] = {
                                "value": value,
                                "coin": coin,
                                "direction": direction,
                                "hour": str(hour),
                            }
                        if value > 0:
                            positive_counts[scenario][kind] += 1
                total_scenario_observations += 1
                req = make_request(
                    coin,
                    long_v,
                    short_v,
                    long_q,
                    short_q,
                    hour.to_pydatetime(),
                    ENTRY_GATE_SCENARIO,
                    spread_bps,
                )
                decision = evaluate_neutral_opportunity(req, config)
                decisions[direction] = decision
                action_counts[coin][decision.action.value] = (
                    action_counts[coin].get(decision.action.value, 0) + 1
                )
                n_obs += 1

            for direction, decision in sorted(
                decisions.items(), key=lambda kv: -kv[1].expected_value_after_cost_bps.base
            ):
                if decision.action.value != "ARBITRAGE" or hour < next_free[direction]:
                    continue
                exit_hour = hour + timedelta(hours=HORIZON_HOURS)
                if exit_hour > common_end:
                    continue
                episode = simulate_episode(
                    coin,
                    direction,
                    hour,
                    exit_hour,
                    hl_funding,
                    bybit_funding,
                    hl_prices,
                    bybit_prices,
                    cap,
                )
                if episode is not None:
                    all_episodes.append(episode)
                    next_free[direction] = exit_hour
                break

        observation_counts[coin] = n_obs

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "parameters": {
            "horizon_hours": HORIZON_HOURS,
            "safety_buffer_bps": SAFETY_BUFFER_BPS,
            "assumed_leverage": ASSUMED_LEVERAGE,
            "entry_gate_fee_scenario": ENTRY_GATE_SCENARIO,
            "fee_schedule_bps": {"bybit": BYBIT_FEES, "hyperliquid": HL_FEES},
            "live_spread_bps": spread_bps,
            "live_capacity_notional": capacity_notional,
        },
        "data_versions": {
            "basis_price_common_window": common_windows,
            "funding_only_window": funding_only_windows,
            "input_checksums": checksums,
        },
        "observation_counts": observation_counts,
        "action_counts": action_counts,
        # Best BASE (point estimate) and LOW (conservative bound) found
        # anywhere in the full grid, per fee scenario - see this script's
        # module docstring's TERMINOLOGY section. Never mix a "base" value
        # from one scenario with a "low" value from another when quoting
        # this in prose.
        "best_net_edge_bps_by_scenario": best_by_scenario,
        "total_scenario_observations": total_scenario_observations,
        "positive_fraction_by_scenario": {
            scenario: {
                kind: positive_counts[scenario][kind] / total_scenario_observations
                for kind in ("base", "low")
            }
            for scenario in FEE_SCENARIOS
        },
        "episodes_entered": len(all_episodes),
        "verdict": "CARRY_CANDIDATE" if all_episodes else "NO_CANDIDATE",
    }
    report_root.mkdir(parents=True, exist_ok=True)
    manifest_path = report_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    log.info(
        "screen complete",
        episodes=len(all_episodes),
        verdict=manifest["verdict"],
        manifest=str(manifest_path),
    )


def _sha256_dir_summary(directory: Path) -> str:
    """Single combined checksum of every *.parquet file in `directory`,
    order-independent (sorted by relative path) - a compact fingerprint
    for a whole monthly-partitioned dataset rather than one hash per file."""
    if not directory.exists():
        return "no-data"
    hasher = hashlib.sha256()
    for path in sorted(directory.glob("*.parquet")):
        hasher.update(path.name.encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


if __name__ == "__main__":
    app()
