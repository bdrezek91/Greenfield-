"""Run the lossless Greenfield v2 Binance USDT-M Futures collector for BTC,
ETH, and SOL.

Structurally mirrors scripts/collect_raw_okx.py and
scripts/collect_raw_coinbase.py - same start-gate binding
(src.data.raw_collector_start_gate.validate_raw_collector_start), same
config-driven symbol/timing setup. Requires its own soak marker
authorizing this collector_id before it will open a connection; does not
share any state with the active Bybit soak.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import structlog
import typer

from src.data.binance_raw_collector import RawBinanceCollector
from src.data.raw_collector_config import (
    DEFAULT_RAW_COLLECTOR_CONFIG,
    load_binance_raw_collector_config,
)
from src.data.raw_collector_start_gate import validate_raw_collector_start

app = typer.Typer(add_completion=False)
log = structlog.get_logger()


@app.command()
def collect(
    config_path: Annotated[
        Path, typer.Option(help="Versioned raw collector configuration.")
    ] = DEFAULT_RAW_COLLECTOR_CONFIG,
    data_dir: Annotated[
        Path | None, typer.Option(help="Defaults to DATA_DIR or ./data.")
    ] = None,
    symbol: Annotated[
        str | None, typer.Option(help="Run one configured symbol in this process.")
    ] = None,
    collector_id: Annotated[
        str, typer.Option(help="Stable ID used for health and metrics files.")
    ] = "all",
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    soak_session_id = os.environ.get("GREENFIELD_SOAK_ID", "")
    deployed_commit = os.environ.get("GREENFIELD_DEPLOY_COMMIT", "")
    config = load_binance_raw_collector_config(config_path)
    if symbol is not None and symbol not in config.symbols:
        raise typer.BadParameter(
            f"symbol must be one of {config.symbols}", param_hint="--symbol"
        )
    symbols = (symbol,) if symbol is not None else config.symbols
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    try:
        binding = validate_raw_collector_start(
            data_dir=resolved_data_dir,
            session_id=soak_session_id,
            deployed_commit=deployed_commit,
            collector_id=collector_id,
            config_paths=(
                config_path,
                repository_root / "docker-compose.yml",
                repository_root / "docker-compose.monitoring.yml",
            ),
        )
    except (OSError, TypeError, ValueError) as exc:
        raise typer.BadParameter(
            f"collector start gate refused connection: {exc}"
        ) from exc
    collector = RawBinanceCollector(
        symbols,
        resolved_data_dir,
        market_type=config.market_type,
        flush_interval_secs=config.flush_interval_secs,
        max_batch_events=config.max_batch_events,
        queue_capacity=config.queue_capacity,
        ping_interval_secs=config.ping_interval_secs,
        ping_timeout_secs=config.ping_timeout_secs,
        health_interval_secs=config.health_interval_secs,
        minimum_runtime_free_gib=config.minimum_runtime_free_gib,
        reconnect_min_secs=config.reconnect_min_secs,
        reconnect_max_secs=config.reconnect_max_secs,
        collector_id=collector_id,
    )
    log.info(
        "starting lossless Binance raw collector",
        symbols=symbols,
        market_type=config.market_type,
        data_dir=str(resolved_data_dir),
        soak_session_id=binding.session_id,
        source_commit=binding.source_commit,
        soak_marker=str(binding.marker_path),
        subscribe_streams=collector.subscribe_streams,
    )
    collector.run_forever()


if __name__ == "__main__":
    app()
