"""scripts/evaluate_cross_market_evidence_signal.py: asset/universe
validation and the missing-data failure path - mirrors
tests/unit/test_evaluate_derivatives_evidence_signal_script.py's shape.
"""

from __future__ import annotations

from pathlib import Path

from click import unstyle
from typer.testing import CliRunner

from scripts.evaluate_cross_market_evidence_signal import app

runner = CliRunner()


def _normalized_output(result_output: str) -> str:
    """Make CLI assertions independent of ANSI styling and terminal wrapping."""
    return " ".join(unstyle(result_output).split())


def test_unknown_asset_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tmp_path),
            "--asset",
            "DOGE",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
        ],
    )
    assert result.exit_code != 0
    assert "unknown asset" in str(result.output).lower()


def test_asset_not_in_universe_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tmp_path),
            "--asset",
            "SOL",
            "--universe",
            "BTC,ETH",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
        ],
    )
    assert result.exit_code != 0
    assert "member of --universe" in _normalized_output(result.output)


def test_missing_data_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tmp_path),
            "--asset",
            "BTC",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
        ],
    )
    assert result.exit_code == 1
