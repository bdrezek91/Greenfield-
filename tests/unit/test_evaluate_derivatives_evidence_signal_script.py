"""scripts/evaluate_derivatives_evidence_signal.py: symbol validation and
the missing-data failure path - mirrors
tests/unit/test_find_historical_analogs_script.py's shape.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from scripts.evaluate_derivatives_evidence_signal import app

runner = CliRunner()


def test_invalid_symbol_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tmp_path),
            "--symbol",
            "NOTREAL",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
        ],
    )
    assert result.exit_code != 0
    assert "symbol" in str(result.output).lower()


def test_missing_data_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tmp_path),
            "--symbol",
            "BTCUSDT",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
        ],
    )
    assert result.exit_code == 1
