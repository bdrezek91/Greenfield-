from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest

from src.research.locking import CycleLock, CycleLockHeld, GracefulShutdown


def test_lock_acquire_and_release(tmp_path: Path) -> None:
    lock = CycleLock(tmp_path / "cycle.lock")
    lock.acquire()
    assert lock.path.exists()
    lock.release()
    assert not lock.path.exists()


def test_second_acquire_blocked_while_first_held(tmp_path: Path) -> None:
    path = tmp_path / "cycle.lock"
    first = CycleLock(path)
    first.acquire()
    second = CycleLock(path)
    with pytest.raises(CycleLockHeld):
        second.acquire()
    first.release()


def test_context_manager_releases_on_exception(tmp_path: Path) -> None:
    path = tmp_path / "cycle.lock"
    with pytest.raises(ValueError):
        with CycleLock(path):
            raise ValueError("boom")
    assert not path.exists()


def test_old_lock_is_stolen(tmp_path: Path) -> None:
    """A lock older than `stale_after_seconds` is treated as abandoned -
    regardless of whether its recorded PID happens to be "alive" in this
    process's PID namespace (see module docstring: PID liveness is
    meaningless across separate `docker compose run` containers)."""
    path = tmp_path / "cycle.lock"
    path.write_text(f"pid={os.getpid()} started_at=0")
    old_time = time.time() - 100
    os.utime(path, (old_time, old_time))

    lock = CycleLock(path, stale_after_seconds=10)
    lock.acquire()  # must not raise - stale lock is taken over
    lock.release()


def test_fresh_lock_is_not_stolen_even_if_recorded_pid_looks_alive(tmp_path: Path) -> None:
    path = tmp_path / "cycle.lock"
    path.write_text(f"pid={os.getpid()} started_at={time.time()}")  # this process IS alive
    lock = CycleLock(path, stale_after_seconds=3600)
    with pytest.raises(CycleLockHeld):
        lock.acquire()


def test_fresh_lock_from_a_different_pid_namespace_is_still_not_stolen(tmp_path: Path) -> None:
    """The scenario that broke the old PID-liveness check: a lock recorded
    by some PID that happens to also exist in THIS process's namespace
    (e.g. PID 1, extremely common as a container's main process) must still
    be respected while fresh - age is the only signal that matters."""
    path = tmp_path / "cycle.lock"
    path.write_text("pid=1 started_at=" + str(time.time()))
    lock = CycleLock(path, stale_after_seconds=3600)
    with pytest.raises(CycleLockHeld):
        lock.acquire()


def test_graceful_shutdown_sets_flag_on_sigterm() -> None:
    with GracefulShutdown() as shutdown:
        assert shutdown.requested is False
        # ``os.kill(pid, 15)`` terminates the interpreter directly on
        # Windows instead of dispatching Python's installed handler.
        signal.raise_signal(signal.SIGTERM)
        assert shutdown.requested is True
