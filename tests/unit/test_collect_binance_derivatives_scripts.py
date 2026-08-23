"""scripts/collect_binance_open_interest.py / collect_binance_long_short_ratio.py:
symbol/period validation before any network connection is attempted -
mirrors tests/unit/test_collect_raw_coinbase_script.py's shape. These
pollers are not part of the raw-collector soak-marker start gate (that
gate is specific to the Bronze WS raw-collector pipeline -
src/data/raw_collector_start_gate.py), so there is nothing else to
validate here without an actual network call.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from scripts.collect_binance_long_short_ratio import app as long_short_app
from scripts.collect_binance_open_interest import app as open_interest_app

runner = CliRunner()


def test_open_interest_invalid_symbol_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        open_interest_app, ["--data-dir", str(tmp_path), "--symbol", "NOTREAL"]
    )
    assert result.exit_code != 0
    assert "symbol must be one of" in str(result.output)


def test_open_interest_invalid_period_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        open_interest_app,
        ["--data-dir", str(tmp_path), "--symbol", "BTCUSDT", "--period", "9m"],
    )
    assert result.exit_code != 0
    assert "period must be one of" in str(result.output)


def test_long_short_ratio_invalid_symbol_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(long_short_app, ["--data-dir", str(tmp_path), "--symbol", "NOTREAL"])
    assert result.exit_code != 0
    assert "symbol must be one of" in str(result.output)


def test_long_short_ratio_invalid_period_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        long_short_app,
        ["--data-dir", str(tmp_path), "--symbol", "BTCUSDT", "--period", "9m"],
    )
    assert result.exit_code != 0
    assert "period must be one of" in str(result.output)
