"""Create immutable descriptive evidence for one exact Gold dataset."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from src.features.distribution_report import (
    audit_feature_distribution,
    write_feature_distribution_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def audit(
    feature_set: Annotated[str, typer.Option(help="Exact Gold feature set.")],
    symbol: Annotated[str, typer.Option(help="Exact Gold symbol.")],
    dataset_version: Annotated[str, typer.Option(help="Exact dataset SHA-256.")],
    code_version: Annotated[str, typer.Option(help="Exact feature code version.")],
    data_dir: Annotated[Path, typer.Option(help="Greenfield data root.")] = Path("data"),
) -> None:
    report = audit_feature_distribution(
        data_dir,
        feature_set=feature_set,
        symbol=symbol,
        dataset_version=dataset_version,
        code_version=code_version,
    )
    path = write_feature_distribution_report(data_dir, report)
    typer.echo(
        f"qualified={report.qualified}; rows={report.row_count}; "
        f"metrics={len(report.metrics)}; warnings={len(report.warnings)}; report={path}"
    )


if __name__ == "__main__":
    app()
