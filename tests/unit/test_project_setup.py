"""Smoke test proving the package layout and test runner are wired up correctly."""

import src


def test_src_package_importable() -> None:
    assert src is not None
