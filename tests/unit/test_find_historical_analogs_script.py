"""scripts/find_historical_analogs.py: symbol/timeframe validation and the
no-data failure path - mirrors
tests/unit/test_download_binance_klines_script.py's shape. The real
end-to-end success path (real klines -> features -> regime -> analogs) is
covered by tests/unit/test_analogs_bridge.py at the library level and was
live-verified manually against real downloaded Bybit BTCUSDT klines this
cycle.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from scripts.find_historical_analogs import app

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
    assert "timeframe" in str(result.output).lower()


def test_empty_feature_columns_is_rejected(tmp_path: Path) -> None:
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
            "--feature-columns",
            "  ,  ",
        ],
    )
    assert result.exit_code != 0
    assert "at least one column" in str(result.output)


def test_no_klines_in_range_exits_nonzero(tmp_path: Path) -> None:
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
