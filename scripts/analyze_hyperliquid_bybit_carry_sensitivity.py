"""P5: sensitivity/explanatory analysis of the already-verdicted
Hyperliquid<->Bybit funding-carry coarse screen (NO_CANDIDATE, frozen
2026-08-27 in scripts/screen_hyperliquid_bybit_funding_carry.py).

Does NOT change the preregistered verdict or any parameter. Reuses that
script's exact functions (simulate_episode, cost_breakdown,
net_edge_for_scenario, derive_cross_exchange_funding_edge,
realized_basis_pnl_bps, realized_funding_pnl_bps) - no new carry engine,
no retuning.

Answers, on real data, over the full hourly grid for BTC/ETH/SOL:
  1. What eats the edge: fees vs. entry basis vs. exit basis vs. funding
     differential vs. slippage vs. the LOW bound's uncertainty buffer.
  2. Full distributions (gross, BASE, LOW, REALIZED net) per coin per fee
     scenario (maker/maker, maker/taker, taker/taker, adverse).
  3. A passive-entry (partial-maker-fill) sensitivity sweep: blends
     maker/maker and taker/taker REALIZED outcomes by an assumed fill
     probability p, and charges an adverse-selection penalty proportional
     to p (reusing this project's own "adverse" scenario's +10bps
     extra-slippage figure as the per-unit-probability penalty, rather
     than inventing a new number) - maker fill is NEVER treated as
     guaranteed (p=1.0 is shown only as one extreme of the sweep, always
     alongside its adverse-selection cost).
  4. A final verdict: promotes nothing without real/paper execution
     evidence (there is none here - this is still a backtest). Closes the
     whole direction as NO_CANDIDATE_CURRENT_MARKET_STRUCTURE only if even
     the sweep's most favorable realistic point (p<1.0) fails to clear
     SAFETY_BUFFER_BPS on a robust (median, not cherry-picked max) basis.

Historical data limitation carried over unchanged from the parent script:
no historical tick/L2 book exists for either venue, so this cannot
estimate a REAL empirical maker-fill probability or realized adverse-
selection cost from data - the sweep is a stated sensitivity analysis
over assumed probabilities, not a calibrated forecast. This limitation is
exactly why nothing here is promoted to a live/paper candidate.

Usage:
    python scripts/analyze_hyperliquid_bybit_carry_sensitivity.py \
        --data-dir /opt/greenfield-v2/data \
        --price-cache-dir <dir with hl_candles_{COIN}.parquet> \
        --out-dir reports/hyperliquid-bybit-funding-carry \
        --live-spread-bps '{...}' --live-capacity-notional '{...}'
"""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import structlog
import typer

from scripts.screen_hyperliquid_bybit_funding_carry import (
    FEE_SCENARIOS,
    HORIZON_HOURS,
    SAFETY_BUFFER_BPS,
    SYMBOLS,
    _sha256,
    _sha256_dir_summary,
    build_quote,
    hourly_bybit_funding_rate,
    hourly_hl_funding_rate,
    load_funding,
    load_prices,
    net_edge_for_scenario,
    price_at,
    simulate_episode,
)
from src.engines.neutral_market import derive_cross_exchange_funding_edge

log = structlog.get_logger()
app = typer.Typer(add_completion=False)

DIRECTIONS = ("long_bybit_short_hl", "long_hl_short_bybit")
# Reuses the parent script's own "adverse" scenario extra-slippage figure
# as the per-unit-probability adverse-selection penalty for the passive-
# entry sweep below, instead of inventing a new number.
ADVERSE_SELECTION_BPS_AT_FULL_MAKER = 10.0
FILL_PROBABILITIES = (0.0, 0.25, 0.5, 0.75, 1.0)


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p25": None, "median": None, "p75": None, "mean": None, "min": None, "max": None}
    ordered = sorted(values)
    return {
        "p25": statistics.quantiles(ordered, n=4)[0] if len(ordered) >= 4 else ordered[0],
        "median": statistics.median(ordered),
        "p75": statistics.quantiles(ordered, n=4)[2] if len(ordered) >= 4 else ordered[-1],
        "mean": statistics.fmean(ordered),
        "min": ordered[0],
        "max": ordered[-1],
    }


def _positive_run_lengths(flags: list[bool]) -> list[int]:
    runs: list[int] = []
    current = 0
    for flag in flags:
        if flag:
            current += 1
        elif current:
            runs.append(current)
            current = 0
    if current:
        runs.append(current)
    return runs


