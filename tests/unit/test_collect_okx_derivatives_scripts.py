"""scripts/collect_okx_open_interest.py / collect_okx_long_short_ratio.py:
inst_id/period validation before any network connection is attempted -
the OKX counterpart to test_collect_binance_derivatives_scripts.py.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from scripts.collect_okx_long_short_ratio import app as long_short_app
from scripts.collect_okx_open_interest import app as open_interest_app

runner = CliRunner()


def test_open_interest_invalid_inst_id_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        open_interest_app, ["--data-dir", str(tmp_path), "--inst-id", "NOT-REAL-SWAP"]
    )
    assert result.exit_code != 0
    assert "inst_id must be one of" in str(result.output)


def test_long_short_ratio_invalid_inst_id_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        long_short_app, ["--data-dir", str(tmp_path), "--inst-id", "NOT-REAL-SWAP"]
    )
    assert result.exit_code != 0
    assert "inst_id must be one of" in str(result.output)


def test_long_short_ratio_invalid_period_is_rejected(tmp_path: Path) -> None:
    result = runner.invoke(
        long_short_app,
        ["--data-dir", str(tmp_path), "--inst-id", "BTC-USDT-SWAP", "--period", "9m"],
    )
    assert result.exit_code != 0
    assert "period must be one of" in str(result.output)
