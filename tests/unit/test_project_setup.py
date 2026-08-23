"""Repository-level reproducibility checks."""

import tomllib
from pathlib import Path

import yaml

import src

ROOT = Path(__file__).resolve().parents[2]


def test_src_package_importable() -> None:
    assert src is not None


def test_supported_runtime_and_engine_are_pinned_consistently() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["requires-python"] == ">=3.11,<3.12"
    assert pyproject["project"]["optional-dependencies"]["backtest"] == [
        "nautilus_trader==1.221.0"
    ]

    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    collector_dockerfile = (ROOT / "docker" / "Dockerfile.collector").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lockfile = (ROOT / "uv.lock").read_text(encoding="utf-8")
    lock_data = tomllib.loads(lockfile)

    assert dockerfile.startswith("FROM python:3.11.15-slim")
    assert collector_dockerfile.startswith("FROM python:3.11.15-slim")
    assert 'python-version: "3.11.15"' in workflow
    assert lock_data["requires-python"] == "==3.11.*"
    nautilus_versions = [
        package["version"]
        for package in lock_data["package"]
        if package["name"] == "nautilus-trader"
    ]
    assert nautilus_versions == ["1.221.0"]


def test_ci_and_docker_install_from_the_lockfile() -> None:
    dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    collector_dockerfile = (ROOT / "docker" / "Dockerfile.collector").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv sync --all-extras --locked" in dockerfile
    assert "uv sync --all-extras --locked" in workflow
    assert "uv sync --extra data --locked" in collector_dockerfile
    assert "--all-extras" not in collector_dockerfile
    assert "build-essential" not in collector_dockerfile
    assert "docker/Dockerfile.collector" in workflow
    assert "ARG GREENFIELD_GIT_COMMIT=unknown" in dockerfile
    assert "--build-arg GREENFIELD_GIT_COMMIT=${{ github.sha }}" in workflow
    assert 'pip install --no-cache-dir -e ".[dev,data,backtest,ml]"' not in dockerfile
    assert 'pip install -e ".[dev,data,backtest]"' not in workflow
    assert {".git", ".venv", ".env", "data", "*.parquet", "*.joblib"} <= set(
        dockerignore
    )


def test_phase1_collectors_use_minimal_image_and_exact_host_data_dir() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for service_name in ("raw-bybit-btc", "raw-bybit-eth", "raw-bybit-sol"):
        service = compose["services"][service_name]
        assert service["build"]["dockerfile"] == "docker/Dockerfile.collector"
        assert service["image"] == "greenfield-phase1:collector"
        assert "${DATA_DIR:-./data}:/app/data" in service["volumes"]
        assert "ai-trading-lab-data:/app/data" not in service["volumes"]


def test_shadow_service_data_volume_shares_no_mount_source_with_active_bybit_soak() -> None:
    """Cycle 6 remediation: a previous revision of docker-compose.yml
    *claimed* shadow-service shared no volume path with raw-bybit-*, while
    both actually bound the identical ${DATA_DIR:-./data} host directory
    into /app/data - meaning either container could read/write the other's
    queue/work/audit/risk or raw market data. shadow-service must use its
    own Docker-managed named volume instead, and raw-bybit-*'s mounts (the
    active soak) must be completely untouched.
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    shadow = services["shadow-service"]

    assert shadow["profiles"] == ["shadow"]  # still disabled by default
    assert "shadow-service-data:/app/data" in shadow["volumes"]
    assert "${DATA_DIR:-./data}:/app/data" not in shadow["volumes"]
    assert "ai-trading-lab-data:/app/data" not in shadow["volumes"]
    assert "shadow-service-data" in compose["volumes"]

    def _source(mount: str) -> str:
        return mount.split(":", 1)[0]

    shadow_sources = {_source(mount) for mount in shadow["volumes"]}
    for bybit_service in ("raw-bybit-btc", "raw-bybit-eth", "raw-bybit-sol"):
        bybit_service_def = services[bybit_service]
        assert bybit_service_def["volumes"] == [".:/app", "${DATA_DIR:-./data}:/app/data"], (
            f"{bybit_service} volumes changed - this cycle must not touch the active Bybit soak"
        )
        bybit_sources = {_source(mount) for mount in bybit_service_def["volumes"]}
        # "." (the repo source bind) is legitimately shared by every
        # service; the data-root mount source must not be.
        shared = (shadow_sources & bybit_sources) - {"."}
        assert not shared, f"shadow-service and {bybit_service} share data mount source {shared}"
