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


def _venue_preflight(
    path: Path,
    *,
    venue: str = "okx",
    qualified: bool = True,
    passed: bool = True,
    commit: str = COMMIT,
    generated_ns: int = NOW_NS,
) -> Path:
    generated = datetime.fromtimestamp(generated_ns / 1_000_000_000, tz=UTC).isoformat()
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": generated,
                "qualified": qualified,
                "expected_commit": commit,
                "observed_commit": commit,
                "working_tree_clean": True,
                "venues": [{"venue": venue, "passed": passed}],
            }
        ),
        encoding="utf-8",
    )
    return path


def _capacity(
    path: Path,
    *,
    qualified: bool = True,
    commit: str = COMMIT,
    target_data_dir: Path | None = None,
    generated_ns: int = NOW_NS,
    venue: str | None = None,
    health_namespace: str | None = None,
) -> Path:
    generated = datetime.fromtimestamp(generated_ns / 1_000_000_000, tz=UTC).isoformat()
    value = {
        "schema_version": 2 if venue is not None else 1,
        "generated_at_utc": generated,
        "source_commit": commit,
        "target_data_dir": str((target_data_dir or path.parent).resolve()),
        "qualified": qualified,
        "required_capacity_bytes": 1,
        "available_capacity_bytes": 2,
        "checks": {"lossless": qualified, "fits": qualified},
    }
    if venue is not None:
        value["venue"] = venue
        value["health_namespace"] = health_namespace
        value["smoke_report_sha256"] = "e" * 64
    path.write_text(
        json.dumps(value),
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


def test_phase3_session_binds_exact_venue_contract_and_preflight(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path / "preflight.json")
    venue_preflight = _venue_preflight(tmp_path / "venue-preflight.json")
    capacity = _capacity(
        tmp_path / "capacity.json",
        target_data_dir=tmp_path,
        venue="okx",
        health_namespace="okx-swap",
    )
    output = tmp_path / "sessions" / "okx-20270115.json"

    session = create_raw_soak_session(
        session_id="okx-20270115",
        source_commit=COMMIT,
        preflight_report_path=preflight,
        capacity_forecast_report_path=capacity,
        expected_data_dir=tmp_path,
        config_paths=_configs(tmp_path),
        output_path=output,
        collector_ids=("btc-usdt-swap", "eth-usdt-swap", "sol-usdt-swap"),
        health_namespace="okx-swap",
        venue="okx",
        venue_preflight_report_path=venue_preflight,
        now_ns=NOW_NS,
    )

    assert session.schema_version == 3
    assert session.venue == "okx"
    assert session.health_namespace == "okx-swap"
    assert session.venue_preflight_report_sha256 == file_sha256(venue_preflight)
    assert load_raw_soak_session(output) == session


@pytest.mark.parametrize(
    ("qualified", "passed", "commit", "generated_ns", "match"),
    [
        (False, True, COMMIT, NOW_NS, "not qualified"),
        (True, False, COMMIT, NOW_NS, "did not qualify"),
        (True, True, "b" * 40, NOW_NS, "clean source commit"),
        (True, True, COMMIT, NOW_NS - 901 * 1_000_000_000, "stale"),
    ],
)
def test_phase3_session_rejects_invalid_venue_preflight(
    tmp_path: Path,
    qualified: bool,
    passed: bool,
    commit: str,
    generated_ns: int,
    match: str,
) -> None:
    preflight = _preflight(tmp_path / "preflight.json")
    venue_preflight = _venue_preflight(
        tmp_path / "venue-preflight.json",
        qualified=qualified,
        passed=passed,
        commit=commit,
        generated_ns=generated_ns,
    )
    capacity = _capacity(
        tmp_path / "capacity.json",
        target_data_dir=tmp_path,
        venue="okx",
        health_namespace="okx-swap",
    )

    with pytest.raises(ValueError, match=match):
        create_raw_soak_session(
            session_id="okx-session",
            source_commit=COMMIT,
            preflight_report_path=preflight,
            capacity_forecast_report_path=capacity,
            expected_data_dir=tmp_path,
            config_paths=_configs(tmp_path),
            output_path=tmp_path / "session.json",
            collector_ids=("btc-usdt-swap", "eth-usdt-swap", "sol-usdt-swap"),
            health_namespace="okx-swap",
            venue="okx",
            venue_preflight_report_path=venue_preflight,
            now_ns=NOW_NS,
        )


@pytest.mark.parametrize(
    ("collector_ids", "health_namespace", "match"),
    [
        (("btcusdt",), "okx-swap", "collector_ids"),
        (
            ("btc-usdt-swap", "eth-usdt-swap", "sol-usdt-swap"),
            "bybit-linear",
            "health_namespace",
        ),
    ],
)
def test_phase3_session_rejects_identity_outside_venue_contract(
    tmp_path: Path,
    collector_ids: tuple[str, ...],
    health_namespace: str,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        create_raw_soak_session(
            session_id="okx-session",
            source_commit=COMMIT,
            preflight_report_path=_preflight(tmp_path / "preflight.json"),
            capacity_forecast_report_path=_capacity(
                tmp_path / "capacity.json",
                target_data_dir=tmp_path,
                venue="okx",
                health_namespace="okx-swap",
            ),
            expected_data_dir=tmp_path,
            config_paths=_configs(tmp_path),
            output_path=tmp_path / "session.json",
            collector_ids=collector_ids,
            health_namespace=health_namespace,
            venue="okx",
            venue_preflight_report_path=_venue_preflight(tmp_path / "venue-preflight.json"),
            now_ns=NOW_NS,
        )


def test_phase3_session_rejects_capacity_from_another_venue(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="capacity forecast does not match"):
        create_raw_soak_session(
            session_id="okx-session",
            source_commit=COMMIT,
            preflight_report_path=_preflight(tmp_path / "preflight.json"),
            capacity_forecast_report_path=_capacity(
                tmp_path / "capacity.json",
                target_data_dir=tmp_path,
                venue="binance",
                health_namespace="binance-linear",
            ),
            expected_data_dir=tmp_path,
            config_paths=_configs(tmp_path),
            output_path=tmp_path / "session.json",
            collector_ids=("btc-usdt-swap", "eth-usdt-swap", "sol-usdt-swap"),
            health_namespace="okx-swap",
            venue="okx",
            venue_preflight_report_path=_venue_preflight(tmp_path / "venue-preflight.json"),
            now_ns=NOW_NS,
        )


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
    preflight = _preflight(tmp_path / "preflight.json", qualified=qualified, commit=commit)
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
