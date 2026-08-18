"""Wires the research module together into one research cycle.

See docs/AUTONOMOUS_RESEARCH_AUDIT.md's "Dokładny plan zmian" for the
12-step cycle this implements: lock -> disk/data checks -> load queue ->
run bounded hypotheses -> walk-forward + adverse costs -> PBO/DSR -> update
ledger -> rank (allow no winner) -> at most one new PAPER candidate -> write
reports -> exit with an unambiguous status.

The cycle uses half-open event-time windows, pre-segment warm-up, historical
funding, full cost-aware MTM equity, a frozen global DSR trial count,
per-window parameter surfaces, candidate-only Monte Carlo, and a durable
one-time final holdout gate. Every recomputation input is persisted below
the cycle's trial artifact directory.
"""

from __future__ import annotations

import ctypes
import gc
import json
import shutil
import time
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd
import structlog

from src.analytics.experiment import (
    CURRENT_TIMESTAMP_SEMANTICS,
    VALID_FOR_CURRENT_PROTOCOL,
    capture_git_commit,
)
from src.analytics.metrics import compute_equity_metrics, trade_pnl
from src.analytics.monte_carlo import run_monte_carlo
from src.analytics.robustness import deflated_sharpe_ratio, probability_of_backtest_overfitting
from src.backtesting.annualization import periods_per_year_for_timeframe
from src.backtesting.costs import ExecutionAssumptions
from src.backtesting.data_adapter import closed_klines, timeframe_delta
from src.backtesting.funding import FundingAssumptions
from src.backtesting.runner import run_backtest_window
from src.backtesting.walk_forward import WalkForwardWindow, generate_windows, run_walk_forward
from src.data.storage import read_funding, read_klines
from src.data.validate import validate_dataset
from src.regimes.analysis import label_trades_with_regime, metrics_by_regime
from src.regimes.classifier import classify_regimes
from src.research.config import ResearchProtocol
from src.research.evaluator import CandidateEvidence, evaluate_candidate
from src.research.ledger import TrialLedger, TrialRecord, fingerprint_dataset_content
from src.research.locking import CycleLock, CycleLockHeld
from src.research.promotion import PromotionRegistry
from src.research.queue import QueuedHypothesis, build_hypothesis_queue
from src.research.reporting import CycleResult, TrialReportRow, new_cycle_id, write_cycle_report
from src.strategies.registry import BENCHMARK_STRATEGIES, RESEARCH_STRATEGIES

log = structlog.get_logger()

MIN_FREE_DISK_MB = 500


def _release_engine_memory() -> None:
    """Collect reference cycles and return freed heap pages to the OS.

    gc.collect() alone leaves freed arenas in the glibc allocator's free
    list rather than returning them to the OS, so long research workers
    still grow monotonically across hundreds of short-lived Nautilus
    engines. malloc_trim(0) forces that release; it is glibc-specific and
    a no-op (skipped) on platforms without it.
    """
    gc.collect()
    try:
        malloc_trim = ctypes.CDLL(None).malloc_trim
    except (AttributeError, OSError):
        return
    malloc_trim(0)


def _write_trial_artifacts(
    reports_root: Path,
    cycle_id: str,
    hypothesis_id: str,
    artifacts: dict[str, object],
) -> dict[str, str]:
    """Persist every input needed to independently recompute a trial."""
    trial_dir = reports_root / cycle_id / "trials" / hypothesis_id
    trial_dir.mkdir(parents=True, exist_ok=True)
    index: dict[str, str] = {}

    equity = artifacts.get("equity")
    if isinstance(equity, pd.Series | pd.DataFrame):
        path = trial_dir / "equity.parquet"
        equity_frame = (
            equity.rename("equity").to_frame().rename_axis("timestamp").reset_index()
            if isinstance(equity, pd.Series)
            else equity.copy()
        )
        equity_frame.to_parquet(path, index=False)
        index["equity"] = str(path.relative_to(reports_root / cycle_id))

    trades = artifacts.get("trades")
    if isinstance(trades, pd.DataFrame):
        path = trial_dir / "trades.parquet"
        serializable = trades.copy()
        if "funding_cashflows" in serializable:
            serializable["funding_cashflows"] = serializable["funding_cashflows"].map(
                lambda rows: json.dumps([[str(ts), cost] for ts, cost in rows])
            )
        serializable.to_parquet(path, index=False)
        index["trades"] = str(path.relative_to(reports_root / cycle_id))

    pbo_matrix = artifacts.get("pbo_matrix")
    if isinstance(pbo_matrix, pd.DataFrame):
        path = trial_dir / "pbo_matrix.csv"
        pbo_matrix.to_csv(path, index=False)
        index["pbo_matrix"] = str(path.relative_to(reports_root / cycle_id))

    for key in (
        "fold_metrics",
        "selected_params",
        "parameter_surface",
        "cost_stress",
        "regime_metrics",
        "benchmarks",
        "monte_carlo",
        "metadata",
    ):
        if key not in artifacts:
            continue
        path = trial_dir / f"{key}.json"
        path.write_text(json.dumps(artifacts[key], indent=2, default=str))
        index[key] = str(path.relative_to(reports_root / cycle_id))
    return index


def _cost_stress_summary(
    qh: QueuedHypothesis,
    *,
    config: CycleConfig,
    windows: list[WalkForwardWindow],
    selected_params: list[dict],
    funding_history: pd.DataFrame,
) -> dict[str, dict[str, float | int]]:
    """Re-run frozen per-window parameters under BASE and SEVERE costs."""
    strategy_cls, config_cls = RESEARCH_STRATEGIES[qh.strategy_name]
    symbol = qh.hypothesis.symbols[0]
    timeframe = qh.hypothesis.timeframes[0]
    summaries: dict[str, dict[str, float | int]] = {}
    warmup_bars = _required_warmup_bars(qh.param_grid)
    for name in ("base", "severe"):
        scenario = getattr(config.protocol.costs, name)
        funding = FundingAssumptions.from_history(
            funding_history, multiplier=scenario.funding_multiplier
        )
        execution = ExecutionAssumptions(
            fee_multiplier=scenario.fee_multiplier,
            slippage_multiplier=scenario.slippage_multiplier,
            spread_bps=scenario.spread_bps,
            entry_delay_bars=scenario.entry_delay_bars,
            missed_trade_probability=scenario.missed_trade_probability,
        )
        total_pnl = 0.0
        total_trades = 0
        for window, params in zip(windows, selected_params, strict=True):
            result = run_backtest_window(
                strategy_cls=strategy_cls,
                config_cls=config_cls,
                symbol=symbol,
                timeframe=timeframe,
                start=window.test_start,
                end=window.test_end,
                data_dir=config.data_dir,
                starting_balance=config.starting_balance,
                periods_per_year=periods_per_year_for_timeframe(timeframe),
                config_kwargs=params,
                funding_assumptions=funding,
                reference_symbol=qh.reference_symbol,
                reference_symbols=qh.reference_symbols,
                execution=execution,
                warmup_start=window.test_start - timeframe_delta(timeframe) * warmup_bars,
            )
            total_pnl += result.metrics.trade_metrics.net_return
            total_trades += result.metrics.trade_metrics.trades
        summaries[name] = {
            "aggregate_return": total_pnl / float(config.starting_balance),
            "trades": total_trades,
        }
    return summaries