@app.command()
def analyze(
    data_dir: str = typer.Option(..., help="Greenfield production data root."),
    price_cache_dir: str = typer.Option(
        ..., help="Directory holding hl_candles_{COIN}.parquet basis-proxy caches."
    ),
    out_dir: str = typer.Option(
        "reports/hyperliquid-bybit-funding-carry", help="Where to write the manifest."
    ),
    live_spread_bps: str = typer.Option(
        ..., help="Same live-observed spread JSON as the parent screen."
    ),
    live_capacity_notional: str = typer.Option(
        ..., help="Same live-observed capacity JSON as the parent screen."
    ),
) -> None:
    data_root = Path(data_dir)
    cache_root = Path(price_cache_dir)
    report_root = Path(out_dir)
    spread_bps: dict = json.loads(live_spread_bps)
    capacity_notional: dict = json.loads(live_capacity_notional)

    checksums: dict[str, dict[str, str]] = {}
    per_coin: dict[str, dict] = {}
    # decomposition accumulators, pooled across all coins/hours/directions
    decomposition: dict[str, list[float]] = {
        "funding_differential_bps": [],
        "entry_basis_bps": [],
        "exit_basis_bps": [],
        "realized_basis_pnl_bps": [],
        "realized_funding_pnl_bps": [],
    }
    net_by_scenario_all: dict[str, list[float]] = {s: [] for s in FEE_SCENARIOS}
    base_by_scenario_all: dict[str, list[float]] = {s: [] for s in FEE_SCENARIOS}
    low_by_scenario_all: dict[str, list[float]] = {s: [] for s in FEE_SCENARIOS}
    gross_all: list[float] = []
    fees_by_scenario_bps = {s: sum(v) for s, v in ((s, FEE_SCENARIOS[s]) for s in FEE_SCENARIOS)}

    for coin in SYMBOLS:
        log.info("analyzing", coin=coin)
        hl_funding, bybit_funding = load_funding(data_root, coin)
        hl_prices, bybit_prices = load_prices(data_root, cache_root, coin)

        checksums[coin] = {
            "hyperliquid_funding": _sha256_dir_summary(
                data_root / "hyperliquid_funding_history" / coin
            ),
            "bybit_funding": _sha256_dir_summary(data_root / "funding" / f"{coin}USDT"),
            "hyperliquid_candles": _sha256(cache_root / f"hl_candles_{coin}.parquet"),
            "bybit_klines": _sha256_dir_summary(data_root / "klines" / f"{coin}USDT" / "1h"),
        }

        common_start = max(hl_prices["timestamp"].min(), bybit_prices["timestamp"].min())
        common_end = min(hl_prices["timestamp"].max(), bybit_prices["timestamp"].max())
        hours = pd.date_range(common_start, common_end - timedelta(hours=HORIZON_HOURS), freq="1h")

        coin_net_by_scenario: dict[str, list[float]] = {s: [] for s in FEE_SCENARIOS}
        coin_base_by_scenario: dict[str, list[float]] = {s: [] for s in FEE_SCENARIOS}
        coin_low_by_scenario: dict[str, list[float]] = {s: [] for s in FEE_SCENARIOS}
        coin_gross: list[float] = []
        cap = capacity_notional[coin]

        for hour in hours:
            hl_price = price_at(hl_prices, hour)
            bybit_price = price_at(bybit_prices, hour)
            if hl_price is None or bybit_price is None:
                continue
            hl_rate = hourly_hl_funding_rate(hl_funding, hour)
            bybit_rate = hourly_bybit_funding_rate(bybit_funding, hour)
            if hl_rate != hl_rate or bybit_rate != bybit_rate:
                continue

            hour_dt = hour.to_pydatetime()
            hl_q = build_quote("hyperliquid", coin, hl_price, hl_rate, cap, spread_bps, hour_dt)
            by_q = build_quote("bybit", coin, bybit_price, bybit_rate, cap, spread_bps, hour_dt)

            # A rational actor picks whichever direction the market offers
            # the better edge, once per hour - it is never entered in both
            # directions simultaneously. Pooling both mirror-image
            # directions unconditionally would average entry_basis_bps,
            # funding_differential_bps, and realized basis/funding P&L to
            # EXACTLY zero every single hour (realized_basis_pnl_bps and
            # realized_funding_pnl_bps are each other's exact negation
            # between the two directions, by construction - see their
            # docstrings in the parent screen script), which would erase
            # the very decomposition this analysis exists to produce. Only
            # the better-scoring direction per hour is recorded below,
            # matching the parent screen's own per-hour direction choice
            # (`sorted(decisions..., key=...expected_value_after_cost_bps)`).
            candidates = {}
            for direction, (long_q, short_q) in {
                "long_bybit_short_hl": (by_q, hl_q),
                "long_hl_short_bybit": (hl_q, by_q),
            }.items():
                edge = derive_cross_exchange_funding_edge(
                    long_q,
                    short_q,
                    as_of_utc=hour_dt,
                    funding_periods=HORIZON_HOURS,
                    model_uncertainty_bps=5.0,
                    maximum_quote_age_seconds=3600.0,
                )
                candidates[direction] = edge
            direction, edge = max(
                candidates.items(), key=lambda kv: kv[1].expected_gross_edge_bps.base
            )

            coin_gross.append(edge.expected_gross_edge_bps.base)
            gross_all.append(edge.expected_gross_edge_bps.base)
            decomposition["funding_differential_bps"].append(edge.funding_differential_bps)
            decomposition["entry_basis_bps"].append(edge.entry_basis_bps)

            exit_hour = hour + timedelta(hours=HORIZON_HOURS)
            episode = simulate_episode(
                coin, direction, hour, exit_hour, hl_funding, bybit_funding,
                hl_prices, bybit_prices, cap,
            )

            for scenario in FEE_SCENARIOS:
                net = net_edge_for_scenario(
                    edge.expected_gross_edge_bps, scenario, coin, spread_bps
                )
                coin_base_by_scenario[scenario].append(net.base)
                coin_low_by_scenario[scenario].append(net.low)
                base_by_scenario_all[scenario].append(net.base)
                low_by_scenario_all[scenario].append(net.low)
                if episode is not None:
                    coin_net_by_scenario[scenario].append(episode.net_pnl_bps[scenario])
                    net_by_scenario_all[scenario].append(episode.net_pnl_bps[scenario])

            if episode is not None:
                decomposition["exit_basis_bps"].append(episode.exit_basis_bps)
                decomposition["realized_basis_pnl_bps"].append(episode.realized_basis_pnl_bps)
                decomposition["realized_funding_pnl_bps"].append(episode.realized_funding_pnl_bps)

        per_coin[coin] = {
            "observations": len(coin_gross),
            "gross_edge_base_bps": _quantiles(coin_gross),
            "net_base_bps_by_scenario": {
                s: _quantiles(v) for s, v in coin_base_by_scenario.items()
            },
            "net_low_bps_by_scenario": {s: _quantiles(v) for s, v in coin_low_by_scenario.items()},
            "realized_net_bps_by_scenario": {
                s: _quantiles(v) for s, v in coin_net_by_scenario.items()
            },
            "positive_episode_duration_hours_by_scenario": {
                s: _quantiles(
                    [
                        float(run) * HORIZON_HOURS
                        for run in _positive_run_lengths(
                            [pnl > 0 for pnl in coin_net_by_scenario[s]]
                        )
                    ]
                )
                for s in FEE_SCENARIOS
            },
        }

    # --- cost attribution: mean contribution of each component, pooled ---
    attribution = {
        "mean_funding_differential_bps": statistics.fmean(decomposition["funding_differential_bps"])
        if decomposition["funding_differential_bps"]
        else None,
        "mean_entry_basis_bps": statistics.fmean(decomposition["entry_basis_bps"])
        if decomposition["entry_basis_bps"]
        else None,
        "mean_exit_basis_bps": statistics.fmean(decomposition["exit_basis_bps"])
        if decomposition["exit_basis_bps"]
        else None,
        "mean_realized_basis_pnl_bps": statistics.fmean(decomposition["realized_basis_pnl_bps"])
        if decomposition["realized_basis_pnl_bps"]
        else None,
        "mean_realized_funding_pnl_bps": statistics.fmean(decomposition["realized_funding_pnl_bps"])
        if decomposition["realized_funding_pnl_bps"]
        else None,
        "fees_bps_by_scenario": fees_by_scenario_bps,
        "note": (
            "mean_realized_basis_pnl_bps + mean_realized_funding_pnl_bps is the "
            "average REALIZED gross edge before any fees/slippage; each "
            "scenario's fees_bps_by_scenario is fixed and subtracted in full "
            "every trade (never partially avoidable); slippage and the LOW "
            "bound's uncertainty buffer are scenario-dependent, see "
            "net_low_bps_by_scenario vs net_base_bps_by_scenario per coin above "
            "for their combined effect (LOW - BASE)."
        ),
    }

    # --- passive-entry / partial-maker-fill sensitivity sweep ---
    passive_entry_sweep: dict[str, dict] = {}
    for coin in SYMBOLS:
        maker_vals = per_coin[coin]["realized_net_bps_by_scenario"]["maker_maker"]
        taker_vals = per_coin[coin]["realized_net_bps_by_scenario"]["taker_taker"]
        sweep_for_coin = {}
        for p in FILL_PROBABILITIES:
            # Blend at the summary-statistic level (median/p25/p75), not by
            # re-simulating a synthetic per-observation blend - explicit
            # about being a linear interpolation of the two observed
            # scenario distributions, not a new backtest.
            blended: dict[str, float | None] = {}
            for stat in ("p25", "median", "p75"):
                m = maker_vals[stat]
                t = taker_vals[stat]
                if m is None or t is None:
                    blended[stat] = None
                    continue
                blended[stat] = p * m + (1 - p) * t - p * ADVERSE_SELECTION_BPS_AT_FULL_MAKER
            sweep_for_coin[f"fill_probability_{p:.2f}"] = blended
        passive_entry_sweep[coin] = sweep_for_coin

    # Robust (median-based) verdict: does ANY point on the sweep with
    # p < 1.0 (partial or no maker dependency - p=1.0 excluded because
    # full-maker-fill-guaranteed is exactly the assumption this sweep
    # exists to avoid making) clear the safety buffer on a MEDIAN basis,
    # for every symbol simultaneously (not cherry-picked per-symbol)?
    robust_candidate_found = False
    for p in FILL_PROBABILITIES:
        if p >= 1.0:
            continue
        key = f"fill_probability_{p:.2f}"
        medians = [passive_entry_sweep[coin][key]["median"] for coin in SYMBOLS]
        if all(m is not None and m > SAFETY_BUFFER_BPS for m in medians):
            robust_candidate_found = True
            break

    verdict = (
        "CARRY_CANDIDATE" if robust_candidate_found else "NO_CANDIDATE_CURRENT_MARKET_STRUCTURE"
    )

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "parent_screen_verdict": "NO_CANDIDATE",
        "parent_screen_frozen_parameters": {
            "horizon_hours": HORIZON_HOURS,
            "safety_buffer_bps": SAFETY_BUFFER_BPS,
        },
        "data_versions": {"input_checksums": checksums},
        "per_coin": per_coin,
        "pooled_cost_attribution": attribution,
        "passive_entry_fill_probability_sweep": {
            "method": (
                "Linear interpolation between REALIZED maker/maker and "
                "taker/taker net-edge distributions by assumed fill "
                "probability p, minus p * adverse_selection_bps_at_full_maker "
                f"({ADVERSE_SELECTION_BPS_AT_FULL_MAKER} bps, reused from the "
                "parent screen's own 'adverse' scenario extra-slippage "
                "figure). NOT a calibrated empirical fill-probability model - "
                "no historical L2/tick book data exists for either venue to "
                "estimate one; p is swept as a sensitivity parameter, and "
                "p=1.0 (guaranteed maker fill) is never used as the verdict "
                "basis."
            ),
            "adverse_selection_bps_at_full_maker": ADVERSE_SELECTION_BPS_AT_FULL_MAKER,
            "fill_probabilities_swept": list(FILL_PROBABILITIES),
            "by_coin": passive_entry_sweep,
        },
        "verdict": verdict,
        "verdict_basis": (
            "CARRY_CANDIDATE requires ALL of BTC/ETH/SOL to clear "
            f"SAFETY_BUFFER_BPS ({SAFETY_BUFFER_BPS}bps) on a MEDIAN realized "
            "net-edge basis at some fill probability p < 1.0 in the sweep "
            "above. This is still backtest-only evidence - no live/paper "
            "execution evidence exists - so even a CARRY_CANDIDATE verdict "
            "here is a research flag, not a promotion."
        ),
    }
    report_root.mkdir(parents=True, exist_ok=True)
    manifest_path = report_root / "sensitivity_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    log.info("sensitivity analysis complete", verdict=verdict, manifest=str(manifest_path))


if __name__ == "__main__":
    app()
