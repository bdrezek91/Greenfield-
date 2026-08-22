"""Run the lossless Greenfield v2 Bybit collector for BTC, ETH, and SOL."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import structlog
import typer

from src.data.bybit_raw_collector import RawBybitCollector
from src.data.raw_collector_config import (
    DEFAULT_RAW_COLLECTOR_CONFIG,
    load_bybit_raw_collector_config,
)

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
    config = load_bybit_raw_collector_config(config_path)
    if symbol is not None and symbol not in config.symbols:
        raise typer.BadParameter(
            f"symbol must be one of {config.symbols}", param_hint="--symbol"
        )
    symbols = (symbol,) if symbol is not None else config.symbols
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    collector = RawBybitCollector(
        symbols,
        resolved_data_dir,
        market_type=config.market_type,
        orderbook_depth=config.orderbook_depth,
        flush_interval_secs=config.flush_interval_secs,
        max_batch_events=config.max_batch_events,
        queue_capacity=config.queue_capacity,
        ping_interval_secs=config.ping_interval_secs,
        health_interval_secs=config.health_interval_secs,
        minimum_runtime_free_gib=config.minimum_runtime_free_gib,
        reconnect_min_secs=config.reconnect_min_secs,
        reconnect_max_secs=config.reconnect_max_secs,
        collector_id=collector_id,
    )
    log.info(
        "starting lossless Bybit raw collector",
        symbols=symbols,
        market_type=config.market_type,
        data_dir=str(resolved_data_dir),
        topics=collector.topics,
    )
    collector.run_forever()


if __name__ == "__main__":
    app()
