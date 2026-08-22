"""Record a secret-free, immutable Phase 1 off-host delivery receipt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.data.phase1_alert_delivery import (
    build_external_alert_receipt,
    write_external_alert_receipt,
)

app = typer.Typer(add_completion=False)


@app.command()
def record(
    event_id: Annotated[
        str,
        typer.Option(help="Greenfield event ID displayed in the delivered message."),
    ],
    received_at_utc: Annotated[
        str,
        typer.Option(help="External channel delivery time as timezone-aware ISO-8601."),
    ],
    receipt_id: Annotated[
        str,
        typer.Option(help="Immutable Gmail Message-ID or Make execution ID."),
    ],
    destination: Annotated[
        str,
        typer.Option(help="Non-secret channel name, for example gmail-operator-alerts."),
    ],
    output_path: Annotated[
        Path,
        typer.Option(help="New immutable receipt JSON path."),
    ] = Path("reports/phase1-evidence/off-host-receipt.json"),
) -> None:
    """Write operator-observed external evidence; this command sends no alert."""

    try:
        receipt = build_external_alert_receipt(
            event_id=event_id,
            received_at_utc=received_at_utc,
            receipt_id=receipt_id,
            destination=destination,
        )
        write_external_alert_receipt(output_path, receipt)
    except (OSError, TypeError, ValueError) as exc:
        typer.echo(f"invalid external alert receipt: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(receipt.to_dict(), sort_keys=True, indent=2))


if __name__ == "__main__":
    app()
