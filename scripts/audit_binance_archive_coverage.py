"""Write retained Binance Bronze/Silver/Gold coverage evidence."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from src.data.binance_archive_coverage import audit_binance_archive_coverage

app = typer.Typer(add_completion=False)


@app.command()
def audit(
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
    output: Annotated[Path | None, typer.Option(help="Optional report path.")] = None,
) -> None:
    report = audit_binance_archive_coverage(data_dir)
    path = output or Path(data_dir).joinpath(
        "reports",
        "binance-public-archive",
        f"coverage-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    typer.echo(json.dumps({"report": str(path), **report}, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
