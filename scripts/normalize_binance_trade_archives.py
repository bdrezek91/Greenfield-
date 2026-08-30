"""Normalize downloaded Binance trades/aggTrades ZIPs into Silver Parquet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_public_archive import GIB
from src.data.binance_trade_archive import normalize_binance_trade_archive

app = typer.Typer(add_completion=False)


@app.command()
def normalize(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")],
    source: Annotated[
        list[Path] | None,
        typer.Option(help="Explicit ZIP; repeat option for multiple archives."),
    ] = None,
    minimum_free_gib: Annotated[
        float, typer.Option(help="Hard reserve checked after every Parquet row group.")
    ] = 5.0,
    chunksize: Annotated[int, typer.Option(help="CSV rows per bounded chunk.")] = 500_000,
) -> None:
    sources = tuple(source or _discover(data_dir))
    if not sources:
        raise typer.BadParameter("no downloaded Binance trade archives found")
    if minimum_free_gib <= 0:
        raise typer.BadParameter("minimum_free_gib must be positive")
    results: list[dict[str, object]] = []
    for index, path in enumerate(sources, start=1):
        typer.echo(f"[{index}/{len(sources)}] {path}", err=True)
        output, changed, metadata = normalize_binance_trade_archive(
            path,
            data_dir=data_dir,
            minimum_free_bytes=int(minimum_free_gib * GIB),
            chunksize=chunksize,
        )
        results.append(
            {
                "source": str(path),
                "output": str(output),
                "normalized": changed,
                "row_count": metadata["row_count"],
            }
        )
    typer.echo(json.dumps({"archives": results}, indent=2, sort_keys=True))


def _discover(data_dir: Path) -> list[Path]:
    root = Path(data_dir) / "external" / "binance-public-data"
    return sorted(
        path
        for path in root.rglob("*.zip")
        if any(part in {"trades", "aggTrades"} for part in path.parts)
    )


if __name__ == "__main__":
    app()
