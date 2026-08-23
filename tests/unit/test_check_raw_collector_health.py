"""Container healthcheck script: exchange-aware health file resolution.

Cycle 7: the script gained EXCHANGE/MARKET_TYPE env vars so the same image
can healthcheck any raw collector - these tests confirm the Bybit-only
default path is unchanged and that OKX resolves correctly via the new
env vars.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from typer.testing import CliRunner

from scripts.check_raw_collector_health import app

runner = CliRunner()


def _write_health(path: Path, *, status: str = "running") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "heartbeat_ts_ns": time.time_ns(),
                "dropped_event_count": 0,
            }
        ),
        encoding="utf-8",
    )


def test_defaults_to_bybit_linear_path_when_no_exchange_env_set(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("EXCHANGE", raising=False)
    monkeypatch.delenv("MARKET_TYPE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COLLECTOR_ID", "btcusdt")
    _write_health(tmp_path / "health" / "bybit-linear-btcusdt.json")

    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.stdout
    assert "healthy" in result.stdout


def test_resolves_okx_swap_path_via_exchange_and_market_type_env(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EXCHANGE", "okx")
    monkeypatch.setenv("MARKET_TYPE", "swap")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COLLECTOR_ID", "btc-usdt-swap")
    _write_health(tmp_path / "health" / "okx-swap-btc-usdt-swap.json")

    result = runner.invoke(app, [])

    assert result.exit_code == 0, result.stdout
    assert "healthy" in result.stdout


def test_unhealthy_when_health_file_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("EXCHANGE", raising=False)
    monkeypatch.delenv("MARKET_TYPE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("COLLECTOR_ID", raising=False)

    result = runner.invoke(app, [])

    assert result.exit_code == 1


def test_unhealthy_when_collector_reported_a_dropped_event(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EXCHANGE", "okx")
    monkeypatch.setenv("MARKET_TYPE", "swap")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COLLECTOR_ID", "eth-usdt-swap")
    path = tmp_path / "health" / "okx-swap-eth-usdt-swap.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"status": "failed", "heartbeat_ts_ns": time.time_ns(), "dropped_event_count": 1}
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, [])

    assert result.exit_code == 1
