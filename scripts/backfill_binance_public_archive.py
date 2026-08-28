"""Inventory or download checksum-verified Binance public-data archives."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_public_archive import (
    GIB,
    BinanceArchiveJob,
    build_binance_archive_jobs,
    download_binance_archive,
    load_binance_archive_config,
    probe_binance_archives,
    probes_report,
    select_downloads,
    write_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def backfill(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    execute: Annotated[
        bool,
        typer.Option(help="Download selected archives; default is inventory only."),
    ] = False,
    market: Annotated[str | None, typer.Option(help="spot or futures/um.")] = None,
    dataset: Annotated[str | None, typer.Option(help="Archive dataset name.")] = None,
    symbol: Annotated[str | None, typer.Option(help="BTCUSDT, ETHUSDT or SOLUSDT.")] = None,
    start_period: Annotated[
        str | None, typer.Option(help="Inclusive YYYY-MM or YYYY-MM-DD filter.")
    ] = None,
    end_period: Annotated[
        str | None, typer.Option(help="Inclusive YYYY-MM or YYYY-MM-DD filter.")
    ] = None,
    max_archives: Annotated[int | None, typer.Option(help="Bound selected archive count.")] = None,
    budget_gib: Annotated[
        float | None, typer.Option(help="Bound compressed download bytes.")
    ] = None,
    minimum_free_gib: Annotated[
        float | None, typer.Option(help="Hard free-space reserve after every download.")
    ] = None,
    newest_first: Annotated[bool, typer.Option(help="Prioritize recent archives.")] = True,
    workers: Annotated[int, typer.Option(help="Concurrent HEAD probes, maximum 32.")] = 12,
) -> None:
    config = load_binance_archive_config()
    jobs = _filter_jobs(
        build_binance_archive_jobs(config, as_of=datetime.now(UTC).date()),
        market=market,
        dataset=dataset,
        symbol=symbol,
        start_period=start_period,
        end_period=end_period,
    )
    if max_archives is not None and max_archives < 1:
        raise typer.BadParameter("max_archives must be positive", param_hint="--max-archives")
    if not jobs:
        raise typer.BadParameter("filters selected no Binance archive jobs")
    probes = probe_binance_archives(jobs, workers=workers)
    report = probes_report(probes)
    report_path = (
        Path(data_dir)
        / "reports"
        / "binance-public-archive"
        / f"inventory-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_report(report_path, report)
    effective_budget = config.download_budget_bytes if budget_gib is None else int(budget_gib * GIB)
    effective_reserve = (
        config.minimum_free_bytes if minimum_free_gib is None else int(minimum_free_gib * GIB)
    )
    if effective_budget <= 0 or effective_reserve <= 0:
        raise typer.BadParameter("budget and free-space reserve must be positive")
    selected = select_downloads(
        probes,
        budget_bytes=effective_budget,
        newest_first=newest_first,
    )
    if max_archives is not None:
        selected = selected[:max_archives]
    summary: dict[str, object] = {
        "execute": execute,
        "inventory_report": str(report_path),
        "requested_archives": report["requested_archives"],
        "available_archives": report["available_archives"],
        "known_size_bytes": report["known_size_bytes"],
        "selected_archives": len(selected),
        "selected_size_bytes": sum(value.size_bytes or 0 for value in selected),
        "download_budget_bytes": effective_budget,
        "minimum_free_bytes": effective_reserve,
        "free_bytes_before": shutil.disk_usage(Path(data_dir)).free,
    }
    typer.echo(json.dumps(summary, indent=2, sort_keys=True))
    if not execute:
        return
    downloaded = 0
    reused = 0
    for index, probe in enumerate(selected, start=1):
        typer.echo(f"[{index}/{len(selected)}] {probe.job.identity}", err=True)
        _, changed = download_binance_archive(
            probe,
            data_dir=data_dir,
            minimum_free_bytes=effective_reserve,
        )
        downloaded += int(changed)
        reused += int(not changed)
    typer.echo(
        json.dumps(
            {
                "downloaded_archives": downloaded,
                "reused_archives": reused,
                "free_bytes_after": shutil.disk_usage(Path(data_dir)).free,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _filter_jobs(
    jobs: tuple[BinanceArchiveJob, ...],
    *,
    market: str | None,
    dataset: str | None,
    symbol: str | None,
    start_period: str | None,
    end_period: str | None,
) -> tuple[BinanceArchiveJob, ...]:
    return tuple(
        job
        for job in jobs
        if (market is None or job.market == market)
        and (dataset is None or job.dataset == dataset)
        and (symbol is None or job.symbol == symbol.upper())
        and (start_period is None or job.period >= start_period)
        and (end_period is None or job.period <= end_period)
    )


if __name__ == "__main__":
    app()
