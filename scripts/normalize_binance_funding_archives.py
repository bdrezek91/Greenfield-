"""Normalize downloaded Binance monthly funding archives to Silver."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_funding_archive import normalize_binance_funding_archive

GIB = 1024**3
app = typer.Typer(add_completion=False)


@app.command()
def normalize(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    symbol: Annotated[str | None, typer.Option(help="Optional BTC/ETH/SOL symbol.")] = None,
    minimum_free_gib: Annotated[
        float, typer.Option(help="Hard free-space reserve.")
    ] = 5.0,
) -> None:
    if minimum_free_gib <= 0:
        raise typer.BadParameter("minimum_free_gib must be positive")
    base = (
        Path(data_dir)
        / "external"
        / "binance-public-data"
        / "futures-um"
        / "fundingRate"
    )
    pattern = f"{symbol.upper()}/*.zip" if symbol else "*/*.zip"
    sources = sorted(base.glob(pattern))
    if not sources:
        raise typer.BadParameter("no downloaded Binance funding archives found")
    changed = 0
    rows = 0
    for index, source in enumerate(sources, start=1):
        typer.echo(f"[{index}/{len(sources)}] {source}", err=True)
        _, wrote, metadata = normalize_binance_funding_archive(
            source,
            data_dir=data_dir,
            minimum_free_bytes=int(minimum_free_gib * GIB),
        )
        changed += int(wrote)
        rows += int(metadata["row_count"])
    typer.echo(
        json.dumps(
            {"archives": len(sources), "written": changed, "rows": rows},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
