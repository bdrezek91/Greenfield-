"""Stop named collectors before the data lake exhausts its inodes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def available_inodes(path: Path) -> int:
    statvfs = getattr(os, "statvfs", None)
    if statvfs is None:
        raise RuntimeError("inode accounting is unavailable on this platform")
    return int(statvfs(path).f_favail)


def stop_running_containers(
    containers: tuple[str, ...],
    *,
    run: CommandRunner = _run_command,
) -> list[str]:
    stopped: list[str] = []
    for container in containers:
        state = run(["docker", "inspect", "--format", "{{.State.Running}}", container])
        if state.stdout.strip() != "true":
            continue
        run(["docker", "stop", "--time", "30", container])
        stopped.append(container)
    return stopped


def enforce_inode_reserve(
    data_dir: Path,
    minimum_free_inodes: int,
    containers: tuple[str, ...],
    *,
    inode_probe: Callable[[Path], int] = available_inodes,
    run: CommandRunner = _run_command,
) -> dict[str, object]:
    if minimum_free_inodes <= 0:
        raise ValueError("minimum_free_inodes must be positive")
    resolved = data_dir.resolve(strict=True)
    free = int(inode_probe(resolved))
    breached = free <= minimum_free_inodes
    stopped = stop_running_containers(containers, run=run) if breached else []
    return {
        "status": "STOPPED_BEFORE_ENOSPC" if breached else "HEALTHY",
        "data_dir": str(resolved),
        "available_inodes": free,
        "minimum_free_inodes": minimum_free_inodes,
        "stopped_containers": stopped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--minimum-free-inodes", type=int, default=100_000)
    parser.add_argument("--container", action="append", default=[])
    args = parser.parse_args()
    report = enforce_inode_reserve(
        args.data_dir,
        args.minimum_free_inodes,
        tuple(args.container),
    )
    print(json.dumps(report, sort_keys=True))
    return 2 if report["status"] == "STOPPED_BEFORE_ENOSPC" else 0


if __name__ == "__main__":
    raise SystemExit(main())
