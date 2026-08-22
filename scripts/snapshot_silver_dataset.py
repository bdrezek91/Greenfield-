"""Create a reproducible point-in-time Silver dataset catalog entry."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from src.data.dataset_catalog import build_dataset_snapshot, write_dataset_snapshot

app = typer.Typer(add_completion=False)


@app.command()
def snapshot(
    as_of: Annotated[str, typer.Option(help="Timezone-aware point-in-time cutoff.")],
    code_version: Annotated[str, typer.Option(help="Git commit or feature code version.")],
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    symbol: Annotated[str | None, typer.Option(help="Optional exact symbol.")] = None,
    channel: Annotated[str | None, typer.Option(help="Optional exact channel.")] = None,
) -> None:
    value = build_dataset_snapshot(
        data_dir,
        as_of=pd.Timestamp(as_of),
        code_version=code_version,
        symbol=symbol,
        channel=channel,
    )
    path = write_dataset_snapshot(data_dir, value)
    typer.echo(
        f"dataset_version={value.dataset_version}; rows={value.eligible_row_count}; "
        f"parts={value.part_count}; snapshot={path}"
    )


if __name__ == "__main__":
    app()
