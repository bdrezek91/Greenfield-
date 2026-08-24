"""Plan or execute bounded multi-venue historical backfill for BTC/ETH/SOL."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.data.historical_backfill import (
    HistoricalBackfillJob,
    build_historical_backfill_jobs,
    load_historical_backfill_config,
)

app = typer.Typer(add_completion=False)


@app.command()
def backfill(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    execute: Annotated[
        bool,
        typer.Option(help="Perform public API downloads; default only prints the plan."),
    ] = False,
    venue: Annotated[str | None, typer.Option(help="Optional venue filter.")] = None,
    symbol: Annotated[str | None, typer.Option(help="Optional BTC/ETH/SOL filter.")] = None,
    timeframe: Annotated[
        str | None, typer.Option(help="Optional kline timeframe filter.")
    ] = None,
    max_jobs: Annotated[
        int | None, typer.Option(help="Optional bounded number of jobs for staged runs.")
    ] = None,
) -> None:
    config = load_historical_backfill_config()
    jobs = build_historical_backfill_jobs(config, as_of=datetime.now(UTC).date())
    selected = tuple(
        job
        for job in jobs
        if (venue is None or job.venue == venue)
        and (symbol is None or job.symbol == symbol)
        and (timeframe is None or job.timeframe == timeframe)
    )
    if max_jobs is not None:
        if max_jobs < 1:
            raise typer.BadParameter("max_jobs must be positive", param_hint="--max-jobs")
        selected = selected[:max_jobs]
    if not selected:
        raise typer.BadParameter("filters selected no historical backfill jobs")
    typer.echo(
        json.dumps(
            {
                "execute": execute,
                "job_count": len(selected),
                "jobs": [_job_dict(job) for job in selected],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if not execute:
        return
    for index, job in enumerate(selected, start=1):
        typer.echo(f"[{index}/{len(selected)}] {job.identity}", err=True)
        _execute(job, data_dir=data_dir)


def _execute(job: HistoricalBackfillJob, *, data_dir: Path) -> None:
    start = job.start.isoformat()
    end = job.end.isoformat()
    if job.dataset == "klines" and job.venue == "bybit":
        from scripts.download_data import download

        download(
            start=start,
            end=end,
            symbol=job.symbol,
            timeframe=job.timeframe,
            data_dir=str(data_dir),
        )
        return
    if job.dataset == "klines" and job.venue == "binance":
        from scripts.download_binance_klines import download

        download(
            start=start,
            end=end,
            symbol=job.symbol,
            timeframe=job.timeframe,
            data_dir=str(data_dir),
        )
        return
    if job.dataset == "klines" and job.venue == "okx":
        from scripts.download_okx_klines import download

        download(
            start=start,
            end=end,
            inst_id=job.venue_symbol,
            timeframe=job.timeframe,
            data_dir=str(data_dir),
        )
        return
    if job.dataset in {"funding", "open_interest"} and job.venue == "bybit":
        from scripts.download_funding_oi import download

        download(
            symbol=job.symbol,
            start=start,
            end=end,
            data_dir=str(data_dir),
            oi_interval=job.timeframe or "5min",
            only=job.dataset,
        )
        return
    raise ValueError(f"unsupported historical backfill job: {job.identity}")


def _job_dict(job: HistoricalBackfillJob) -> dict[str, object]:
    return {
        "dataset": job.dataset,
        "venue": job.venue,
        "symbol": job.symbol,
        "venue_symbol": job.venue_symbol,
        "timeframe": job.timeframe,
        "start": job.start.isoformat(),
        "end": job.end.isoformat(),
    }


if __name__ == "__main__":
    app()