def _regime_summary(
    trades: pd.DataFrame,
    *,
    data_dir: Path,
    symbol: str,
    timeframe: str,
) -> dict[str, dict[str, dict]]:
    """Point-in-time bull/bear/range and high/low-vol trade breakdown."""
    if trades.empty:
        return {"trend": {}, "volatility": {}}
    klines = read_klines(data_dir, symbol, timeframe)
    if klines.empty:
        return {"trend": {}, "volatility": {}}
    frame = klines.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True) + timeframe_delta(
        timeframe
    )
    regimes = classify_regimes(frame)
    labeled = label_trades_with_regime(trades, regimes)
    return {
        "trend": {
            name: asdict(metrics)
            for name, metrics in metrics_by_regime(labeled, "trend_regime").items()
        },
        "volatility": {
            name: asdict(metrics)
            for name, metrics in metrics_by_regime(labeled, "vol_regime").items()
        },
    }


def _benchmark_summary(
    *,
    symbol: str,
    timeframe: str,
    windows: list[WalkForwardWindow],
    config: CycleConfig,
    funding_assumptions: FundingAssumptions,
    execution: ExecutionAssumptions,
) -> dict[str, dict[str, float | int]]:
    """Run the four frozen sanity benchmarks on the exact OOS windows."""
    summaries: dict[str, dict[str, float | int]] = {}
    periods_per_year = periods_per_year_for_timeframe(timeframe)
    for name, (strategy_cls, config_cls) in BENCHMARK_STRATEGIES.items():
        returns: list[float] = []
        trades = 0
        drawdowns: list[float] = []
        for window in windows:
            # Buy-and-hold has no trade_start hook, so it starts exactly at
            # TEST. Rolling benchmarks receive pre-TEST indicator history.
            warmup_start = None
            if "trade_start_ns" in getattr(config_cls, "__struct_fields__", ()):
                warmup_start = window.test_start - timeframe_delta(timeframe) * 250
            result = run_backtest_window(
                strategy_cls=strategy_cls,
                config_cls=config_cls,
                symbol=symbol,
                timeframe=timeframe,
                start=window.test_start,
                end=window.test_end,
                data_dir=config.data_dir,
                starting_balance=config.starting_balance,
                periods_per_year=periods_per_year,
                funding_assumptions=funding_assumptions,
                execution=execution,
                warmup_start=warmup_start,
            )
            returns.append(
                result.metrics.trade_metrics.net_return / float(config.starting_balance)
            )
            trades += result.metrics.trade_metrics.trades
            drawdowns.append(abs(result.metrics.equity_metrics.max_drawdown))
        summaries[name] = {
            "aggregate_return": sum(returns),
            "trades": trades,
            "worst_fold_drawdown": max(drawdowns, default=0.0),
        }
    return summaries


def _frozen_holdout_gate(
    qh: QueuedHypothesis,
    evidence: CandidateEvidence,
    *,
    config: CycleConfig,
    ledger: TrialLedger,
) -> tuple[bool, str, dict[str, object]]:
    """Evaluate the already-selected candidate on the frozen holdout once."""
    holdout = config.protocol.holdout
    family = qh.hypothesis.family
    if not holdout.enabled:
        return True, "holdout disabled by versioned protocol", {}
    if ledger.holdout_already_used(family, holdout.holdout_id):
        return False, "frozen holdout was already consumed for this family/id", {}

    selected = evidence.artifacts.get("selected_params", [])
    selected_rows = selected if isinstance(selected, list) else []
    encoded = [
        json.dumps(row["parameters"], sort_keys=True)
        for row in selected_rows
        if isinstance(row, dict) and "parameters" in row
    ]
    if not encoded:
        return False, "no pre-holdout selected parameters were persisted", {}
    frozen_params = json.loads(Counter(encoded).most_common(1)[0][0])

    symbol = qh.hypothesis.symbols[0]
    timeframe = qh.hypothesis.timeframes[0]
    start, end = holdout.bounds()
    funding = read_funding(config.data_dir, symbol)
    if funding.empty:
        return False, "historical funding data missing for holdout", {}
    funding_assumptions = FundingAssumptions.from_history(
        funding,
        multiplier=config.protocol.costs.adverse.funding_multiplier,
    )
    execution = ExecutionAssumptions(
        fee_multiplier=config.protocol.costs.adverse.fee_multiplier,
        slippage_multiplier=config.protocol.costs.adverse.slippage_multiplier,
        spread_bps=config.protocol.costs.adverse.spread_bps,
        entry_delay_bars=config.protocol.costs.adverse.entry_delay_bars,
        missed_trade_probability=config.protocol.costs.adverse.missed_trade_probability,
    )
    strategy_cls, config_cls = RESEARCH_STRATEGIES[qh.strategy_name]
    warmup_bars = _required_warmup_bars(qh.param_grid)
    result = run_backtest_window(
        strategy_cls=strategy_cls,
        config_cls=config_cls,
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        data_dir=config.data_dir,
        starting_balance=config.starting_balance,
        periods_per_year=periods_per_year_for_timeframe(timeframe),
        config_kwargs=frozen_params,
        funding_assumptions=funding_assumptions,
        reference_symbol=qh.reference_symbol,
        reference_symbols=qh.reference_symbols,
        execution=execution,
        warmup_start=start - timeframe_delta(timeframe) * warmup_bars,
    )
    holdout_return = result.metrics.trade_metrics.net_return / float(config.starting_balance)
    passed = (
        result.metrics.trade_metrics.trades > 0
        and holdout_return > 0
        and abs(result.metrics.equity_metrics.max_drawdown)
        <= config.protocol.promotion_gate.max_drawdown_pct
    )
    status = "PASSED" if passed else "FAILED_GATE"
    ledger.record(
        TrialRecord(
            trial_id=ledger.next_trial_id(),
            hypothesis_id=f"{qh.hypothesis.hypothesis_id}-HOLDOUT",
            parent_hypothesis_id=qh.hypothesis.hypothesis_id,
            family=family,
            rationale="one-time frozen holdout confirmation after all pre-holdout gates",
            symbol=symbol,
            timeframe=timeframe,
            cost_scenario="adverse_holdout",
            status=status,
            dataset_fingerprint=fingerprint_dataset_content(
                config.data_dir, symbol, timeframe
            ),
            holdout_used=True,
            holdout_id=holdout.holdout_id,
            metrics_summary={
                "return": holdout_return,
                "trades": result.metrics.trade_metrics.trades,
                "max_drawdown": result.metrics.equity_metrics.max_drawdown,
            },
            trial_count_contribution=0,
            **_trial_metadata(config.protocol),
        )
    )
    detail = (
        f"holdout {holdout.holdout_id}: return={holdout_return:.4f}, "
        f"trades={result.metrics.trade_metrics.trades}, "
        f"max_drawdown={result.metrics.equity_metrics.max_drawdown:.4f}"
    )
    return passed, detail, {
        "equity": result.equity,
        "trades": result.trades,
        "selected_params": [{"window_id": "FROZEN_HOLDOUT", "parameters": frozen_params}],
        "metadata": {
            "holdout_id": holdout.holdout_id,
            "start": start,
            "end": end,
            "return": holdout_return,
            "passed": passed,
        },
    }


