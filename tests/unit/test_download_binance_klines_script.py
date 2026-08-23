"""scripts/download_binance_klines.py: symbol/timeframe validation before
any network connection is attempted - mirrors
tests/unit/test_collect_binance_derivatives_scripts.py's shape.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from scripts.download_binance_klines import app

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
    assert "symbol must be one of" in str(result.output)


def test_invalid_timeframe_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tmp_path),
            "--symbol",
            "BTCUSDT",
            "--timeframe",
            "3h",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-02",
        ],
    )
    assert result.exit_code != 0
    assert "timeframe must be one of" in str(result.output)
