"""Repository-level reproducibility checks."""

import tomllib
from pathlib import Path

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
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lockfile = (ROOT / "uv.lock").read_text(encoding="utf-8")
    lock_data = tomllib.loads(lockfile)

    assert dockerfile.startswith("FROM python:3.11.15-slim")
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
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "uv sync --all-extras --locked" in dockerfile
    assert "uv sync --all-extras --locked" in workflow
    assert "ARG GREENFIELD_GIT_COMMIT=unknown" in dockerfile
    assert "--build-arg GREENFIELD_GIT_COMMIT=${{ github.sha }}" in workflow
    assert 'pip install --no-cache-dir -e ".[dev,data,backtest,ml]"' not in dockerfile
    assert 'pip install -e ".[dev,data,backtest]"' not in workflow
    assert {".git", ".venv", ".env", "data", "*.parquet", "*.joblib"} <= set(
        dockerignore
    )
