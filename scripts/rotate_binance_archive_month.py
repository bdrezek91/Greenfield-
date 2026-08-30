"""Capacity-safe verified rotation of one Binance Bronze/Silver month."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_archive_rotation import rotate_binance_archive_month

app = typer.Typer(add_completion=False)


@app.command()
def rotate(
    period: Annotated[str, typer.Option(help="Complete YYYY-MM period.")],
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")],
    backup_root: Annotated[Path, typer.Option(help="Distinct backup volume root.")],
    execute: Annotated[bool, typer.Option(help="Copy and verify instead of inventory.")] = False,
    prune_source: Annotated[
        bool, typer.Option(help="Delete exact source files only after verified backup.")
    ] = False,
) -> None:
    if prune_source and not execute:
        raise typer.BadParameter("--prune-source requires --execute")
    report = rotate_binance_archive_month(
        data_dir,
        backup_root,
        period=period,
        execute=execute,
        prune_source=prune_source,
    )
    typer.echo(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
