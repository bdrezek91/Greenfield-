"""CLI: run the live OKX open-interest-snapshot poller continuously, meant
for `docker compose run -d` like scripts/collect_binance_open_interest.py.

Public data only - no API keys, no account/order actions. Live-verified
against https://www.okx.com in this session - see
src/data/okx_derivatives_client.py's module docstring.

Usage:
    python scripts/collect_okx_open_interest.py --inst-id BTC-USDT-SWAP
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog
import typer

from src.data.okx_derivatives_collector import OkxOpenInterestCollector
from src.data.raw_collector_config import INITIAL_V2_OKX_INST_IDS

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


@app.command()
def collect(
    inst_id: str = typer.Option(..., help=f"One of {INITIAL_V2_OKX_INST_IDS}."),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
    poll_interval_secs: float = typer.Option(60.0, help="How often to poll the endpoint."),
) -> None:
    if inst_id not in INITIAL_V2_OKX_INST_IDS:
        raise typer.BadParameter(
            f"inst_id must be one of {INITIAL_V2_OKX_INST_IDS}", param_hint="--inst-id"
        )

    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))
    log.info(
        "starting okx open-interest collector",
        inst_id=inst_id,
        data_dir=str(resolved_data_dir),
        poll_interval_secs=poll_interval_secs,
    )
    collector = OkxOpenInterestCollector(
        inst_id,
        resolved_data_dir,
        poll_interval_secs=poll_interval_secs,
    )
    collector.run_forever()


if __name__ == "__main__":
    app()
