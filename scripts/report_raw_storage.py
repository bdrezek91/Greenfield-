"""Generate a read-only Bronze raw-lake disk-usage/age report.

See src/data/raw_storage_report.py's module docstring: this reports usage
and age only. It never deletes, moves, or rewrites anything.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.data.raw_storage_report import build_raw_storage_report, write_raw_storage_report

app = typer.Typer(add_completion=False)


@app.command()
def report(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    exchange: Annotated[
        str | None, typer.Option(help="Optional single-exchange filter.")
    ] = None,
) -> None:
    value = build_raw_storage_report(data_dir, now_utc=datetime.now(UTC), exchange=exchange)
    path = write_raw_storage_report(data_dir, value)
    gib = value.total_bytes / 1024**3
    typer.echo(
        f"parts={value.total_part_count}; rows={value.total_row_count}; "
        f"total={gib:.2f} GiB; groups={len(value.groups)}; report={path}"
    )


if __name__ == "__main__":
    app()
