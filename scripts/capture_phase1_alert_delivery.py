"""Capture immutable proof of one Phase 1 end-to-end alert delivery test."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from src.data.phase1_alert_delivery import (
    evaluate_phase1_alert_delivery,
    load_alert_journal,
    write_alert_delivery_report,
)
from src.data.raw_soak_session import load_raw_soak_session

app = typer.Typer(add_completion=False)


@app.command()
def capture(
    session_path: Annotated[Path, typer.Option(help="Immutable soak session JSON.")],
    journal_path: Annotated[
        Path, typer.Option(help="Durable alert receiver JSONL journal.")
    ],
    external_receipt_path: Annotated[
        Path, typer.Option(help="Exported external delivery receipt JSON.")
    ],
    event_id: Annotated[
        str,
        typer.Option(help="Event ID in the journal and X-Greenfield-Event-ID header."),
    ],
    operator: Annotated[str, typer.Option(help="Named test operator identity.")],
    report_path: Annotated[
        Path, typer.Option(help="New immutable alert delivery report JSON.")
    ] = Path("reports/phase1_alert_delivery.json"),
) -> None:
    """Validate measured receipts; this command sends no alert itself."""

    try:
        session = load_raw_soak_session(session_path)
        journal = load_alert_journal(journal_path)
        external = _load_json(external_receipt_path)
        report = evaluate_phase1_alert_delivery(
            journal_records=journal,
            external_receipt=external,
            event_id=event_id,
            session_id=session.session_id,
            source_commit=session.source_commit,
            operator=operator,
        )
        write_alert_delivery_report(report_path, report)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        typer.echo(f"invalid alert delivery evidence: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    if not report.qualified:
        raise typer.Exit(code=1)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


if __name__ == "__main__":
    app()
