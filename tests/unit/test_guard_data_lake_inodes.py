from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.guard_data_lake_inodes import enforce_inode_reserve


def test_healthy_reserve_does_not_touch_docker(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def run(command: list[str]) -> CompletedProcess[str]:
        commands.append(command)
        return CompletedProcess(command, 0, stdout="", stderr="")

    report = enforce_inode_reserve(
        tmp_path,
        100_000,
        ("btc",),
        inode_probe=lambda _: 100_001,
        run=run,
    )

    assert report["status"] == "HEALTHY"
    assert report["stopped_containers"] == []
    assert commands == []


def test_breach_stops_only_running_named_containers(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def run(command: list[str]) -> CompletedProcess[str]:
        commands.append(command)
        if command[:2] == ["docker", "inspect"]:
            running = command[-1] == "btc"
            return CompletedProcess(command, 0, stdout=f"{str(running).lower()}\n", stderr="")
        return CompletedProcess(command, 0, stdout="", stderr="")

    report = enforce_inode_reserve(
        tmp_path,
        100_000,
        ("btc", "eth"),
        inode_probe=lambda _: 100_000,
        run=run,
    )

    assert report["status"] == "STOPPED_BEFORE_ENOSPC"
    assert report["stopped_containers"] == ["btc"]
    assert ["docker", "stop", "--time", "30", "btc"] in commands
    assert ["docker", "stop", "--time", "30", "eth"] not in commands


def test_invalid_reserve_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        enforce_inode_reserve(tmp_path, 0, (), inode_probe=lambda _: 1)
