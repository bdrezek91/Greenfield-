"""scripts/collect_deribit_market_summary.py: currency/kind validation
before any network connection is attempted - mirrors
tests/unit/test_collect_binance_derivatives_scripts.py's shape.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from scripts.collect_deribit_market_summary import app

runner = CliRunner()


def test_invalid_currency_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["--data-dir", str(tmp_path), "--currency", "DOGE", "--kind", "future"]
    )
    assert result.exit_code != 0
    assert "currency must be one of" in str(result.output)


def test_invalid_kind_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["--data-dir", str(tmp_path), "--currency", "BTC", "--kind", "perpetual"]
    )
    assert result.exit_code != 0
    assert "kind must be one of" in str(result.output)