def _engine_version() -> str:
    try:
        return version("nautilus-trader")
    except PackageNotFoundError:
        return "unknown"


def _trial_metadata(protocol: ResearchProtocol) -> dict:
    adverse = ExecutionAssumptions(
        fee_multiplier=protocol.costs.adverse.fee_multiplier,
        slippage_multiplier=protocol.costs.adverse.slippage_multiplier,
        spread_bps=protocol.costs.adverse.spread_bps,
        entry_delay_bars=protocol.costs.adverse.entry_delay_bars,
        missed_trade_probability=protocol.costs.adverse.missed_trade_probability,
    )
    return {
        "git_commit": capture_git_commit(),
        "protocol_version": protocol.version,
        "timestamp_semantics_version": CURRENT_TIMESTAMP_SEMANTICS,
        "backtest_engine_version": _engine_version(),
        "execution_assumptions": asdict(adverse),
        "validity_status": VALID_FOR_CURRENT_PROTOCOL,
    }


def _cycle_metadata() -> dict:
    return {
        "git_commit": capture_git_commit(),
        "timestamp_semantics_version": CURRENT_TIMESTAMP_SEMANTICS,
        "backtest_engine_version": _engine_version(),
    }


class CycleAborted(RuntimeError):
    pass


@dataclass(frozen=True)
class CycleConfig:
    data_dir: Path
    protocol: ResearchProtocol
    as_of: pd.Timestamp
    starting_balance: Decimal = Decimal(100_000)


def _disk_space_ok(path: Path, min_free_mb: int = MIN_FREE_DISK_MB) -> bool:
    usage = shutil.disk_usage(path if path.exists() else path.parent)
    return usage.free / (1024 * 1024) >= min_free_mb


def _positive_symbols_by_strategy(
    raw_results: list[tuple[QueuedHypothesis, TrialReportRow, CandidateEvidence | None]],
) -> dict[str, set[str]]:
    """Strategy name -> set of symbols (among those tested THIS cycle) with
    a positive `aggregate_return_after_adverse_costs`. Used to correct
    `CandidateEvidence.symbols_with_positive_return` after the fact, since
    each hypothesis run only ever covers one symbol.
    """
    result: dict[str, set[str]] = {}
    for qh, _row, evidence in raw_results:
        if evidence is not None and evidence.aggregate_return_after_adverse_costs > 0:
            result.setdefault(qh.strategy_name, set()).add(qh.hypothesis.symbols[0])
    return result


def _clip_lookback(
    earliest_available: pd.Timestamp, end: pd.Timestamp, max_lookback_days: int | None
) -> pd.Timestamp:
    """The walk-forward start timestamp, bounded by
    `data_split.max_lookback_days` regardless of how much history is
    actually on disk - see that field's comment in
    configs/research_protocol.yaml for why this exists."""
    if max_lookback_days is None:
        return earliest_available
    return max(earliest_available, end - pd.Timedelta(days=max_lookback_days))


MAX_PBO_PARTITIONS = 16
"""CSCV's cost is combinatorial: C(n_partitions, n_partitions/2) splits are
evaluated. C(16, 8) = 12,870 (the ~2s benchmark in
docs/PROJECT_STATUS.md's PBO section). Using the raw walk-forward window
count as n_partitions instead (an earlier version of this function did
exactly that) makes the cost explode with more history: C(28, 14) is
40,116,600 - over 3,000x more - and C(100, 50) is astronomically large.
Found in practice: a hypothesis with ~100 windows (years of accumulated
history, before max_lookback_days existed) never finished; even after
capping history to 2 years (~29 windows), PBO alone still took minutes.
Capping n_partitions to this constant, independent of window count, keeps
CSCV's cost bounded and matches src.analytics.robustness's own tested
default - a few windows are excluded from the PBO check when there are
more than this many, which is a fine trade for the check finishing at all.
"""


def _pbo_partitions(n_periods: int, max_partitions: int = MAX_PBO_PARTITIONS) -> int | None:
    """Largest even n_partitions <= min(n_periods, max_partitions). None if
    fewer than 4 usable periods remain (CSCV needs at least a train/test
    split per partition).
    """
    n = min(n_periods, max_partitions)
    if n % 2 != 0:
        n -= 1
    return n if n >= 4 else None


def _perturb(params: dict, factor: float) -> dict:
    """+/-`factor` perturbation of every numeric parameter (int fields are
    rounded, never left at 0). This is the concrete implementation of the
    promotion gate's "no sharp isolated optimum" requirement.
    """
    perturbed: dict[str, object] = {}
    for key, value in params.items():
        if isinstance(value, bool):
            perturbed[key] = value
        elif isinstance(value, int):
            perturbed[key] = max(1, round(value * (1 + factor)))
        elif isinstance(value, float):
            perturbed[key] = value * (1 + factor)
        else:
            perturbed[key] = value
    return perturbed


def _fold_returns(
    trades: pd.DataFrame, windows: list[WalkForwardWindow], starting_balance: float
) -> tuple[float, ...]:
    if trades.empty:
        return tuple(0.0 for _ in windows)
    priced = trade_pnl(trades)
    if "window_id" not in priced:
        raise ValueError("walk-forward trades must carry an explicit window_id")
    returns = []
    for window in windows:
        mask = priced["window_id"] == window.window_id
        returns.append(float(priced.loc[mask, "net_pnl"].sum()) / starting_balance)
    return tuple(returns)


