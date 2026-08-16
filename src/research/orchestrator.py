"""Wires the research module together into one research cycle.

See docs/AUTONOMOUS_RESEARCH_AUDIT.md's "Dokładny plan zmian" for the
12-step cycle this implements: lock -> disk/data checks -> load queue ->
run bounded hypotheses -> walk-forward + adverse costs -> PBO/DSR -> update
ledger -> rank (allow no winner) -> at most one new PAPER candidate -> write
reports -> exit with an unambiguous status.

Known, disclosed scope limits for this build (see the module-level notes
below and docs/AUTONOMOUS_RESEARCH_AUDIT.md "Znane ograniczenia"):

- Only the momentum/trend_following ("momentum_trend") family has a
  runnable strategy (src/research/queue.py). Other families are recorded
  as skipped, never faked.
- The "severe"/"adverse" cost scenarios only scale funding in this build -
  fee/slippage multiplier wiring into the execution engine itself
  (ExecutionAssumptions is fixed per BacktestRunSpec today) is a separate,
  larger change than fit in this session (docs/AUTONOMOUS_RESEARCH_AUDIT.md
  M4) and is listed as a known limitation, not silently pretended.
- Parameter-perturbation and entry-lag checks are computed for real
  (see `_perturbation_degradation` / `_entry_lag_return`) but against a
  best-effort approximation - see each function's docstring.
- The frozen holdout is never touched by `run_cycle` - a holdout is
  evaluated at most once by a deliberate, separate call, never
  automatically on every cycle.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import structlog

from src.analytics.metrics import trade_pnl
from src.analytics.robustness import deflated_sharpe_ratio, probability_of_backtest_overfitting
from src.backtesting.annualization import periods_per_year_for_timeframe
from src.backtesting.funding import FundingAssumptions
from src.backtesting.runner import run_backtest_window
from src.backtesting.walk_forward import WalkForwardWindow, generate_windows, run_walk_forward
from src.data.storage import read_klines
from src.data.validate import validate_dataset
from src.research.config import ResearchProtocol
from src.research.evaluator import CandidateEvidence, evaluate_candidate
from src.research.ledger import TrialLedger, TrialRecord, fingerprint_dataset_content
from src.research.locking import CycleLock, CycleLockHeld
from src.research.promotion import PromotionRegistry
from src.research.queue import QueuedHypothesis, build_hypothesis_queue
from src.research.reporting import CycleResult, TrialReportRow, new_cycle_id, write_cycle_report
from src.strategies.registry import ALL_STRATEGIES

log = structlog.get_logger()

MIN_FREE_DISK_MB = 500


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


def _pbo_partitions(n_periods: int) -> int | None:
    """Largest even n_partitions <= n_periods that evenly divides n_periods,
    dropping at most one trailing period. None if fewer than 4 usable
    periods remain (CSCV needs at least a train/test split per partition).
    """
    n = n_periods if n_periods % 2 == 0 else n_periods - 1
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
    returns = []
    for window in windows:
        mask = (priced["exit_time"] >= window.test_start) & (priced["exit_time"] < window.test_end)
        returns.append(float(priced.loc[mask, "net_pnl"].sum()) / starting_balance)
    return tuple(returns)


def _perturbation_degradation(
    *,
    strategy_cls: type,
    config_cls: type,
    symbol: str,
    timeframe: str,
    windows: list[WalkForwardWindow],
    data_dir: Path,
    starting_balance: Decimal,
    periods_per_year: float,
    base_params: dict,
    base_aggregate_return: float,
    funding_assumptions: FundingAssumptions | None,
) -> float:
    """Re-run the strategy's TEST windows with +/-10% and +/-20% perturbed
    parameters and report the worst relative degradation vs. the base
    result. A strategy whose edge depends on one sharp parameter value
    should degrade sharply here; a strategy sitting on a stable plateau
    should not.
    """
    if base_aggregate_return <= 0 or not base_params:
        return 1.0  # nothing to compare against - fail closed, not "0% degradation"

    worst = 0.0
    for factor in (-0.20, -0.10, 0.10, 0.20):
        perturbed_params = _perturb(base_params, factor)
        trades_frames = []
        for window in windows:
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
            )
            trades_frames.append(result.trades)
        combined = pd.concat(trades_frames, ignore_index=True) if trades_frames else pd.DataFrame()
        perturbed_return = (
            float(trade_pnl(combined)["net_pnl"].sum()) / float(starting_balance)
            if not combined.empty
            else 0.0
        )
        degradation = (base_aggregate_return - perturbed_return) / abs(base_aggregate_return)
        worst = max(worst, degradation)
    return worst


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

    end = df["timestamp"].max()
    if protocol.holdout.enabled:
        end = end - pd.Timedelta(days=protocol.holdout.days)
    start = df["timestamp"].min()

    windows = generate_windows(
        start,
        end,
        train_period=pd.Timedelta(days=protocol.data_split.train_days),
        validation_period=pd.Timedelta(days=protocol.data_split.validation_days),
        test_period=pd.Timedelta(days=protocol.data_split.test_days),
    )
    if not windows:
        return failed("insufficient history for train/validation/test windows"), None

    strategy_cls, config_cls = ALL_STRATEGIES[qh.strategy_name]
    periods_per_year = periods_per_year_for_timeframe(timeframe)
    funding_assumptions = FundingAssumptions(
        rate_per_interval=FundingAssumptions().rate_per_interval
        * Decimal(str(protocol.costs.adverse.funding_multiplier))
    )

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
        n_trials = max(1, ledger.global_trial_count(family=hyp.family))
        per_period_sharpe = returns_series.mean() / returns_series.std(ddof=1)
        dsr = deflated_sharpe_ratio(
            per_period_sharpe, returns_series, n_trials=n_trials
        ).deflated_sharpe_ratio

    pbo = 1.0  # fail-closed default if not computable
    parameter_stable = False
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
                )
                sharpe_row.append(r.metrics.equity_metrics.sharpe)
            variant_matrix.append(sharpe_row)
        matrix = pd.DataFrame(variant_matrix[:n_partitions])
        if not matrix.isna().any().any():
            pbo = probability_of_backtest_overfitting(
                matrix, n_partitions=n_partitions
            ).probability_of_backtest_overfitting
            col_means = matrix.mean(axis=0)
            best_idx = int(col_means.idxmax())
            neighbors = [col_means[i] for i in range(len(col_means)) if i != best_idx]
            parameter_stable = bool(neighbors) and (
                col_means[best_idx] - max(neighbors) < 0.5 * (abs(col_means[best_idx]) + 1e-9)
            )
    else:
        parameter_stable = True  # nothing to compare against - not flagged unstable by default

    base_params = wf_result.selected_params[-1] if wf_result.selected_params else {}
    degradation = _perturbation_degradation(
        strategy_cls=strategy_cls,
        config_cls=config_cls,
        symbol=symbol,
        timeframe=timeframe,
        windows=windows,
        data_dir=config.data_dir,
        starting_balance=config.starting_balance,
        periods_per_year=periods_per_year,
        base_params=base_params,
        base_aggregate_return=aggregate_return,
        funding_assumptions=funding_assumptions,
    )
    entry_lag_return = _entry_lag_return(
        symbol=symbol,
        timeframe=timeframe,
        trades=wf_result.test_trades,
        data_dir=config.data_dir,
        starting_balance=starting_balance_f,
    )

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
        mark_to_market_applied=wf_result.mark_to_market_applied,
        data_complete=report.is_valid,
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
            data_quality: dict = {}
            passed: list[TrialReportRow] = []
            rejected: list[TrialReportRow] = []
            best: tuple[TrialReportRow, CandidateEvidence] | None = None
            budget_seconds = config.protocol.hypothesis_budget.max_wall_clock_minutes_per_cycle * 60
            cycle_start = time.monotonic()
            budget_exhausted = False

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

                row, evidence = _run_hypothesis(
                    qh, config=config, ledger=ledger, data_quality=data_quality
                )
                if evidence is None:
                    rejected.append(row)
                    continue
                decision = evaluate_candidate(evidence, config.protocol.promotion_gate)
                if decision.passed:
                    if (
                        best is None
                        or evidence.deflated_sharpe_ratio > best[1].deflated_sharpe_ratio
                    ):
                        best = (row, evidence)
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
                row, _evidence = best
                registry.register_research_candidate(
                    row.hypothesis_id, reason="cleared full promotion gate this cycle"
                )
                selected_id = row.hypothesis_id

            status = "CANDIDATE" if selected_id else "NO_CANDIDATE"
            result = CycleResult(
                cycle_id=cycle_id,
                protocol_version=config.protocol.version,
                started_at=started_at,
                finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
                status=status,
                data_quality=data_quality,
                skipped_families=queue.skipped_families,
                passed_trials=tuple(passed),
                rejected_trials=tuple(rejected),
                selected_candidate_hypothesis_id=selected_id,
                global_trial_count=ledger.global_trial_count(),
                robustness={
                    row.hypothesis_id: {
                        "dsr": row.deflated_sharpe_ratio,
                        "pbo": row.probability_of_backtest_overfitting,
                    }
                    for row in (*passed, *rejected)
                    if row.deflated_sharpe_ratio is not None
                },
                notes=_render_notes(queue, passed, rejected, selected_id, ledger, budget_exhausted),
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
) -> dict[str, str]:
    hypothesis_list = ", ".join(qh.hypothesis.hypothesis_id for qh in queue.queued) or "(brak)"
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
        "edge_inne": (
            "Nie sprawdzono w tym cyklu na wielu symbolach jednocześnie (patrz known limitations)."
        ),
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
