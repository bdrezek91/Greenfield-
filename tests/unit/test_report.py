"""Markdown report rendering must include the required experiment metadata sections."""

from __future__ import annotations

from pathlib import Path

from src.analytics.experiment import ExperimentRecord
from src.analytics.report import render_markdown, save_report


def _record() -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id="EXP-000001",
        git_commit="abc123",
        dataset_version="deadbeef",
        date_range=("2024-01-01", "2024-02-01"),
        symbols=("BTCUSDT", "ETHUSDT"),
        timeframes=("1h",),
        strategy_version="none",
        parameters={"foo": 1},
        fees={"maker": 0.0002},
        slippage={"prob_slippage": 0.2},
        funding_assumptions={"rate_per_interval": 0.0001},
        metrics={"sharpe": 1.23, "trades": 10},
    )


def test_render_markdown_includes_key_sections() -> None:
    md = render_markdown(_record())
    assert "# EXP-000001" in md
    assert "abc123" in md
    assert "BTCUSDT, ETHUSDT" in md
    assert '"sharpe": 1.23' in md
    assert "## Metrics" in md


def test_save_report_writes_file(tmp_path: Path) -> None:
    record = _record()
    path = save_report(record, reports_dir=tmp_path)

    assert path.exists()
    assert path.name == "EXP-000001.md"
    assert path.read_text() == render_markdown(record)
