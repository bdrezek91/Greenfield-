"""Compare a restored storage tree with its independent source tree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.data.storage_restore_verification import (
    StorageRestoreVerificationError,
    verify_storage_restore,
    write_storage_restore_verification_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def verify(
    source_root: Annotated[Path, typer.Option(help="Mounted read-only backup source.")],
    restored_root: Annotated[Path, typer.Option(help="Separate restored tree.")],
    report_path: Annotated[Path, typer.Option(help="New immutable report JSON.")],
) -> None:
    try:
        report = verify_storage_restore(source_root, restored_root)
        write_storage_restore_verification_report(report_path, report)
    except (OSError, StorageRestoreVerificationError) as exc:
        typer.echo(f"storage restore verification failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    if not report.qualified:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