def _max_feasible_trades(
    windows: list[WalkForwardWindow], timeframe: str, param_grid: tuple[dict, ...]
) -> int:
    """Conservative upper bound used to reject an impossible protocol setup.

    It is not an estimate of actual signal frequency.  It only proves that
    the TEST length, holding horizon and one-position-at-a-time lifecycle do
    not make the configured minimum trade count unreachable by construction.
    """
    delta = timeframe_delta(timeframe)
    holding = min(int(params.get("holding_period_bars", 24)) for params in param_grid)
    per_trade_bars = max(1, holding + 1)  # include at least one bar to re-enter
    return sum(
        int((window.test_end - window.test_start) / delta) // per_trade_bars
        for window in windows
    )


def _required_warmup_bars(param_grid: tuple[dict, ...]) -> int:
    """Enough pre-segment history for every bounded rolling parameter."""
    rolling_suffixes = ("bars", "period", "lookback", "observations")
    candidates = [
        int(value)
        for params in param_grid
        for key, value in params.items()
        if isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
        and ("lookback" in key or key.endswith(rolling_suffixes))
    ]
    return max(250, max(candidates, default=0) + 2)


def _perturbation_surface(
    *,
    strategy_cls: type,
    config_cls: type,
    symbol: str,
    timeframe: str,
    windows: list[WalkForwardWindow],
    data_dir: Path,
    starting_balance: Decimal,
    periods_per_year: float,
    selected_params: list[dict],
    base_window_returns: dict[str, float],
    base_aggregate_return: float,
    funding_assumptions: FundingAssumptions | None,
    reference_symbol: str | None = None,
    reference_symbols: tuple[str, ...] = (),
    execution: ExecutionAssumptions | None = None,
    warmup_bars: int = 250,
) -> tuple[float, bool, list[dict]]:
    """Perturb each selected parameter independently inside each TEST fold.

    Each fold keeps the parameters selected by its own VALIDATION segment;
    no last-window parameter is ever projected backwards.  The returned
    surface contains both fold-level and aggregate results for a complete,
    auditable neighborhood test.
    """
    if not selected_params:
        return 1.0, False, []  # fail closed, never treat missing evidence as stable

    numeric_keys = sorted(
        {
            key
            for params in selected_params
            for key, value in params.items()
            if isinstance(value, int | float) and not isinstance(value, bool)
        }
    )
    if not numeric_keys:
        return 1.0, False, []

    surface: list[dict] = []
    aggregate_degradations: list[float] = []
    for key in numeric_keys:
        for factor in (-0.20, -0.10, 0.10, 0.20):
            perturbed_total = 0.0
            fold_rows: list[dict] = []
            for window, base_params in zip(windows, selected_params, strict=True):
                base_return = base_window_returns.get(window.window_id, 0.0)
                if key not in base_params:
                    perturbed_total += base_return
                    continue
                perturbed_params = dict(base_params)
                perturbed_params[key] = _perturb({key: base_params[key]}, factor)[key]
                warmup_start = window.test_start - timeframe_delta(timeframe) * warmup_bars
                result = run_backtest_window(
                    strategy_cls=strategy_cls,
                    config_cls=config_cls,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=window.test_start,
                    end=window.test_end,
                    data_dir=data_dir,
                    starting_balance=starting_balance,
                    periods_per_year=periods_per_year,
                    config_kwargs=perturbed_params,
                    funding_assumptions=funding_assumptions,
                    reference_symbol=reference_symbol,
                    reference_symbols=reference_symbols,
                    execution=execution,
                    warmup_start=warmup_start,
                )
                perturbed_return = (
                    result.metrics.trade_metrics.net_return / float(starting_balance)
                )
                perturbed_total += perturbed_return
                fold_rows.append(
                    {
                        "window_id": window.window_id,
                        "base_value": base_params[key],
                        "perturbed_value": perturbed_params[key],
                        "base_return": base_return,
                        "perturbed_return": perturbed_return,
                    }
                )
            denominator = max(abs(base_aggregate_return), 1e-12)
            degradation = (base_aggregate_return - perturbed_total) / denominator
            aggregate_degradations.append(degradation)
            surface.append(
                {
                    "parameter": key,
                    "factor": factor,
                    "base_aggregate_return": base_aggregate_return,
                    "perturbed_aggregate_return": perturbed_total,
                    "degradation": degradation,
                    "folds": fold_rows,
                }
            )

    worst = max(0.0, *aggregate_degradations)
    local = [
        row["degradation"] for row in surface if abs(float(row["factor"])) == 0.10
    ]
    stable = bool(local) and max(local) <= 0.30 and float(pd.Series(local).median()) <= 0.15
    return worst, stable, surface


def _entry_lag_return(
    *,
    symbol: str,
    timeframe: str,
    trades: pd.DataFrame,
    data_dir: Path,
    starting_balance: float,
) -> float:
    """Approximates "delay entry by one bar": looks up the next bar's close
    after each trade's actual entry_time from the underlying klines and
    recomputes net PnL against that price instead of the real entry price.

    This is a post-hoc approximation, not a re-run of the strategy with a
    genuinely delayed execution path (no strategy in src/strategies exposes
    an entry-delay knob today) - documented as such rather than presented
    as equivalent to a real re-run.
    """
    if trades.empty:
        return 0.0
    df = read_klines(
        data_dir, symbol, timeframe, start=trades["entry_time"].min(), end=trades["exit_time"].max()
    )
    if df.empty:
        return 0.0
    closes = df.set_index("timestamp")["close"].sort_index()

    total = 0.0
    for row in trades.itertuples():
        later = closes[closes.index > row.entry_time]
        if later.empty:
            continue
        delayed_entry_price = float(later.iloc[0])
        total += row.quantity * (row.exit_price - delayed_entry_price) - row.fees - row.funding_cost
    return total / starting_balance


