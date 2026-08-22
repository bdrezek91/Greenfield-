"""Fail-closed host preflight for the seven-day Phase 1 raw-data soak."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

BYBIT_REST_TIME_URL = "https://api.bybit.com/v5/market/time"
BYBIT_STREAM_HOST = "stream.bybit.com"
BYBIT_STREAM_URL = "wss://stream.bybit.com/v5/public/linear"
DEFAULT_MINIMUM_FREE_GIB = 100.0
MAXIMUM_CLOCK_SKEW_SECS = 1.0


@dataclass(frozen=True, slots=True)
class PreflightObservations:
    platform_system: str
    python_version: str
    source_commit: str
    working_tree_clean: bool
    docker_compose_available: bool
    docker_daemon_available: bool
    compose_config_valid: bool
    data_atomic_probe_passed: bool
    data_free_bytes: int
    pending_reboot: bool
    bybit_dns_passed: bool
    bybit_tls_passed: bool
    bybit_websocket_passed: bool
    bybit_clock_skew_secs: float | None
    bybit_clock_round_trip_secs: float | None
    grafana_password_ready: bool
    monitoring_bind_address: str
    external_alert_https_ready: bool


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PhaseOnePreflightReport:
    schema_version: int
    generated_at_utc: str
    qualified: bool
    expected_commit: str
    minimum_free_bytes: int
    observations: PreflightObservations
    checks: tuple[PreflightCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def gather_preflight_observations(
    *,
    repository_root: Path,
    data_dir: Path,
    compose_files: Sequence[Path],
    timeout_secs: float = 10.0,
    environment: Mapping[str, str] | None = None,
) -> PreflightObservations:
    """Probe the target host without exposing environment values in the report."""

    if timeout_secs <= 0:
        raise ValueError("timeout_secs must be positive")
    repo = Path(repository_root).resolve()
    resolved_data_dir = Path(data_dir).resolve()
    env = _load_runtime_environment(repo, environment)

    commit = _run_output(("git", "rev-parse", "HEAD"), cwd=repo, timeout=timeout_secs)
    status = _run_output(
        ("git", "status", "--porcelain"), cwd=repo, timeout=timeout_secs
    )
    compose_available = _command_ok(
        ("docker", "compose", "version"), cwd=repo, timeout=timeout_secs, env=env
    )
    daemon_available = _command_ok(
        ("docker", "info", "--format", "{{.ServerVersion}}"),
        cwd=repo,
        timeout=timeout_secs,
        env=env,
    )
    compose_command = ["docker", "compose"]
    for path in compose_files:
        compose_command.extend(("-f", str(Path(path).resolve())))
    compose_command.extend(("--profile", "monitoring", "config", "--quiet"))
    compose_valid = compose_available and _command_ok(
        tuple(compose_command), cwd=repo, timeout=timeout_secs, env=env
    )

    atomic_probe = _atomic_storage_probe(resolved_data_dir)
    try:
        free_bytes = shutil.disk_usage(resolved_data_dir).free
    except OSError:
        free_bytes = 0

    dns_ok = _dns_probe(BYBIT_STREAM_HOST, timeout_secs=timeout_secs)
    tls_ok = dns_ok and _tls_probe(BYBIT_STREAM_HOST, timeout_secs=timeout_secs)
    websocket_ok = tls_ok and _websocket_probe(timeout_secs=timeout_secs)
    clock_skew, clock_rtt = _bybit_clock_probe(timeout_secs=timeout_secs)

    grafana_password = env.get("GRAFANA_ADMIN_PASSWORD", "")
    password_ready = (
        len(grafana_password) >= 16
        and grafana_password.lower() not in {"admin", "password", "changeme"}
    )
    bind_address = env.get("MONITORING_BIND_ADDRESS", "127.0.0.1").strip()
    forward_url = env.get("ALERT_FORWARD_URL", "").strip()
    parsed_forward = urllib.parse.urlsplit(forward_url)
    external_alert_ready = parsed_forward.scheme == "https" and bool(parsed_forward.netloc)

    return PreflightObservations(
        platform_system=platform.system(),
        python_version=platform.python_version(),
        source_commit=commit or "",
        working_tree_clean=status == "",
        docker_compose_available=compose_available,
        docker_daemon_available=daemon_available,
        compose_config_valid=compose_valid,
        data_atomic_probe_passed=atomic_probe,
        data_free_bytes=free_bytes,
        pending_reboot=Path("/var/run/reboot-required").exists(),
        bybit_dns_passed=dns_ok,
        bybit_tls_passed=tls_ok,
        bybit_websocket_passed=websocket_ok,
        bybit_clock_skew_secs=clock_skew,
        bybit_clock_round_trip_secs=clock_rtt,
        grafana_password_ready=password_ready,
        monitoring_bind_address=bind_address,
        external_alert_https_ready=external_alert_ready,
    )


def evaluate_phase1_preflight(
    observations: PreflightObservations,
    *,
    expected_commit: str,
    minimum_free_gib: float = DEFAULT_MINIMUM_FREE_GIB,
) -> PhaseOnePreflightReport:
    if minimum_free_gib <= 0:
        raise ValueError("minimum_free_gib must be positive")
    minimum_free_bytes = int(minimum_free_gib * 1024**3)
    checks: list[PreflightCheck] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append(PreflightCheck(name, bool(passed), detail))

    check(
        "linux_host",
        observations.platform_system == "Linux",
        f"platform={observations.platform_system}",
    )
    check(
        "python_3_11",
        observations.python_version.startswith("3.11."),
        f"python={observations.python_version}",
    )
    check(
        "exact_clean_commit",
        len(expected_commit) == 40
        and observations.source_commit == expected_commit
        and observations.working_tree_clean,
        (
            f"observed={observations.source_commit or '<missing>'}; "
            f"expected={expected_commit}; clean={observations.working_tree_clean}"
        ),
    )
    check(
        "docker_runtime",
        observations.docker_compose_available
        and observations.docker_daemon_available
        and observations.compose_config_valid,
        (
            f"compose={observations.docker_compose_available}; "
            f"daemon={observations.docker_daemon_available}; "
            f"config={observations.compose_config_valid}"
        ),
    )
    check(
        "atomic_data_storage",
        observations.data_atomic_probe_passed,
        "write/fsync/atomic-rename/read/delete probe on DATA_DIR",
    )
    check(
        "data_disk_capacity",
        observations.data_free_bytes >= minimum_free_bytes,
        (
            f"free_gib={observations.data_free_bytes / 1024**3:.2f}; "
            f"required_gib={minimum_free_gib:.2f}"
        ),
    )
    check(
        "host_restart_state",
        not observations.pending_reboot,
        f"pending_reboot={observations.pending_reboot}",
    )
    check(
        "bybit_public_connectivity",
        observations.bybit_dns_passed
        and observations.bybit_tls_passed
        and observations.bybit_websocket_passed,
        (
            f"dns={observations.bybit_dns_passed}; tls={observations.bybit_tls_passed}; "
            f"websocket={observations.bybit_websocket_passed}"
        ),
    )
    skew = observations.bybit_clock_skew_secs
    check(
        "clock_synchronization",
        skew is not None and skew <= MAXIMUM_CLOCK_SKEW_SECS,
        (
            f"absolute_skew_secs={skew}; "
            f"round_trip_secs={observations.bybit_clock_round_trip_secs}; "
            f"maximum={MAXIMUM_CLOCK_SKEW_SECS}"
        ),
    )
    check(
        "grafana_secret",
        observations.grafana_password_ready,
        "GRAFANA_ADMIN_PASSWORD must be non-default and at least 16 characters",
    )
    check(
        "loopback_monitoring_bind",
        observations.monitoring_bind_address in {"127.0.0.1", "::1", "localhost"},
        f"bind_address={observations.monitoring_bind_address or '<missing>'}",
    )
    check(
        "external_alert_https",
        observations.external_alert_https_ready,
        "ALERT_FORWARD_URL must be a configured absolute HTTPS endpoint",
    )
    return PhaseOnePreflightReport(
        schema_version=1,
        generated_at_utc=datetime.now(UTC).isoformat(),
        qualified=all(item.passed for item in checks),
        expected_commit=expected_commit,
        minimum_free_bytes=minimum_free_bytes,
        observations=observations,
        checks=tuple(checks),
    )


def write_preflight_report(path: Path, report: PhaseOnePreflightReport) -> None:
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _run_output(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=None if env is None else dict(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _load_runtime_environment(
    repository_root: Path, explicit: Mapping[str, str] | None
) -> dict[str, str]:
    if explicit is not None:
        return dict(explicit)
    values = {
        str(key): value
        for key, value in dotenv_values(repository_root / ".env").items()
        if value is not None
    }
    # Exported variables intentionally override the local .env file, matching
    # Docker Compose interpolation and ordinary process semantics.
    values.update(os.environ)
    return values


def _command_ok(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
) -> bool:
    return _run_output(command, cwd=cwd, timeout=timeout, env=env) is not None


def _atomic_storage_probe(data_dir: Path) -> bool:
    probe_dir = data_dir / ".preflight"
    identity = uuid.uuid4().hex
    temp_path = probe_dir / f".{identity}.tmp"
    final_path = probe_dir / f"{identity}.probe"
    payload = identity.encode()
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        with temp_path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, final_path)
        return final_path.read_bytes() == payload
    except OSError:
        return False
    finally:
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        try:
            probe_dir.rmdir()
        except OSError:
            pass


def _dns_probe(host: str, *, timeout_secs: float) -> bool:
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_secs)
    try:
        return bool(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
    except OSError:
        return False
    finally:
        socket.setdefaulttimeout(previous)


def _tls_probe(host: str, *, timeout_secs: float) -> bool:
    try:
        with socket.create_connection((host, 443), timeout=timeout_secs) as raw_socket:
            with ssl.create_default_context().wrap_socket(
                raw_socket, server_hostname=host
            ) as tls_socket:
                return bool(tls_socket.getpeercert())
    except (OSError, ssl.SSLError):
        return False


def _websocket_probe(*, timeout_secs: float) -> bool:
    try:
        import websocket
    except ImportError:
        return False
    try:
        connection = websocket.create_connection(BYBIT_STREAM_URL, timeout=timeout_secs)
    except (OSError, websocket.WebSocketException):
        return False
    try:
        return bool(connection.connected)
    finally:
        connection.close()


def _bybit_clock_probe(*, timeout_secs: float) -> tuple[float | None, float | None]:
    before_ns = time.time_ns()
    request = urllib.request.Request(
        BYBIT_REST_TIME_URL, headers={"User-Agent": "greenfield-preflight/1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_secs) as response:
            payload = json.loads(response.read())
        after_ns = time.time_ns()
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            return None, None
        server_ns = int(result["timeNano"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None, None
    midpoint_ns = (before_ns + after_ns) // 2
    return (
        abs(server_ns - midpoint_ns) / 1_000_000_000,
        (after_ns - before_ns) / 1_000_000_000,
    )
