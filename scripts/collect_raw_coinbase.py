"""Run the lossless Greenfield v2 Coinbase collector for BTC, ETH, and SOL
spot.

Structurally mirrors scripts/collect_raw_bybit.py and
scripts/collect_raw_okx.py - same start-gate binding
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

from src.data.coinbase_raw_collector import RawCoinbaseCollector
from src.data.raw_collector_config import (
    DEFAULT_RAW_COLLECTOR_CONFIG,
    load_coinbase_raw_collector_config,
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
    product_id: Annotated[
        str | None, typer.Option(help="Run one configured product_id in this process.")
    ] = None,
    collector_id: Annotated[
        str, typer.Option(help="Stable ID used for health and metrics files.")
    ] = "all",
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    soak_session_id = os.environ.get("GREENFIELD_SOAK_ID", "")
    deployed_commit = os.environ.get("GREENFIELD_DEPLOY_COMMIT", "")
    config = load_coinbase_raw_collector_config(config_path)
    if product_id is not None and product_id not in config.product_ids:
        raise typer.BadParameter(
            f"product_id must be one of {config.product_ids}", param_hint="--product-id"
        )
    product_ids = (product_id,) if product_id is not None else config.product_ids
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
    collector = RawCoinbaseCollector(
        product_ids,
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
        "starting lossless Coinbase raw collector",
        product_ids=product_ids,
        market_type=config.market_type,
        data_dir=str(resolved_data_dir),
        soak_session_id=binding.session_id,
        source_commit=binding.source_commit,
        soak_marker=str(binding.marker_path),
        subscribe_messages=collector.subscribe_messages,
    )
    collector.run_forever()


if __name__ == "__main__":
    app()