def _run_hypothesis(
    qh: QueuedHypothesis,
    *,
    config: CycleConfig,
    ledger: TrialLedger,
    data_quality: dict,
    dsr_trial_count: int,
    benchmark_cache: dict[tuple[str, str], dict[str, dict[str, float | int]]],
) -> tuple[TrialReportRow, CandidateEvidence | None]:
    hyp = qh.hypothesis
    symbol = hyp.symbols[0]
    timeframe = hyp.timeframes[0]
    protocol = config.protocol

    def failed(reason: str, status: str = "FAILED_GATE") -> TrialReportRow:
        ledger.record(
            TrialRecord(
                trial_id=ledger.next_trial_id(),
                hypothesis_id=hyp.hypothesis_id,
                parent_hypothesis_id=hyp.parent_hypothesis_id,
                family=hyp.family,
                rationale=hyp.rationale,
                symbol=symbol,
                timeframe=timeframe,
                cost_scenario="adverse",
                status=status,
                notes=reason,
                trial_count_contribution=len(qh.param_grid),
                **_trial_metadata(protocol),
            )
        )
        return TrialReportRow(
            hypothesis_id=hyp.hypothesis_id,
            family=hyp.family,
            strategy=qh.strategy_name,
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            deflated_sharpe_ratio=None,
            probability_of_backtest_overfitting=None,
            oos_trades=None,
            aggregate_return_after_adverse_costs=None,
            reason=reason,
        )

    df = read_klines(config.data_dir, symbol, timeframe, start=None, end=config.as_of)
    if df.empty:
        data_quality[f"{symbol}:{timeframe}"] = {"available": False}
        return failed("no data available for this symbol/timeframe"), None

    # Strip the trailing still-forming Bybit candle before validation,
    # fingerprint-dependent research decisions, or window construction.
    df = closed_klines(df, timeframe, config.as_of)
    if df.empty:
        return failed("no completed candles available as of the research cutoff"), None

    report = validate_dataset(df, timeframe, now=config.as_of)
    fingerprint = fingerprint_dataset_content(config.data_dir, symbol, timeframe)
    data_quality[f"{symbol}:{timeframe}"] = {
        "available": True,
        "valid": report.is_valid,
        "rows": len(df),
        "fingerprint": fingerprint,
    }
    if not report.is_valid:
        return failed("data quality check failed (gaps/duplicates/non-UTC/anomalous prices)"), None

    references = list(qh.reference_symbols)
    if qh.reference_symbol is not None and qh.reference_symbol not in references:
        references.append(qh.reference_symbol)
    report_is_valid = report.is_valid
    for reference_symbol in references:
        ref_df = read_klines(
            config.data_dir, reference_symbol, timeframe, start=None, end=config.as_of
        )
        if ref_df.empty:
            data_quality[f"{reference_symbol}:{timeframe}"] = {"available": False}
            return failed(
                f"no data available for reference symbol {reference_symbol}/{timeframe}"
            ), None
        ref_df = closed_klines(ref_df, timeframe, config.as_of)
        ref_report = validate_dataset(ref_df, timeframe, now=config.as_of)
        data_quality[f"{reference_symbol}:{timeframe}"] = {
            "available": True,
            "valid": ref_report.is_valid,
            "rows": len(ref_df),
            "fingerprint": fingerprint_dataset_content(
                config.data_dir, reference_symbol, timeframe
            ),
        }
        if not ref_report.is_valid:
            return failed(
                f"data quality check failed for reference symbol {reference_symbol}"
            ), None
        report_is_valid = report_is_valid and ref_report.is_valid

    delta = timeframe_delta(timeframe)
    latest_event_exclusive = df["timestamp"].max() + delta + pd.Timedelta(nanoseconds=1)
    end = min(latest_event_exclusive, config.as_of)
    if protocol.holdout.enabled:
        holdout_start, _ = protocol.holdout.bounds()
        end = min(end, holdout_start)
    earliest_event = df["timestamp"].min() + delta
    start = _clip_lookback(earliest_event, end, protocol.data_split.max_lookback_days)

    windows = generate_windows(
        start,
        end,
        train_period=pd.Timedelta(days=protocol.data_split.train_days),
        validation_period=pd.Timedelta(days=protocol.data_split.validation_days),
        test_period=pd.Timedelta(days=protocol.data_split.test_days),
        purge_bars=protocol.data_split.purge_bars,
        embargo_bars=protocol.data_split.embargo_bars,
        timeframe=timeframe,
    )
    if not windows:
        return failed("insufficient history for train/validation/test windows"), None
    feasible_trades = _max_feasible_trades(windows, timeframe, qh.param_grid)
    if feasible_trades < protocol.promotion_gate.min_oos_trades:
        return failed(
            "protocol is mathematically unable to reach min_oos_trades: "
            f"upper_bound={feasible_trades}, required="
            f"{protocol.promotion_gate.min_oos_trades}"
        ), None

    strategy_cls, config_cls = RESEARCH_STRATEGIES[qh.strategy_name]
    periods_per_year = periods_per_year_for_timeframe(timeframe)
    funding_history = read_funding(config.data_dir, symbol)
    if funding_history.empty:
        return failed("historical funding data missing for adverse-cost run"), None
    funding_assumptions = FundingAssumptions.from_history(
        funding_history,
        multiplier=protocol.costs.adverse.funding_multiplier,
    )
    adverse_execution = ExecutionAssumptions(
        fee_multiplier=protocol.costs.adverse.fee_multiplier,
        slippage_multiplier=protocol.costs.adverse.slippage_multiplier,
        spread_bps=protocol.costs.adverse.spread_bps,
        entry_delay_bars=protocol.costs.adverse.entry_delay_bars,
        missed_trade_probability=protocol.costs.adverse.missed_trade_probability,
    )
    warmup_bars = _required_warmup_bars(qh.param_grid)

    try:
        wf_result = run_walk_forward(
            strategy_cls=strategy_cls,
            config_cls=config_cls,
            symbol=symbol,
            timeframe=timeframe,
            windows=windows,
            data_dir=config.data_dir,
            starting_balance=config.starting_balance,
            periods_per_year=periods_per_year,
            param_grid=list(qh.param_grid),
            selection_metric="sharpe",
            funding_assumptions=funding_assumptions,
            reference_symbol=qh.reference_symbol,
            reference_symbols=qh.reference_symbols,
            execution=adverse_execution,
            warmup_bars=warmup_bars,
        )
    except Exception as exc:  # noqa: BLE001 - a broken run must never crash the whole cycle
        return failed(f"walk-forward run errored: {exc}", status="ERROR"), None

    oos_trades = wf_result.metrics.trade_metrics.trades
    if oos_trades == 0:
        return failed("zero OOS trades"), None

    starting_balance_f = float(config.starting_balance)
    aggregate_return = wf_result.metrics.trade_metrics.net_return / starting_balance_f
    fold_returns = _fold_returns(wf_result.test_trades, windows, starting_balance_f)
    trade_returns = tuple(
        (trade_pnl(wf_result.test_trades)["net_pnl"] / starting_balance_f).tolist()
    )

    returns_series = wf_result.test_equity.pct_change().dropna()
    dsr = 0.0
    if len(returns_series) >= 2 and returns_series.std(ddof=1) > 0:
        per_period_sharpe = returns_series.mean() / returns_series.std(ddof=1)
        dsr = deflated_sharpe_ratio(
            per_period_sharpe, returns_series, n_trials=max(1, dsr_trial_count)
        ).deflated_sharpe_ratio

    pbo = 1.0  # fail-closed default if not computable
    parameter_stable = False
    matrix = pd.DataFrame()
    n_partitions = _pbo_partitions(len(windows))
    if len(qh.param_grid) >= 2 and n_partitions is not None:
        variant_matrix = []
        for window in windows:
            sharpe_row = []
            for variant in qh.param_grid:
                r = run_backtest_window(
                    strategy_cls=strategy_cls,
                    config_cls=config_cls,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=window.test_start,
                    end=window.test_end,
                    data_dir=config.data_dir,
                    starting_balance=config.starting_balance,
                    periods_per_year=periods_per_year,
                    config_kwargs=variant,
                    funding_assumptions=funding_assumptions,
                    reference_symbol=qh.reference_symbol,
                    reference_symbols=qh.reference_symbols,
                    execution=adverse_execution,
                    warmup_start=(
                        window.test_start - timeframe_delta(timeframe) * warmup_bars
                    ),
                )
                sharpe_row.append(r.metrics.equity_metrics.sharpe)
            variant_matrix.append(sharpe_row)
        matrix = pd.DataFrame(variant_matrix[:n_partitions])
        if not matrix.isna().any().any():
            pbo = probability_of_backtest_overfitting(
                matrix, n_partitions=n_partitions
            ).probability_of_backtest_overfitting
            # Plateau stability is computed below from genuine per-window,
            # per-dimension perturbations rather than this coarse variant grid.
    else:
        parameter_stable = True  # nothing to compare against - not flagged unstable by default

    base_window_returns = {
        window.window_id: fold_return
        for window, fold_return in zip(windows, fold_returns, strict=True)
    }
    degradation, parameter_stable, parameter_surface = _perturbation_surface(
        strategy_cls=strategy_cls,
        config_cls=config_cls,
        symbol=symbol,
        timeframe=timeframe,
        windows=windows,
        data_dir=config.data_dir,
        starting_balance=config.starting_balance,
        periods_per_year=periods_per_year,
        selected_params=wf_result.selected_params,
        base_window_returns=base_window_returns,
        base_aggregate_return=aggregate_return,
        funding_assumptions=funding_assumptions,
        reference_symbol=qh.reference_symbol,
        reference_symbols=qh.reference_symbols,
        execution=adverse_execution,
        warmup_bars=warmup_bars,
    )
    # The adverse run itself used the configured one-bar delay; this is no
    # longer a post-hoc price substitution.
    entry_lag_return = aggregate_return if wf_result.delay_applied else float("-inf")

    fold_metrics = []
    equity_frames: list[pd.DataFrame] = []
    for window, fold_return in zip(windows, fold_returns, strict=True):
        window_trades = wf_result.test_trades.loc[
            wf_result.test_trades["window_id"] == window.window_id
        ]
        window_equity = wf_result.window_equity[window.window_id]
        equity_metrics = compute_equity_metrics(window_equity, periods_per_year)
        equity_frame = (
            window_equity.rename("equity")
            .to_frame()
            .rename_axis("timestamp")
            .reset_index()
        )
        equity_frame["window_id"] = window.window_id
        equity_frames.append(equity_frame)
        fold_metrics.append(
            {
                "window_id": window.window_id,
                "train_start": window.train_start,
                "train_end": window.train_end,
                "validation_start": window.validation_start,
                "validation_end": window.validation_end,
                "test_start": window.test_start,
                "test_end": window.test_end,
                "oos_return": fold_return,
                "oos_trades": len(window_trades),
                "sharpe": equity_metrics.sharpe,
                "max_drawdown": equity_metrics.max_drawdown,
            }
        )

    cost_stress = _cost_stress_summary(
        qh,
        config=config,
        windows=windows,
        selected_params=wf_result.selected_params,
        funding_history=funding_history,
    )
    cost_stress["adverse"] = {
        "aggregate_return": aggregate_return,
        "trades": oos_trades,
    }
    regime_metrics = _regime_summary(
        wf_result.test_trades,
        data_dir=config.data_dir,
        symbol=symbol,
        timeframe=timeframe,
    )
    benchmark_key = (symbol, timeframe)
    if benchmark_key not in benchmark_cache:
        benchmark_cache[benchmark_key] = _benchmark_summary(
            symbol=symbol,
            timeframe=timeframe,
            windows=windows,
            config=config,
            funding_assumptions=funding_assumptions,
            execution=adverse_execution,
        )
    benchmarks = benchmark_cache[benchmark_key]

    evidence = CandidateEvidence(
        oos_trades=oos_trades,
        symbols_with_positive_return=1 if aggregate_return > 0 else 0,
        aggregate_return_after_adverse_costs=aggregate_return,
        fold_returns=fold_returns,
        trade_returns=trade_returns,
        deflated_sharpe_ratio=dsr,
        probability_of_backtest_overfitting=pbo,
        parameter_stable=parameter_stable,
        max_drawdown_pct=abs(wf_result.metrics.equity_metrics.max_drawdown),
        perturbation_degradation_pct=degradation,
        entry_lag_return_after_one_bar_delay=entry_lag_return,
        funding_applied=wf_result.funding_applied,
        fee_applied=wf_result.fee_applied,
        slippage_applied=wf_result.slippage_applied,
        spread_applied=wf_result.spread_applied,
        delay_applied=wf_result.delay_applied,
        missed_trades_applied=wf_result.missed_trades_applied,
        mark_to_market_applied=wf_result.mark_to_market_applied,
        data_complete=report_is_valid,
        artifacts={
            "equity": pd.concat(equity_frames, ignore_index=True),
            "trades": wf_result.test_trades,
            "fold_metrics": fold_metrics,
            "selected_params": [
                {"window_id": window.window_id, "parameters": params}
                for window, params in zip(windows, wf_result.selected_params, strict=True)
            ],
            "parameter_surface": {
                "worst_degradation": degradation,
                "plateau_stable": parameter_stable,
                "points": parameter_surface,
            },
            "cost_stress": cost_stress,
            "regime_metrics": regime_metrics,
            "benchmarks": benchmarks,
            "pbo_matrix": matrix,
            "metadata": {
                "dataset_fingerprint": fingerprint,
                "dsr_trial_count": dsr_trial_count,
                "funding_source": funding_assumptions.source,
                "funding_observations": len(funding_assumptions.historical_rates),
                "execution": asdict(adverse_execution),
                "range_contract": "event-time [start, end)",
                "warmup_bars": warmup_bars,
            },
        },
    )

    status = "PASSED" if aggregate_return > 0 else "FAILED_GATE"
    ledger.record(
        TrialRecord(
            trial_id=ledger.next_trial_id(),
            hypothesis_id=hyp.hypothesis_id,
            parent_hypothesis_id=hyp.parent_hypothesis_id,
            family=hyp.family,
            rationale=hyp.rationale,
            symbol=symbol,
            timeframe=timeframe,
            cost_scenario="adverse",
            status=status,
            dataset_fingerprint=fingerprint,
            metrics_summary={
                "oos_trades": oos_trades,
                "aggregate_return": aggregate_return,
                "dsr": dsr,
                "pbo": pbo,
            },
            trial_count_contribution=len(qh.param_grid),
            **_trial_metadata(protocol),
        )
    )
    row = TrialReportRow(
        hypothesis_id=hyp.hypothesis_id,
        family=hyp.family,
        strategy=qh.strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        status=status,
        deflated_sharpe_ratio=dsr,
        probability_of_backtest_overfitting=pbo,
        oos_trades=oos_trades,
        aggregate_return_after_adverse_costs=aggregate_return,
        reason="see promotion_gate checks" if status == "PASSED" else "non-positive OOS return",
    )
    return row, evidence


