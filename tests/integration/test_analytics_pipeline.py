"""End-to-end: trades/equity -> metrics -> experiment record -> saved report.

Exercises the full reproducibility contract from docs/RESEARCH_METHODOLOGY.md
without depending on any strategy or the backtest engine.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.analytics.experiment import ExperimentRecord, ExperimentStore, capture_git_commit
from src.analytics.metrics import compute_metrics
from src.analytics.report import save_report


def test_full_analytics_pipeline(tmp_path: Path) -> None:
    trades = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01T00:00", "2024-01-05T00:00"], utc=True),
            "exit_time": pd.to_datetime(["2024-01-02T00:00", "2024-01-06T00:00"], utc=True),
            "quantity": [1.0, 1.0],
            "entry_price": [100.0, 105.0],
            "exit_price": [105.0, 102.0],
            "fees": [0.5, 0.5],
            "funding_cost": [0.1, 0.1],
        }
    )
    idx = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
    equity = pd.Series([100_000 + i * 50 for i in range(10)], index=idx, dtype=float)

    report = compute_metrics(
        trades, equity, period_start=idx[0], period_end=idx[-1], periods_per_year=365.25
    )
    assert report.trade_metrics.trades == 2

    store = ExperimentStore(tmp_path / "experiments.jsonl")
    record = ExperimentRecord(
        experiment_id=store.next_id(),
        git_commit=capture_git_commit(),
        dataset_version="test-fixture",
        date_range=(str(idx[0]), str(idx[-1])),
        symbols=("BTCUSDT",),
        timeframes=("1d",),
        strategy_version="none",
        parameters={},
        fees={"maker": 0.0002, "taker": 0.00055},
        slippage={"prob_slippage": 0.2},
        funding_assumptions={"rate_per_interval": 0.0001},
        metrics=report.as_dict(),
    )
    store.save(record)

    reloaded = store.get(record.experiment_id)
    assert reloaded is not None
    assert reloaded.metrics["trades"] == 2

    report_path = save_report(record, reports_dir=tmp_path / "reports")
    assert report_path.exists()
    assert "sharpe" in report_path.read_text()
