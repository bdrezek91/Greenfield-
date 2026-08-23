"""CLI to download and store OKX SWAP klines - the OKX counterpart to
scripts/download_binance_klines.py, reusing
src.data.validate.validate_dataset unchanged (it operates on the generic
klines schema, not anything exchange-specific).

Usage:
    python scripts/download_okx_klines.py --start 2024-01-01 --end 2024-02-01
    python scripts/download_okx_klines.py --inst-id BTC-USDT-SWAP --timeframe 1h \
        --start 2024-01-01 --end 2024-02-01
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import structlog
import typer

from src.data.ingest_okx_klines import fetch_okx_klines
from src.data.okx_klines_client import OkxKlineClient
from src.data.okx_klines_storage import write_okx_klines
from src.data.raw_collector_config import INITIAL_V2_OKX_INST_IDS
from src.data.validate import validate_dataset

log = structlog.get_logger()
app = typer.Typer(add_completion=False)

# Canonical timeframe label -> OKX's own `bar` query parameter.
_BAR_BY_TIMEFRAME: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}
SUPPORTED_TIMEFRAMES: tuple[str, ...] = tuple(_BAR_BY_TIMEFRAME)


@app.command()
def download(
    start: str = typer.Option(..., help="Start date, e.g. 2024-01-01"),
    end: str = typer.Option(..., help="End date, e.g. 2024-02-01"),
    inst_id: str | None = typer.Option(
        None, help=f"One of {INITIAL_V2_OKX_INST_IDS}. Default: all."
    ),
    timeframe: str | None = typer.Option(
        None, help=f"One of {SUPPORTED_TIMEFRAMES}. Default: all."
    ),
    data_dir: str | None = typer.Option(None, help="Defaults to $DATA_DIR or ./data"),
) -> None:
    if inst_id is not None and inst_id not in INITIAL_V2_OKX_INST_IDS:
        raise typer.BadParameter(
            f"inst_id must be one of {INITIAL_V2_OKX_INST_IDS}", param_hint="--inst-id"
        )
    if timeframe is not None and timeframe not in SUPPORTED_TIMEFRAMES:
        raise typer.BadParameter(
            f"timeframe must be one of {SUPPORTED_TIMEFRAMES}", param_hint="--timeframe"
        )

    inst_ids = [inst_id] if inst_id else list(INITIAL_V2_OKX_INST_IDS)
    timeframes = [timeframe] if timeframe else list(SUPPORTED_TIMEFRAMES)
    resolved_data_dir = Path(data_dir or os.environ.get("DATA_DIR", "./data"))

    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)

    client = OkxKlineClient()

    for symbol in inst_ids:
        for tf_label in timeframes:
            log.info("fetching", inst_id=symbol, timeframe=tf_label, start=start, end=end)
            df = fetch_okx_klines(
                client,
                inst_id=symbol,
                bar=_BAR_BY_TIMEFRAME[tf_label],
                timeframe=tf_label,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            if df.empty:
                log.warning("no data returned", inst_id=symbol, timeframe=tf_label)
                continue

            report = validate_dataset(df, tf_label)
            if not report.is_valid:
                log.error(
                    "validation failed, not writing to disk",
                    inst_id=symbol,
                    timeframe=tf_label,
                    gaps=len(report.missing_candle_gaps),
                    duplicates=len(report.duplicate_timestamps),
                    anomalies=len(report.anomalous_price_timestamps),
                    non_utc=report.non_utc,
                )
                continue
            if report.zero_volume_timestamps:
                log.warning(
                    "zero-volume candles present",
                    inst_id=symbol,
                    timeframe=tf_label,
                    count=len(report.zero_volume_timestamps),
                )

            written = write_okx_klines(df, resolved_data_dir)
            log.info("stored", inst_id=symbol, timeframe=tf_label, partitions=len(written))


if __name__ == "__main__":
    app()
