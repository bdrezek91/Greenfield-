"""Static, no-reboot proof that docker.service will not start before the raw
data volume is mounted.

Real incident (2026-08-27): after a VPS reboot, docker.service (and its
`restart: unless-stopped` raw collector containers) started before
/opt/greenfield-v2/data was mounted. The volume's fstab entry uses `nofail`,
which lets it mount asynchronously without blocking local-fs.target /
sysinit.target, so docker.service's implicit ordering via those targets was
not sufficient. The collectors' fail-closed start gate
(`src/data/raw_collector_start_gate.py`) correctly refused to start each
time ("No such file or directory: /app/data/health"), but Docker's restart
policy retried immediately without waiting for the mount - adding a failed-
restart-loop delay on top of the reboot's own unavoidable downtime, and
contributing part of the 514.8s raw-data gap that disqualified soak session
phase1-20260825t164933z.

Fix: a systemd drop-in at
/etc/systemd/system/docker.service.d/10-wait-for-greenfield-data-mount.conf
adding `RequiresMountsFor=<data-dir>` to docker.service - the purpose-built
systemd directive for exactly this, which resolves the correct mount unit
and adds both After= and Requires= automatically, including for `nofail`
mounts.

This script proves the fix statically (via `systemd-analyze verify` and
`systemctl show`), without forcing an actual VPS reboot - deliberately, per
standing instructions to ask before any full VPS reboot. It does not (and
cannot) prove the reboot itself becomes gap-free - the collector is still
down for the reboot's real duration regardless - only that Docker will wait
for the mount instead of retry-looping ahead of it.
"""

from __future__ import annotations

import subprocess
from typing import Annotated

import typer

app = typer.Typer(add_completion=False)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)


def _mount_unit_name(mount_path: str) -> str:
    result = _run("systemd-escape", "-p", "--suffix=mount", mount_path)
    if result.returncode != 0:
        raise RuntimeError(f"systemd-escape failed: {result.stderr.strip()}")
    return result.stdout.strip()


def evaluate_mount_ordering(
    *,
    mount_unit: str,
    show_stdout: str,
    show_returncode: int,
    analyze_verify_returncode: int,
    list_dependencies_stdout: str,
) -> dict[str, bool]:
    """Pure comparison logic, isolated from live subprocess calls for testing.

    `systemctl show` C-style-quotes unit names containing escapes (e.g. a
    backslash doubled to `\\\\x2d`), while `systemd-escape` emits a single
    backslash - strip all backslashes on both sides before comparing so this
    doesn't depend on matching that quoting exactly.
    """
    after_line = next(
        (line for line in show_stdout.splitlines() if line.startswith("After=")), ""
    )
    requires_line = next(
        (line for line in show_stdout.splitlines() if line.startswith("Requires=")), ""
    )
    normalized_mount_unit = mount_unit.replace("\\", "")
    return {
        "mount_unit_resolved": bool(mount_unit),
        "systemctl_show_succeeded": show_returncode == 0,
        "mount_unit_in_after": normalized_mount_unit in after_line.replace("\\", ""),
        "mount_unit_in_requires": normalized_mount_unit in requires_line.replace("\\", ""),
        "systemd_analyze_verify_clean": analyze_verify_returncode == 0,
        "mount_unit_in_dependency_graph": normalized_mount_unit
        in list_dependencies_stdout.replace("\\", ""),
    }


@app.command()
def verify(
    mount_path: Annotated[
        str, typer.Option(help="Raw data volume mount point.")
    ] = "/opt/greenfield-v2/data",
    unit: Annotated[
        str, typer.Option(help="Unit that must wait for the mount.")
    ] = "docker.service",
) -> None:
    mount_unit = _mount_unit_name(mount_path)
    show = _run("systemctl", "show", unit, "--property=After,Requires")
    verify_result = _run("systemd-analyze", "verify", unit)
    deps = _run("systemctl", "list-dependencies", unit)

    checks = evaluate_mount_ordering(
        mount_unit=mount_unit,
        show_stdout=show.stdout,
        show_returncode=show.returncode,
        analyze_verify_returncode=verify_result.returncode,
        list_dependencies_stdout=deps.stdout,
    )

    qualified = all(checks.values())
    typer.echo(f"mount_unit: {mount_unit}")
    for name, passed in checks.items():
        typer.echo(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    typer.echo(f"qualified: {qualified}")
    if not qualified:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
