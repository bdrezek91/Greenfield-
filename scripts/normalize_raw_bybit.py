"""Compatibility CLI for verified multi-venue Bronze-to-Silver normalization."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Annotated

import typer

from src.data.normalization_pipeline import normalize_raw_lake

app = typer.Typer(add_completion=False)


@app.command()
def normalize(
    source_data_dir: Annotated[
        Path, typer.Option(help="Greenfield data root containing raw/v1.")
    ] = Path("data"),
    output_data_dir: Annotated[
        Path, typer.Option(help="Data root for the immutable versioned Silver tree.")
    ] = Path("data"),
    exchange: Annotated[
        str, typer.Option(help="Exact registered exchange adapter name.")
    ] = "bybit",
    market_type: Annotated[
        str, typer.Option(help="Exact venue product namespace.")
    ] = "linear",
    symbol: Annotated[
        str | None, typer.Option(help="Optional exact symbol filter.")
    ] = None,
    channel: Annotated[
        str | None, typer.Option(help="Optional exact raw channel filter.")
    ] = None,
    report_path: Annotated[
        Path | None, typer.Option(help="Optional atomic JSON audit report.")
    ] = None,
) -> None:
    report = normalize_raw_lake(
        source_data_dir,
        output_data_dir,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        channel=channel,
    ).to_dict()
    output = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if report_path is None:
        typer.echo(output, nl=False)
        return
    _atomic_write(report_path, output)
    typer.echo(
        f"Verified {report['source_raw_event_count']} Bronze events; "
        f"wrote {report['normalized_row_count']} Silver rows; report: {report_path}"
    )


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    app()
