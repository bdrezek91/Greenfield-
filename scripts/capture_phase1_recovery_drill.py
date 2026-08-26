"""Capture one immutable, machine-verifiable Phase 1 recovery drill report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from src.data.phase1_recovery_drill import (
    DRILL_TYPES,
    evaluate_phase1_recovery_drill,
    write_recovery_drill_report,
)
from src.data.raw_soak_session import file_sha256, load_raw_soak_session
from src.data.storage_restore_verification import (
    StorageRestoreVerificationError,
    load_storage_restore_verification_report,
)

app = typer.Typer(add_completion=False)


@app.command()
def capture(
    drill_type: Annotated[
        str, typer.Option(help=f"Drill type: {', '.join(DRILL_TYPES)}.")
    ],
    session_path: Annotated[Path, typer.Option(help="Immutable soak session JSON.")],
    before_health_dir: Annotated[
        Path, typer.Option(help="Directory of pre-drill collector health snapshots.")
    ],
    after_health_dir: Annotated[
        Path, typer.Option(help="Directory of post-recovery health snapshots.")
    ],
    replay_report: Annotated[
        Path, typer.Option(help="Strict replay JSON generated after the drill.")
    ],
    operator: Annotated[str, typer.Option(help="Named drill operator identity.")],
    started_at_utc: Annotated[
        str, typer.Option(help="Drill start as timezone-aware ISO-8601 UTC.")
    ],
    completed_at_utc: Annotated[
        str, typer.Option(help="Recovery completion as timezone-aware ISO-8601 UTC.")
    ],
    report_path: Annotated[
        Path, typer.Option(help="New immutable drill report JSON path.")
    ],
    transition_health_dir: Annotated[
        Path | None,
        typer.Option(help="Stopped snapshots required for graceful_sigterm."),
    ] = None,
    boot_id_before: Annotated[
        str | None, typer.Option(help="Host boot ID captured before vps_reboot.")
    ] = None,
    boot_id_after: Annotated[
        str | None, typer.Option(help="Host boot ID captured after vps_reboot.")
    ] = None,
    peak_queue_depth: Annotated[
        int | None, typer.Option(help="Observed peak queue depth for disk_backlog.")
    ] = None,
    queue_capacity: Annotated[
        int | None, typer.Option(help="Configured queue capacity for disk_backlog.")
    ] = None,
    storage_source_sha256: Annotated[
        str | None, typer.Option(help="Verified source backup bundle SHA-256.")
    ] = None,
    storage_restored_sha256: Annotated[
        str | None, typer.Option(help="Verified restored bundle SHA-256.")
    ] = None,
    storage_restore_verification_report: Annotated[
        Path | None,
        typer.Option(help="Qualified tree-comparison report required for storage_restore."),
    ] = None,
) -> None:
    """Validate already captured evidence; this command performs no failure action."""

    try:
        session = load_raw_soak_session(session_path)
        before = _load_health_directory(before_health_dir, session.collector_ids)
        after = _load_health_directory(after_health_dir, session.collector_ids)
        transition = (
            _load_health_directory(transition_health_dir, session.collector_ids)
            if transition_health_dir is not None
            else None
        )
        replay = _load_json(replay_report)
        verification_report_sha256: str | None = None
        if drill_type == "storage_restore":
            if storage_restore_verification_report is None:
                raise ValueError(
                    "storage_restore requires --storage-restore-verification-report"
                )
            verification = load_storage_restore_verification_report(
                storage_restore_verification_report
            )
            storage_source_sha256 = verification.source.tree_sha256
            storage_restored_sha256 = verification.restored.tree_sha256
            verification_report_sha256 = file_sha256(
                storage_restore_verification_report
            )
        report = evaluate_phase1_recovery_drill(
            drill_type=drill_type,
            session=session,
            before_health=before,
            after_health=after,
            transition_health=transition,
            replay_report=replay,
            operator=operator,
            started_at_utc=started_at_utc,
            completed_at_utc=completed_at_utc,
            boot_id_before=boot_id_before,
            boot_id_after=boot_id_after,
            peak_queue_depth=peak_queue_depth,
            queue_capacity=queue_capacity,
            storage_source_sha256=storage_source_sha256,
            storage_restored_sha256=storage_restored_sha256,
            storage_restore_verification_report_sha256=verification_report_sha256,
        )
        write_recovery_drill_report(report_path, report)
    except (
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        StorageRestoreVerificationError,
    ) as exc:
        typer.echo(f"invalid recovery drill evidence: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(json.dumps(report.to_dict(), sort_keys=True, indent=2))
    if not report.qualified:
        raise typer.Exit(code=1)


def _load_health_directory(
    path: Path, collector_ids: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    if not path.is_dir():
        raise ValueError(f"health snapshot directory does not exist: {path}")
    return {
        collector_id: _load_json(path / f"bybit-linear-{collector_id}.json")
        for collector_id in collector_ids
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


if __name__ == "__main__":
    app()
