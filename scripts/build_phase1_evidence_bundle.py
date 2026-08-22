"""Build an immutable Phase 1 evidence manifest from measured artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from src.data.phase1_evidence_bundle import create_phase1_evidence_bundle
from src.data.raw_soak_session import file_sha256, load_raw_soak_session

app = typer.Typer(add_completion=False)


@app.command()
def build(
    session_path: Annotated[Path, typer.Option(help="Immutable soak session JSON.")],
    capacity_forecast_report: Annotated[
        Path, typer.Option(help="Qualified capacity report bound by the session.")
    ],
    soak_report: Annotated[Path, typer.Option(help="Qualified seven-day soak JSON.")],
    replay_report: Annotated[Path, typer.Option(help="Strict full-lake replay JSON.")],
    alert_journal: Annotated[
        Path, typer.Option(help="Durable alert receiver journal export.")
    ],
    external_alert_receipt: Annotated[
        Path, typer.Option(help="Exported off-host alert delivery receipt.")
    ],
    alert_delivery_report: Annotated[
        Path, typer.Option(help="Qualified correlated alert delivery report.")
    ],
    runtime_configuration: Annotated[
        Path, typer.Option(help="Rendered, secret-free deployed configuration.")
    ],
    graceful_sigterm_report: Annotated[
        Path, typer.Option(help="Qualified graceful SIGTERM drill JSON.")
    ],
    process_restart_report: Annotated[
        Path, typer.Option(help="Qualified process restart drill JSON.")
    ],
    vps_reboot_report: Annotated[
        Path, typer.Option(help="Qualified VPS reboot drill JSON.")
    ],
    disk_backlog_report: Annotated[
        Path, typer.Option(help="Qualified bounded backlog drill JSON.")
    ],
    storage_restore_report: Annotated[
        Path, typer.Option(help="Qualified storage restore drill JSON.")
    ],
    root: Annotated[
        Path, typer.Option(help="Portable root containing every artifact.")
    ] = Path("."),
    report_path: Annotated[
        Path, typer.Option(help="New immutable bundle manifest path.")
    ] = Path("reports/phase1_evidence_bundle.json"),
    extra_artifact: Annotated[
        list[str] | None,
        typer.Option(help="Optional repeatable ROLE=PATH evidence entry."),
    ] = None,
) -> None:
    """Hash evidence in place; no source artifact is copied or modified."""

    try:
        resolved_root = root.resolve()
        session_file = _rooted(resolved_root, session_path)
        session = load_raw_soak_session(session_file)
        capacity_file = _rooted(resolved_root, capacity_forecast_report)
        if file_sha256(capacity_file) != session.capacity_forecast_report_sha256:
            raise ValueError("capacity forecast hash does not match soak session")
        artifacts = {
            "soak_session": session_file,
            "capacity_forecast": capacity_file,
            "soak_report": _rooted(resolved_root, soak_report),
            "replay_report": _rooted(resolved_root, replay_report),
            "alert_journal": _rooted(resolved_root, alert_journal),
            "external_alert_receipt": _rooted(resolved_root, external_alert_receipt),
            "alert_delivery_report": _rooted(
                resolved_root, alert_delivery_report
            ),
            "runtime_configuration": _rooted(resolved_root, runtime_configuration),
            "recovery_drill/graceful_sigterm": _rooted(
                resolved_root, graceful_sigterm_report
            ),
            "recovery_drill/process_restart": _rooted(
                resolved_root, process_restart_report
            ),
            "recovery_drill/vps_reboot": _rooted(resolved_root, vps_reboot_report),
            "recovery_drill/disk_backlog": _rooted(
                resolved_root, disk_backlog_report
            ),
            "recovery_drill/storage_restore": _rooted(
                resolved_root, storage_restore_report
            ),
        }
        for item in extra_artifact or []:
            role, separator, raw_path = item.partition("=")
            if not separator or not role or not raw_path:
                raise ValueError("extra artifacts must use ROLE=PATH")
            if role in artifacts:
                raise ValueError(f"duplicate evidence artifact role: {role}")
            artifacts[role] = _rooted(resolved_root, Path(raw_path))
        bundle = create_phase1_evidence_bundle(
            root=resolved_root,
            output_path=_rooted(resolved_root, report_path),
            session_id=session.session_id,
            source_commit=session.source_commit,
            artifacts=artifacts,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        typer.echo(f"invalid Phase 1 evidence bundle input: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(bundle.to_dict(), sort_keys=True, indent=2))


def _rooted(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


if __name__ == "__main__":
    app()
