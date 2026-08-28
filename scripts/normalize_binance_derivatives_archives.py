"""Normalize downloaded Binance reference-price and metrics archives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_derivatives_archive import normalize_binance_derivatives_archive

GIB = 1024**3
app = typer.Typer(add_completion=False)


@app.command()
def normalize(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    dataset: Annotated[str | None, typer.Option(help="Optional derivatives dataset.")] = None,
    symbol: Annotated[str | None, typer.Option(help="Optional BTC/ETH/SOL symbol.")] = None,
    minimum_free_gib: Annotated[float, typer.Option(help="Hard free-space reserve.")] = 20.0,
) -> None:
    if minimum_free_gib <= 0:
        raise typer.BadParameter("minimum_free_gib must be positive")
    datasets = [dataset] if dataset else [
        "markPriceKlines", "indexPriceKlines", "premiumIndexKlines", "metrics"
    ]
    allowed = {"markPriceKlines", "indexPriceKlines", "premiumIndexKlines", "metrics"}
    if not set(datasets).issubset(allowed):
        raise typer.BadParameter("unsupported derivatives dataset")
    base = Path(data_dir) / "external" / "binance-public-data" / "futures-um"
    sources: list[Path] = []
    for name in datasets:
        symbol_pattern = symbol.upper() if symbol else "*"
        pattern = (
            f"{name}/{symbol_pattern}/1m/*.zip"
            if name != "metrics"
            else f"{name}/{symbol_pattern}/*.zip"
        )
        sources.extend(base.glob(pattern))
    sources.sort()
    if not sources:
        raise typer.BadParameter("no downloaded Binance derivatives archives found")
    written = rows = 0
    for index, source in enumerate(sources, start=1):
        typer.echo(f"[{index}/{len(sources)}] {source}", err=True)
        _, changed, metadata = normalize_binance_derivatives_archive(
            source,
            data_dir=data_dir,
            minimum_free_bytes=int(minimum_free_gib * GIB),
        )
        written += int(changed)
        rows += int(metadata["row_count"])
    typer.echo(
        json.dumps(
            {"archives": len(sources), "written": written, "rows": rows},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
