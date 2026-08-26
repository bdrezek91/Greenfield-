"""Validate and land an ATAS historical JSONL probe export immutably."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from src.data.atas_history_bridge import ingest_atas_history_export

app = typer.Typer(add_completion=False)


@app.command()
def ingest(
    export_path: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    data_dir: Annotated[Path, typer.Option()] = Path("data"),
    expected_sha256: Annotated[str | None, typer.Option()] = None,
) -> None:
    manifest = ingest_atas_history_export(
        export_path, data_dir, expected_sha256=expected_sha256
    )
    typer.echo(json.dumps(asdict(manifest), sort_keys=True, indent=2))


if __name__ == "__main__":
    app()
