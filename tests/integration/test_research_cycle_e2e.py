"""One full, small research cycle end to end on synthetic data - proves the
whole pipeline (lock -> queue -> walk-forward -> ledger -> gate -> report)
actually runs and produces a well-formed report, per the brief's "execute
and document at least one small end-to-end research cycle."

Uses a deliberately tiny protocol (short windows, one symbol/timeframe, a
small hypothesis budget) so this stays fast - the default
configs/research_protocol.yaml's windows are sized for real history, not a
unit-test-speed synthetic run.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.schema import COLUMNS
from src.data.storage import write_klines
from src.research.config import (
    CostScenario,
    CostScenarios,
    DataSplitConfig,
    HoldoutConfig,
    HypothesisBudgetConfig,
    HypothesisFamilyConfig,
    PaperPromotionConfig,
    PromotionGateConfig,
    ResearchProtocol,
    RetirementConfig,
    UniverseConfig,
)
from src.research.ledger import TrialLedger
from src.research.orchestrator import CycleConfig, run_cycle
from src.research.promotion import PromotionRegistry


def _tiny_protocol() -> ResearchProtocol:
    return ResearchProtocol(
        version=1,
        universe=UniverseConfig(
            symbols=("BTCUSDT",),
            timeframes_primary=("1h",),
            timeframes_secondary=(),
            timeframes_disabled=("15m", "5m", "1m"),
        ),
        data_split=DataSplitConfig(
            train_days=6, validation_days=2, test_days=2, purge_bars=1, embargo_bars=1
        ),
        holdout=HoldoutConfig(enabled=False, holdout_id="TEST-HOLDOUT", days=0),
        hypothesis_budget=HypothesisBudgetConfig(
            max_new_hypotheses_per_cycle=1,
            max_variants_per_hypothesis=2,
            max_cpu_minutes_per_cycle=60,
            max_wall_clock_minutes_per_cycle=60,
        ),
        hypothesis_families=(
            HypothesisFamilyConfig(
                id="momentum_trend", enabled=True, description="Momentum/trend test family."
            ),
        ),
        costs=CostScenarios(
            base=CostScenario(1.0, 1.0, 1.0, 0),
            adverse=CostScenario(1.5, 2.0, 1.5, 1),
            severe=CostScenario(2.0, 4.0, 2.0, 2),
        ),
        promotion_gate=PromotionGateConfig(
            min_oos_trades=1,
            min_independent_symbols_positive=1,
            aggregate_oos_return_positive_after_adverse_costs=True,
            median_fold_return_positive=False,
            min_fraction_positive_oos_folds=0.0,
            max_single_fold_share_of_total_return=1.0,
            max_single_trade_share_of_total_return=1.0,
            min_deflated_sharpe_ratio=-100.0,
            max_probability_of_backtest_overfitting=1.0,
            require_parameter_stability=False,
            max_drawdown_pct=1.0,
            max_perturbation_degradation_pct=100.0,
            entry_lag_one_bar_must_stay_non_negative=False,
            requires_funding_applied=True,
            requires_mark_to_market=True,
            requires_complete_data=True,
        ),
        paper_promotion=PaperPromotionConfig(
            min_paper_weeks=8,
            max_paper_weeks_for_decision=12,
            min_paper_trades=20,
            max_signal_frequency_deviation_pct=40.0,  # 0-100 scale, see config.py docstring
            max_fill_slippage_bps=25,
            min_fill_rate_pct=90.0,  # 0-100 scale
            no_risk_limit_violations=True,
            requires_human_approval=True,
        ),
        retirement=RetirementConfig(
            max_paper_drawdown_pct=25.0,  # 0-100 scale
            consecutive_degraded_reviews_before_retirement=3,
            auto_kill_on=("risk_limit_breach",),
        ),
    )


def _write_synthetic_data(data_dir: Path) -> pd.Timestamp:
    rng = np.random.default_rng(7)
    n_bars = 24 * 14  # 14 days of 1h bars - enough for one tiny walk-forward window
    close = 100 + np.cumsum(rng.normal(0.05, 0.4, size=n_bars))
    ts = pd.date_range("2024-01-01", periods=n_bars, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        }
    )[list(COLUMNS)]
    write_klines(df, data_dir)
    return ts[-1]


def test_small_end_to_end_research_cycle(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    as_of = _write_synthetic_data(data_dir)

    config = CycleConfig(
        data_dir=data_dir,
        protocol=_tiny_protocol(),
        as_of=as_of,
        starting_balance=Decimal(10_000),
    )
    result = run_cycle(
        config,
        lock_path=tmp_path / "cycle.lock",
        ledger_path=tmp_path / "ledger.jsonl",
        promotion_path=tmp_path / "promotion.json",
        reports_root=tmp_path / "reports",
    )

    assert result.status in ("CANDIDATE", "NO_CANDIDATE")
    assert result.error is None
    assert result.global_trial_count >= 1

    cycle_dir = tmp_path / "reports" / result.cycle_id
    assert (cycle_dir / "manifest.json").exists()
    assert (cycle_dir / "summary.md").exists()
    assert (cycle_dir / "candidates.csv").exists()
    assert (cycle_dir / "rejected.csv").exists()
    assert (cycle_dir / "robustness.json").exists()
    assert (cycle_dir / "data_quality.json").exists()

    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    assert ledger.global_trial_count() == result.global_trial_count

    if result.status == "CANDIDATE":
        registry = PromotionRegistry(tmp_path / "promotion.json")
        state = registry.get(result.selected_candidate_hypothesis_id)
        assert state is not None
        assert state.status == "RESEARCH_CANDIDATE"


def test_cycle_is_idempotent_and_resumable(tmp_path: Path) -> None:
    """A second cycle right after the first must not error, must not reset
    the global trial count, and must be able to acquire the lock again
    (the first cycle released it on completion)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    as_of = _write_synthetic_data(data_dir)
    lock_path = tmp_path / "cycle.lock"
    ledger_path = tmp_path / "ledger.jsonl"

    def _run() -> object:
        return run_cycle(
            CycleConfig(
                data_dir=data_dir,
                protocol=_tiny_protocol(),
                as_of=as_of,
                starting_balance=Decimal(10_000),
            ),
            lock_path=lock_path,
            ledger_path=ledger_path,
            promotion_path=tmp_path / "promotion.json",
            reports_root=tmp_path / "reports",
        )

    first = _run()
    second = _run()
    assert not lock_path.exists()
    assert second.global_trial_count >= first.global_trial_count


