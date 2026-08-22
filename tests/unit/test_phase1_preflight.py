"""The Phase 1 VPS preflight fails closed before a seven-day clock starts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.data.phase1_preflight import (
    PreflightObservations,
    _atomic_storage_probe,
    _load_runtime_environment,
    evaluate_phase1_preflight,
    write_preflight_report,
)

COMMIT = "a" * 40


def _valid_observations() -> PreflightObservations:
    return PreflightObservations(
        platform_system="Linux",
        python_version="3.11.15",
        source_commit=COMMIT,
        working_tree_clean=True,
        docker_compose_available=True,
        docker_daemon_available=True,
        compose_config_valid=True,
        data_atomic_probe_passed=True,
        data_free_bytes=200 * 1024**3,
        pending_reboot=False,
        bybit_dns_passed=True,
        bybit_tls_passed=True,
        bybit_websocket_passed=True,
        bybit_clock_skew_secs=0.05,
        bybit_clock_round_trip_secs=0.1,
        grafana_password_ready=True,
        monitoring_bind_address="127.0.0.1",
        external_alert_https_ready=True,
    )


def test_valid_vps_observations_qualify_and_report_is_atomic(tmp_path: Path) -> None:
    report = evaluate_phase1_preflight(_valid_observations(), expected_commit=COMMIT)
    assert report.qualified
    assert all(check.passed for check in report.checks)
    output = tmp_path / "preflight.json"
    write_preflight_report(output, report)
    assert '"qualified": true' in output.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))


def test_wrong_commit_public_bind_no_alert_and_low_disk_fail() -> None:
    observations = replace(
        _valid_observations(),
        source_commit="b" * 40,
        data_free_bytes=5 * 1024**3,
        monitoring_bind_address="0.0.0.0",
        external_alert_https_ready=False,
    )
    report = evaluate_phase1_preflight(observations, expected_commit=COMMIT)
    failed = {check.name for check in report.checks if not check.passed}
    assert not report.qualified
    assert {
        "exact_clean_commit",
        "data_disk_capacity",
        "loopback_monitoring_bind",
        "external_alert_https",
    } <= failed


def test_clock_network_runtime_and_secret_fail_closed() -> None:
    observations = replace(
        _valid_observations(),
        docker_daemon_available=False,
        bybit_websocket_passed=False,
        bybit_clock_skew_secs=None,
        grafana_password_ready=False,
    )
    report = evaluate_phase1_preflight(observations, expected_commit=COMMIT)
    failed = {check.name for check in report.checks if not check.passed}
    assert {
        "docker_runtime",
        "bybit_public_connectivity",
        "clock_synchronization",
        "grafana_secret",
    } <= failed


def test_pending_host_reboot_blocks_soak_start() -> None:
    observations = replace(_valid_observations(), pending_reboot=True)

    report = evaluate_phase1_preflight(observations, expected_commit=COMMIT)

    assert not report.qualified
    assert not next(
        check for check in report.checks if check.name == "host_restart_state"
    ).passed


def test_atomic_storage_probe_cleans_up(tmp_path: Path) -> None:
    assert _atomic_storage_probe(tmp_path)
    assert not (tmp_path / ".preflight").exists()


def test_nonpositive_disk_threshold_is_invalid() -> None:
    try:
        evaluate_phase1_preflight(
            _valid_observations(), expected_commit=COMMIT, minimum_free_gib=0
        )
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_preflight_reads_dotenv_but_exported_values_win(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "GRAFANA_ADMIN_PASSWORD=from-file-password\n"  # pragma: allowlist secret
        "ALERT_FORWARD_URL=https://file.example/alerts\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GRAFANA_ADMIN_PASSWORD", "exported-password")

    environment = _load_runtime_environment(tmp_path, None)

    assert environment["GRAFANA_ADMIN_PASSWORD"] == "exported-password"  # pragma: allowlist secret
    assert environment["ALERT_FORWARD_URL"] == "https://file.example/alerts"
