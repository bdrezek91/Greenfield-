"""Focused tests for orchestrator helpers that don't need the full engine:
resource-budget enforcement, disk-space guard, and the "no LIVE capability
anywhere in src/research/" guarantee.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.research.evaluator import CandidateEvidence
from src.research.hypothesis import Hypothesis
from src.research.orchestrator import (
    _clip_lookback,
    _disk_space_ok,
    _pbo_partitions,
    _perturb,
    _positive_symbols_by_strategy,
)
from src.research.promotion import STATUSES
from src.research.queue import QueuedHypothesis
from src.research.reporting import TrialReportRow


def test_disk_space_ok_for_a_reasonable_threshold(tmp_path: Path) -> None:
    assert _disk_space_ok(tmp_path, min_free_mb=1) is True


def test_disk_space_not_ok_for_an_absurd_threshold(tmp_path: Path) -> None:
    assert _disk_space_ok(tmp_path, min_free_mb=10**9) is False


def test_pbo_partitions_even_periods() -> None:
    assert _pbo_partitions(8) == 8


def test_pbo_partitions_odd_periods_drops_one() -> None:
    assert _pbo_partitions(9) == 8


def test_pbo_partitions_too_few_periods_returns_none() -> None:
    assert _pbo_partitions(2) is None
    assert _pbo_partitions(3) is None


def test_pbo_partitions_caps_large_window_counts() -> None:
    """CSCV cost is combinatorial (C(n, n/2)) - found in practice that
    using the raw window count (e.g. ~100 windows from years of
    accumulated history) made a single PBO check never finish. Must always
    cap at MAX_PBO_PARTITIONS regardless of how many windows exist."""
    assert _pbo_partitions(100) == 16
    assert _pbo_partitions(29) == 16
    assert _pbo_partitions(28) == 16


def test_pbo_partitions_respects_custom_cap() -> None:
    assert _pbo_partitions(100, max_partitions=8) == 8


def test_perturb_scales_numeric_fields() -> None:
    out = _perturb({"lookback_bars": 20, "threshold": 0.01}, 0.10)
    assert out["lookback_bars"] == 22
    assert out["threshold"] == pytest.approx(0.011)


def test_perturb_never_zeroes_an_int_field() -> None:
    out = _perturb({"lookback_bars": 1}, -0.99)
    assert out["lookback_bars"] >= 1


def test_perturb_leaves_non_numeric_fields_untouched() -> None:
    out = _perturb({"name": "momentum"}, 0.10)
    assert out["name"] == "momentum"


def test_no_live_status_exists_anywhere_in_the_promotion_state_machine() -> None:
    """The promotion state machine's universe stops at PAPER_CHAMPION -
    there is no LIVE-adjacent status the research module could ever reach."""
    assert "LIVE" not in STATUSES
    assert all("LIVE" not in status for status in STATUSES)


def _qh(strategy: str, symbol: str) -> QueuedHypothesis:
    hyp = Hypothesis(
        hypothesis_id=f"HYP-momentum_trend-{symbol}",
        family="momentum_trend",
        rationale="test",
        symbols=(symbol,),
        timeframes=("4h",),
        parameters={"strategy": strategy, "param_grid": []},
    )
    return QueuedHypothesis(hypothesis=hyp, strategy_name=strategy, param_grid=())


def _evidence(aggregate_return: float) -> CandidateEvidence:
    return CandidateEvidence(
        oos_trades=10,
        symbols_with_positive_return=0,  # deliberately wrong - the function under test fixes it
        aggregate_return_after_adverse_costs=aggregate_return,
        fold_returns=(),
        trade_returns=(),
        deflated_sharpe_ratio=0.0,
        probability_of_backtest_overfitting=1.0,
        parameter_stable=False,
        max_drawdown_pct=0.0,
        perturbation_degradation_pct=0.0,
        entry_lag_return_after_one_bar_delay=0.0,
        funding_applied=True,
        fee_applied=True,
        slippage_applied=True,
        spread_applied=True,
        delay_applied=True,
        missed_trades_applied=True,
        mark_to_market_applied=True,
        data_complete=True,
    )


def _row(symbol: str) -> TrialReportRow:
    return TrialReportRow(
        hypothesis_id=f"HYP-{symbol}",
        family="momentum_trend",
        strategy="momentum",
        symbol=symbol,
        timeframe="4h",
        status="PASSED",
        deflated_sharpe_ratio=0.0,
        probability_of_backtest_overfitting=1.0,
        oos_trades=10,
        aggregate_return_after_adverse_costs=0.0,
        reason="",
    )


def test_positive_symbols_by_strategy_counts_across_symbols() -> None:
    raw_results = [
        (_qh("momentum", "BTCUSDT"), _row("BTCUSDT"), _evidence(0.05)),
        (_qh("momentum", "ETHUSDT"), _row("ETHUSDT"), _evidence(0.02)),
        (_qh("momentum", "SOLUSDT"), _row("SOLUSDT"), _evidence(-0.01)),
    ]
    result = _positive_symbols_by_strategy(raw_results)
    assert result["momentum"] == {"BTCUSDT", "ETHUSDT"}


def test_positive_symbols_by_strategy_ignores_none_evidence() -> None:
    raw_results = [
        (_qh("momentum", "BTCUSDT"), _row("BTCUSDT"), None),
        (_qh("momentum", "ETHUSDT"), _row("ETHUSDT"), _evidence(0.02)),
    ]
    result = _positive_symbols_by_strategy(raw_results)
    assert result["momentum"] == {"ETHUSDT"}


def test_positive_symbols_by_strategy_separates_different_strategies() -> None:
    raw_results = [
        (_qh("momentum", "BTCUSDT"), _row("BTCUSDT"), _evidence(0.05)),
        (_qh("trend_following", "BTCUSDT"), _row("BTCUSDT"), _evidence(0.05)),
    ]
    result = _positive_symbols_by_strategy(raw_results)
    assert result["momentum"] == {"BTCUSDT"}
    assert result["trend_following"] == {"BTCUSDT"}


def test_positive_symbols_by_strategy_empty_input() -> None:
    assert _positive_symbols_by_strategy([]) == {}


def test_clip_lookback_none_means_no_cap() -> None:
    earliest = pd.Timestamp("2020-01-01", tz="UTC")
    end = pd.Timestamp("2026-01-01", tz="UTC")
    assert _clip_lookback(earliest, end, None) == earliest


def test_clip_lookback_bounds_long_history() -> None:
    """The exact scenario found in practice: years of accumulated history
    on disk (2020-03-25 -> 2026-08-16 for BTCUSDT/4h) must be clipped to
    max_lookback_days, not fed whole into generate_windows()."""
    earliest = pd.Timestamp("2020-03-25", tz="UTC")
    end = pd.Timestamp("2026-06-17", tz="UTC")
    clipped = _clip_lookback(earliest, end, max_lookback_days=730)
    assert clipped == end - pd.Timedelta(days=730)
    assert clipped > earliest


def test_clip_lookback_does_not_extend_short_history() -> None:
    """A cap longer than the available history is a no-op - never invents
    data earlier than what's actually on disk."""
    earliest = pd.Timestamp("2026-01-01", tz="UTC")
    end = pd.Timestamp("2026-03-01", tz="UTC")
    assert _clip_lookback(earliest, end, max_lookback_days=730) == earliest
