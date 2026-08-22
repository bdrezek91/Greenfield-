"""A Phase 1 soak start is fresh, commit-bound, hashed, and immutable."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.data.raw_soak_session import (
    MINIMUM_SOAK_DURATION_SECS,
    create_raw_soak_session,
    file_sha256,
    load_raw_soak_session,
)

COMMIT = "a" * 40
NOW_NS = 1_800_000_000_000_000_000


def _preflight(path: Path, *, qualified: bool = True, commit: str = COMMIT) -> Path:
    generated = datetime.fromtimestamp(NOW_NS / 1_000_000_000, tz=UTC).isoformat()
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": generated,
                "qualified": qualified,
                "expected_commit": commit,
                "observations": {
                    "source_commit": commit,
                    "working_tree_clean": True,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _configs(tmp_path: Path) -> tuple[Path, ...]:
    paths = []
    for name in ("collector.yml", "compose.yml"):
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        paths.append(path)
    return tuple(paths)


def _capacity(
    path: Path,
    *,
    qualified: bool = True,
    commit: str = COMMIT,
    target_data_dir: Path | None = None,
    generated_ns: int = NOW_NS,
) -> Path:
    generated = datetime.fromtimestamp(generated_ns / 1_000_000_000, tz=UTC).isoformat()
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": generated,
                "source_commit": commit,
                "target_data_dir": str((target_data_dir or path.parent).resolve()),
                "qualified": qualified,
                "required_capacity_bytes": 1,
                "available_capacity_bytes": 2,
                "checks": {"lossless": qualified, "fits": qualified},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_session_binds_fresh_preflight_commit_and_config_hashes(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path / "preflight.json")
    capacity = _capacity(tmp_path / "capacity.json", target_data_dir=tmp_path)
    output = tmp_path / "sessions" / "phase1-20270115.json"
    session = create_raw_soak_session(
        session_id="phase1-20270115",
        source_commit=COMMIT,
        preflight_report_path=preflight,
        capacity_forecast_report_path=capacity,
        expected_data_dir=tmp_path,
        config_paths=_configs(tmp_path),
        output_path=output,
        now_ns=NOW_NS,
    )

    assert session.minimum_duration_secs == MINIMUM_SOAK_DURATION_SECS
    assert session.preflight_report_sha256 == file_sha256(preflight)
    assert session.capacity_forecast_report_sha256 == file_sha256(capacity)
    assert set(session.config_sha256) == {"collector.yml", "compose.yml"}
    assert load_raw_soak_session(output) == session


def test_existing_session_marker_is_never_overwritten(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path / "preflight.json")
    capacity = _capacity(tmp_path / "capacity.json", target_data_dir=tmp_path)
    output = tmp_path / "session.json"
    arguments = {
        "session_id": "phase1-session",
        "source_commit": COMMIT,
        "preflight_report_path": preflight,
        "capacity_forecast_report_path": capacity,
        "expected_data_dir": tmp_path,
        "config_paths": _configs(tmp_path),
        "output_path": output,
        "now_ns": NOW_NS,
    }
    create_raw_soak_session(**arguments)
    original = output.read_bytes()

    with pytest.raises(FileExistsError, match="will not be overwritten"):
        create_raw_soak_session(**arguments)
    assert output.read_bytes() == original


@pytest.mark.parametrize(
    ("qualified", "commit", "now_ns", "match"),
    [
        (False, COMMIT, NOW_NS, "not qualified"),
        (True, "b" * 40, NOW_NS, "does not match"),
        (True, COMMIT, NOW_NS + 901 * 1_000_000_000, "stale"),
        (True, COMMIT, NOW_NS - 61 * 1_000_000_000, "future"),
    ],
)
def test_invalid_or_stale_preflight_is_rejected(
    tmp_path: Path, qualified: bool, commit: str, now_ns: int, match: str
) -> None:
    preflight = _preflight(
        tmp_path / "preflight.json", qualified=qualified, commit=commit
    )
    capacity = _capacity(tmp_path / "capacity.json", target_data_dir=tmp_path)
    with pytest.raises(ValueError, match=match):
        create_raw_soak_session(
            session_id="phase1-session",
            source_commit=COMMIT,
            preflight_report_path=preflight,
            capacity_forecast_report_path=capacity,
            expected_data_dir=tmp_path,
            config_paths=_configs(tmp_path),
            output_path=tmp_path / "session.json",
            now_ns=now_ns,
        )


def test_duplicate_configuration_names_are_rejected(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path / "preflight.json")
    capacity = _capacity(tmp_path / "capacity.json", target_data_dir=tmp_path)
    first = tmp_path / "one" / "config.yml"
    second = tmp_path / "two" / "config.yml"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate configuration filename"):
        create_raw_soak_session(
            session_id="phase1-session",
            source_commit=COMMIT,
            preflight_report_path=preflight,
            capacity_forecast_report_path=capacity,
            expected_data_dir=tmp_path,
            config_paths=(first, second),
            output_path=tmp_path / "session.json",
            now_ns=NOW_NS,
        )


@pytest.mark.parametrize(
    ("qualified", "commit", "target_elsewhere", "generated_ns", "match"),
    [
        (False, COMMIT, False, NOW_NS, "not qualified"),
        (True, "b" * 40, False, NOW_NS, "does not match"),
        (True, COMMIT, True, NOW_NS, "target does not match"),
        (True, COMMIT, False, NOW_NS - 901 * 1_000_000_000, "stale"),
    ],
)
def test_invalid_capacity_forecast_is_rejected(
    tmp_path: Path,
    qualified: bool,
    commit: str,
    target_elsewhere: bool,
    generated_ns: int,
    match: str,
) -> None:
    preflight = _preflight(tmp_path / "preflight.json")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    capacity = _capacity(
        tmp_path / "capacity.json",
        qualified=qualified,
        commit=commit,
        target_data_dir=elsewhere if target_elsewhere else tmp_path,
        generated_ns=generated_ns,
    )

    with pytest.raises(ValueError, match=match):
        create_raw_soak_session(
            session_id="phase1-session",
            source_commit=COMMIT,
            preflight_report_path=preflight,
            capacity_forecast_report_path=capacity,
            expected_data_dir=tmp_path,
            config_paths=_configs(tmp_path),
            output_path=tmp_path / "session.json",
            now_ns=NOW_NS,
        )