def run_cycle(
    config: CycleConfig,
    *,
    lock_path: Path = Path("reports") / "research" / "cycle.lock",
    ledger_path: Path | None = None,
    promotion_path: Path | None = None,
    reports_root: Path = Path("reports") / "research_cycles",
) -> CycleResult:
    cycle_id = new_cycle_id()
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    ledger = TrialLedger(ledger_path) if ledger_path else TrialLedger()
    registry = PromotionRegistry(promotion_path) if promotion_path else PromotionRegistry()

    try:
        with CycleLock(lock_path):
            if not _disk_space_ok(config.data_dir):
                raise CycleAborted("insufficient free disk space for a research cycle")

            queue = build_hypothesis_queue(config.protocol)
            # Freeze one global correction count before the first hypothesis.
            # Every hypothesis in this cycle sees the same value, including
            # all historical attempts plus every planned current attempt.
            dsr_trial_count = ledger.global_dsr_trial_count() + sum(
                len(qh.param_grid) for qh in queue.queued
            )
            data_quality: dict = {}
            passed: list[TrialReportRow] = []
            rejected: list[TrialReportRow] = []
            best: tuple[QueuedHypothesis, TrialReportRow, CandidateEvidence] | None = None
            budget_seconds = config.protocol.hypothesis_budget.max_wall_clock_minutes_per_cycle * 60
            cycle_start = time.monotonic()
            budget_exhausted = False
            artifact_index: dict[str, dict[str, str]] = {}
            benchmark_cache: dict[
                tuple[str, str], dict[str, dict[str, float | int]]
            ] = {}

            # Pass 1: run every queued hypothesis (one symbol/timeframe each)
            # and collect its raw evidence. Deferred instead of evaluated
            # inline, because "min_independent_symbols_positive" is a
            # cross-symbol check - a single hypothesis, by itself, only ever
            # covers one symbol and could never satisfy it on its own.
            raw_results: list[
                tuple[QueuedHypothesis, TrialReportRow, CandidateEvidence | None]
            ] = []
            for qh in queue.queued:
                if time.monotonic() - cycle_start > budget_seconds:
                    budget_exhausted = True
                    log.warning(
                        "research cycle wall-clock budget exhausted - stopping early",
                        hypothesis_id=qh.hypothesis.hypothesis_id,
                        budget_minutes=config.protocol.hypothesis_budget.max_wall_clock_minutes_per_cycle,
                    )
                    rejected.append(
                        TrialReportRow(
                            hypothesis_id=qh.hypothesis.hypothesis_id,
                            family=qh.hypothesis.family,
                            strategy=qh.strategy_name,
                            symbol=qh.hypothesis.symbols[0],
                            timeframe=qh.hypothesis.timeframes[0],
                            status="REJECTED",
                            deflated_sharpe_ratio=None,
                            probability_of_backtest_overfitting=None,
                            oos_trades=None,
                            aggregate_return_after_adverse_costs=None,
                            reason="cycle wall-clock budget exhausted before this hypothesis ran",
                        )
                    )
                    continue

                log.info(
                    "hypothesis started",
                    progress=f"{len(raw_results) + 1}/{len(queue.queued)}",
                    hypothesis_id=qh.hypothesis.hypothesis_id,
                    strategy=qh.strategy_name,
                    symbol=qh.hypothesis.symbols[0],
                    timeframe=qh.hypothesis.timeframes[0],
                    variants=len(qh.param_grid),
                )
                hypothesis_start = time.monotonic()
                row, evidence = _run_hypothesis(
                    qh,
                    config=config,
                    ledger=ledger,
                    data_quality=data_quality,
                    dsr_trial_count=dsr_trial_count,
                    benchmark_cache=benchmark_cache,
                )
                if evidence is not None:
                    artifact_index[qh.hypothesis.hypothesis_id] = _write_trial_artifacts(
                        reports_root,
                        cycle_id,
                        qh.hypothesis.hypothesis_id,
                        evidence.artifacts,
                    )
                log.info(
                    "hypothesis finished",
                    progress=f"{len(raw_results) + 1}/{len(queue.queued)}",
                    hypothesis_id=qh.hypothesis.hypothesis_id,
                    seconds=round(time.monotonic() - hypothesis_start, 1),
                    status=row.status,
                )
                raw_results.append((qh, row, evidence))
                # Nautilus engine objects contain Python/Rust reference cycles.
                # A full hypothesis can create hundreds of short-lived engines;
                # collect those cycles and return freed pages to the OS before
                # the next hypothesis so a bounded research worker does not
                # grow until the OS kills it.
                _release_engine_memory()

            # Cross-symbol positive-return counts per strategy, across every
            # symbol/timeframe combination actually tested THIS cycle - the
            # practical, disclosed interpretation of "independent symbols":
            # same strategy family+name, not necessarily identical selected
            # parameters (each symbol's own walk-forward picks its own best
            # params on VALIDATION, same as a single-symbol run always did).
            positive_symbols_by_strategy = _positive_symbols_by_strategy(raw_results)

            # Pass 2: evaluate each hypothesis against the promotion gate
            # with its evidence corrected to the real cross-symbol count.
            for qh, row, evidence in raw_results:
                if evidence is None:
                    rejected.append(row)
                    continue
                symbols_positive = len(positive_symbols_by_strategy.get(qh.strategy_name, ()))
                evidence = replace(evidence, symbols_with_positive_return=symbols_positive)
                decision = evaluate_candidate(evidence, config.protocol.promotion_gate)
                if decision.passed:
                    if (
                        best is None
                        or evidence.deflated_sharpe_ratio > best[2].deflated_sharpe_ratio
                    ):
                        best = (qh, row, evidence)
                    passed.append(row)
                else:
                    reasons = "; ".join(f"{c.name}: {c.detail}" for c in decision.failed_checks())
                    rejected.append(
                        TrialReportRow(
                            **{**row.__dict__, "status": "FAILED_GATE", "reason": reasons}
                        )
                    )

            selected_id = None
            if best is not None:
                best_qh, row, best_evidence = best
                best_trades = best_evidence.artifacts.get("trades")
                if not isinstance(best_trades, pd.DataFrame):
                    raise CycleAborted("candidate trades missing from artifact payload")
                mc = run_monte_carlo(
                    trade_pnl(best_trades)["net_pnl"],
                    n_simulations=10_000,
                    starting_equity=float(config.starting_balance),
                    seed=42,
                )
                mc_summary = mc.summary()
                best_evidence.artifacts["monte_carlo"] = mc_summary
                artifact_index[row.hypothesis_id] = _write_trial_artifacts(
                    reports_root,
                    cycle_id,
                    row.hypothesis_id,
                    best_evidence.artifacts,
                )
                mc_passed = (
                    float(mc_summary["return_pct_p05"]) > 0
                    and float(mc_summary["risk_of_ruin"]) <= 0.05
                )
                if not mc_passed:
                    passed = [candidate for candidate in passed if candidate != row]
                    rejected.append(
                        TrialReportRow(
                            **{
                                **row.__dict__,
                                "status": "FAILED_GATE",
                                "reason": (
                                    "candidate_monte_carlo: 5th-percentile return must be "
                                    "positive and risk_of_ruin <= 5%"
                                ),
                            }
                        )
                    )
                else:
                    holdout_passed, holdout_detail, holdout_artifacts = (
                        _frozen_holdout_gate(
                            best_qh,
                            best_evidence,
                            config=config,
                            ledger=ledger,
                        )
                    )
                    holdout_artifact_id = f"{row.hypothesis_id}-HOLDOUT"
                    artifact_index[holdout_artifact_id] = _write_trial_artifacts(
                        reports_root,
                        cycle_id,
                        holdout_artifact_id,
                        holdout_artifacts,
                    )
                    if holdout_passed:
                        registry.register_research_candidate(
                            row.hypothesis_id,
                            reason=(
                                "cleared pre-holdout gates, Monte Carlo and one-time "
                                "frozen holdout"
                            ),
                        )
                        selected_id = row.hypothesis_id
                    else:
                        passed = [candidate for candidate in passed if candidate != row]
                        rejected.append(
                            TrialReportRow(
                                **{
                                    **row.__dict__,
                                    "status": "FAILED_GATE",
                                    "reason": f"frozen_holdout: {holdout_detail}",
                                }
                            )
                        )

            status = "CANDIDATE" if selected_id else "NO_CANDIDATE"
            result = CycleResult(
                cycle_id=cycle_id,
                protocol_version=config.protocol.version,
                started_at=started_at,
                finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
                status=status,
                **_cycle_metadata(),
                data_quality=data_quality,
                skipped_families=queue.skipped_families,
                passed_trials=tuple(passed),
                rejected_trials=tuple(rejected),
                selected_candidate_hypothesis_id=selected_id,
                global_trial_count=ledger.global_trial_count(),
                dsr_trial_count=dsr_trial_count,
                robustness={
                    row.hypothesis_id: {
                        "dsr": row.deflated_sharpe_ratio,
                        "pbo": row.probability_of_backtest_overfitting,
                    }
                    for row in (*passed, *rejected)
                    if row.deflated_sharpe_ratio is not None
                },
                artifact_index=artifact_index,
                notes=_render_notes(
                    queue,
                    passed,
                    rejected,
                    selected_id,
                    ledger,
                    budget_exhausted,
                    positive_symbols_by_strategy,
                ),
            )
            write_cycle_report(result, base_dir=reports_root)
            return result
    except CycleLockHeld as exc:
        log.warning("research cycle skipped - lock held", reason=str(exc))
        result = CycleResult(
            cycle_id=cycle_id,
            protocol_version=config.protocol.version,
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
            status="ERROR",
            **_cycle_metadata(),
            error=str(exc),
        )
        write_cycle_report(result, base_dir=reports_root)
        return result
    except CycleAborted as exc:
        log.error("research cycle aborted", reason=str(exc))
        result = CycleResult(
            cycle_id=cycle_id,
            protocol_version=config.protocol.version,
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
            status="ERROR",
            **_cycle_metadata(),
            error=str(exc),
        )
        write_cycle_report(result, base_dir=reports_root)
        return result


