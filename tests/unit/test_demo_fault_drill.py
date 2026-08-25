from pathlib import Path

import pytest

from src.execution.demo_fault_drill import (
    evaluate_demo_fault_drill,
    write_demo_fault_drill_report,
)

SHA = "a" * 40
DIGEST = "b" * 64


def _report(**overrides: object):
    values = {
        "source_commit": SHA,
        "started_at_utc": "2026-08-25T16:00:00+00:00",
        "completed_at_utc": "2026-08-25T16:01:00+00:00",
        "flat_before": True,
        "flat_after": True,
        "test_exit_code": 0,
        "test_output_sha256": DIGEST,
        "test_targets": ("lag", "partial-exit"),
    }
    values.update(overrides)
    return evaluate_demo_fault_drill(**values)  # type: ignore[arg-type]


def test_fault_drill_requires_green_tests_and_flat_boundaries() -> None:
    assert _report().qualified
    failed = _report(flat_after=False, test_exit_code=1)
    assert not failed.qualified
    assert len(failed.errors) == 2


def test_fault_drill_report_is_immutable(tmp_path: Path) -> None:
    path = tmp_path / "fault.json"
    write_demo_fault_drill_report(path, _report())
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        write_demo_fault_drill_report(path, _report())