def test_cycle_with_no_data_yields_no_candidate_not_a_crash(tmp_path: Path) -> None:
    """No klines on disk for the configured universe: the cycle must still
    complete cleanly with status NO_CANDIDATE and a data_quality entry
    marking the symbol/timeframe unavailable - never an unhandled exception
    and never a silent pass."""
    empty_data_dir = tmp_path / "data"
    empty_data_dir.mkdir()

    result = run_cycle(
        CycleConfig(
            data_dir=empty_data_dir,
            protocol=_tiny_protocol(),
            as_of=pd.Timestamp("2024-06-01", tz="UTC"),
            starting_balance=Decimal(10_000),
        ),
        lock_path=tmp_path / "cycle.lock",
        ledger_path=tmp_path / "ledger.jsonl",
        promotion_path=tmp_path / "promotion.json",
        reports_root=tmp_path / "reports",
    )

    assert result.status == "NO_CANDIDATE"
    assert result.error is None
    assert result.selected_candidate_hypothesis_id is None
    assert all(row.status in ("FAILED_GATE", "ERROR", "REJECTED") for row in result.rejected_trials)
    assert any(not v.get("available", True) for v in result.data_quality.values())


def _tiny_protocol_with_cross_asset() -> ResearchProtocol:
    base = _tiny_protocol()
    return replace(
        base,
        universe=replace(base.universe, symbols=("BTCUSDT", "ETHUSDT")),
        # momentum_trend alone needs 2 strategies x 2 symbols x 1 timeframe = 4
        # slots before cross_asset_regime gets any - budget must exceed that.
        hypothesis_budget=replace(base.hypothesis_budget, max_new_hypotheses_per_cycle=6),
        hypothesis_families=(
            *base.hypothesis_families,
            HypothesisFamilyConfig(
                id="cross_asset_regime", enabled=True, description="Cross-asset test family."
            ),
        ),
    )


def test_cross_asset_family_runs_end_to_end(tmp_path: Path) -> None:
    """Family B (cross_asset_momentum): two symbols' data loaded into one
    engine run, reference-symbol data validated separately from the
    target's, and the cycle completes cleanly either way."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    rng = np.random.default_rng(13)
    n_bars = 24 * 14
    ts = pd.date_range("2024-01-01", periods=n_bars, freq="1h", tz="UTC")
    for symbol, base_price in (("BTCUSDT", 100.0), ("ETHUSDT", 50.0)):
        close = base_price + np.cumsum(rng.normal(0.05, 0.4, size=n_bars))
        df = pd.DataFrame(
            {
                "timestamp": ts,
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 10.0,
                "turnover": 1000.0,
                "symbol": symbol,
                "timeframe": "1h",
            }
        )[list(COLUMNS)]
        write_klines(df, data_dir)

    result = run_cycle(
        CycleConfig(
            data_dir=data_dir,
            protocol=_tiny_protocol_with_cross_asset(),
            as_of=ts[-1],
            starting_balance=Decimal(10_000),
        ),
        lock_path=tmp_path / "cycle.lock",
        ledger_path=tmp_path / "ledger.jsonl",
        promotion_path=tmp_path / "promotion.json",
        reports_root=tmp_path / "reports",
    )

    assert result.error is None
    assert result.status in ("CANDIDATE", "NO_CANDIDATE")
    assert not any(family_id == "cross_asset_regime" for family_id, _ in result.skipped_families)
    all_rows = (*result.passed_trials, *result.rejected_trials)
    assert any(row.family == "cross_asset_regime" for row in all_rows)
    # BTCUSDT is the reference symbol for this family - never its own target.
    assert all(row.symbol != "BTCUSDT" for row in all_rows if row.family == "cross_asset_regime")
