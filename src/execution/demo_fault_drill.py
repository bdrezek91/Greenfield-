"""Immutable evidence contract for controlled Bybit Demo recovery drills."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DemoFaultDrillReport:
    schema_version: int
    qualified: bool
    source_commit: str
    started_at_utc: str
    completed_at_utc: str
    flat_before: bool
    flat_after: bool
    test_exit_code: int
    test_output_sha256: str
    test_targets: tuple[str, ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_demo_fault_drill(
    *,
    source_commit: str,
    started_at_utc: str,
    completed_at_utc: str,
    flat_before: bool,
    flat_after: bool,
    test_exit_code: int,
    test_output_sha256: str,
    test_targets: tuple[str, ...],
) -> DemoFaultDrillReport:
    errors: list[str] = []
    if len(source_commit) != 40 or any(char not in "0123456789abcdef" for char in source_commit):
        errors.append("source commit is not a full lowercase Git SHA")
    if not flat_before:
        errors.append("Bybit Demo account was not flat before the drill")
    if test_exit_code != 0:
        errors.append(f"controlled fault tests exited with code {test_exit_code}")
    if not flat_after:
        errors.append("Bybit Demo account was not flat after the drill")
    if len(test_output_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in test_output_sha256
    ):
        errors.append("test output SHA-256 is invalid")
    if not test_targets:
        errors.append("no controlled fault test targets were recorded")
    return DemoFaultDrillReport(
        schema_version=1,
        qualified=not errors,
        source_commit=source_commit,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        flat_before=flat_before,
        flat_after=flat_after,
        test_exit_code=test_exit_code,
        test_output_sha256=test_output_sha256,
        test_targets=test_targets,
        errors=tuple(errors),
    )


def write_demo_fault_drill_report(path: Path, report: DemoFaultDrillReport) -> None:
    """Create evidence once; never overwrite an earlier drill report."""
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, path)
    except FileExistsError as exc:
        raise FileExistsError(
            f"Demo fault drill report already exists and will not be overwritten: {path}"
        ) from exc
    finally:
        temp_path.unlink(missing_ok=True)
