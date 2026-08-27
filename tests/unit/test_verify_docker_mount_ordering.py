"""scripts/verify_docker_mount_ordering.py: the mount-unit comparison must
handle systemctl show's C-style double-backslash quoting of escaped unit
names (e.g. `opt-greenfield\\x2dv2-data.mount`), not just the plain single-
backslash form systemd-escape itself emits.
"""

from __future__ import annotations

from scripts.verify_docker_mount_ordering import evaluate_mount_ordering

_MOUNT_UNIT = r"opt-greenfield\x2dv2-data.mount"


def _real_systemctl_show_stdout() -> str:
    # Reproduces systemctl show's actual double-backslash quoting of a unit
    # name that itself contains a systemd-escape backslash.
    return (
        r'Requires=system.slice sysinit.target docker.socket '
        r'"opt-greenfield\\x2dv2-data.mount" -.mount' "\n"
        r'After=nss-lookup.target "opt-greenfield\\x2dv2-data.mount" '
        r'-.mount systemd-journald.socket basic.target' "\n"
    )


def test_all_checks_pass_against_real_captured_systemctl_output() -> None:
    checks = evaluate_mount_ordering(
        mount_unit=_MOUNT_UNIT,
        show_stdout=_real_systemctl_show_stdout(),
        show_returncode=0,
        analyze_verify_returncode=0,
        list_dependencies_stdout="docker.service\n\xe2\x97\x8f opt-greenfield\\x2dv2-data.mount\n",
    )
    assert all(checks.values()), checks


def test_missing_mount_from_after_fails_that_check_only() -> None:
    checks = evaluate_mount_ordering(
        mount_unit=_MOUNT_UNIT,
        show_stdout='Requires="opt-greenfield\\\\x2dv2-data.mount"\nAfter=basic.target\n',
        show_returncode=0,
        analyze_verify_returncode=0,
        list_dependencies_stdout="opt-greenfield\\x2dv2-data.mount\n",
    )
    assert checks["mount_unit_in_requires"] is True
    assert checks["mount_unit_in_after"] is False


def test_nonzero_returncodes_fail_their_own_checks() -> None:
    checks = evaluate_mount_ordering(
        mount_unit=_MOUNT_UNIT,
        show_stdout="",
        show_returncode=1,
        analyze_verify_returncode=1,
        list_dependencies_stdout="",
    )
    assert checks["systemctl_show_succeeded"] is False
    assert checks["systemd_analyze_verify_clean"] is False
    assert checks["mount_unit_in_after"] is False
    assert checks["mount_unit_in_requires"] is False
    assert checks["mount_unit_in_dependency_graph"] is False


def test_empty_mount_unit_fails_resolution_check() -> None:
    checks = evaluate_mount_ordering(
        mount_unit="",
        show_stdout="After=basic.target\nRequires=basic.target\n",
        show_returncode=0,
        analyze_verify_returncode=0,
        list_dependencies_stdout="",
    )
    assert checks["mount_unit_resolved"] is False