def _render_notes(
    queue,
    passed: list[TrialReportRow],
    rejected: list[TrialReportRow],
    selected_id,
    ledger,
    budget_exhausted: bool = False,
    positive_symbols_by_strategy: dict[str, set[str]] | None = None,
) -> dict[str, str]:
    hypothesis_list = ", ".join(qh.hypothesis.hypothesis_id for qh in queue.queued) or "(brak)"
    if positive_symbols_by_strategy:
        edge_inne = "; ".join(
            f"{strategy}: dodatni zwrot na {sorted(symbols)}"
            for strategy, symbols in positive_symbols_by_strategy.items()
        )
    else:
        edge_inne = "Żadna hipoteza w tym cyklu nie miała dodatniego zwrotu na żadnym symbolu."
    budget_note = (
        " UWAGA: budżet czasowy cyklu wyczerpany - część hipotez pominięta."
        if budget_exhausted
        else ""
    )
    return {
        "hipotezy": f"Sprawdzono {len(queue.queued)} hipotez: {hypothesis_list}.{budget_note}",
        "dlaczego": (
            "Rodziny hipotez i uzasadnienia pochodzą z configs/research_protocol.yaml "
            "(momentum/trend na 4h/1d, bounded liczba wariantów)."
        ),
        "liczba_prob": f"Globalny licznik prób (DSR): {ledger.global_trial_count()}.",
        "wyniki_oos": (
            f"{len(passed)} hipotez przeszło bramkę promocji, {len(rejected)} odrzucono."
        ),
        "koszty": "Tak - scenariusz adverse (funding x mnożnik) zastosowany do każdego przebiegu.",
        "pbo": (
            "Policzone per hipoteza z >=2 wariantami (patrz robustness.json); "
            "PBO=1.0 oznacza 'nie policzono - fail-closed'."
        ),
        "stabilnosc": "Patrz pole parameter_stable per hipoteza w trial ledger.",
        "edge_inne": edge_inne,
        "adverse_severe": (
            "Tylko scenariusz adverse zastosowany w tym cyklu (severe: not wired, see audit M4)."
        ),
        "bootstrap": (
            "Nie uruchomiono w tym cyklu (Monte Carlo block bootstrap poza zakresem worker)."
        ),
        "decyzja": "Patrz kolumna 'reason' w candidates.csv / rejected.csv.",
        "nowy_kandydat": (
            f"TAK: {selected_id}" if selected_id else "NIE - status NO_CANDIDATE dla tego cyklu."
        ),
        "paper_status": (
            "Poza zakresem tego cyklu (patrz src/research/promotion.py dla stanu PAPER)."
        ),
        "wymaga_czlowieka": (
            "TAK - promocja do PAPER_CHALLENGER/PAPER_CHAMPION wymaga ręcznej decyzji "
            "(src/research/promotion.py)."
        ),
    }
