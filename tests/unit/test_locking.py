from __future__ import annotations

import os
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


def test_stale_lock_from_dead_pid_is_stolen(tmp_path: Path) -> None:
    path = tmp_path / "cycle.lock"
    path.write_text("999999999")  # extremely unlikely to be a live PID
    lock = CycleLock(path)
    lock.acquire()  # must not raise - stale lock is taken over
    assert int(path.read_text()) == os.getpid()
    lock.release()


def test_lock_held_by_live_process_is_not_stolen(tmp_path: Path) -> None:
    path = tmp_path / "cycle.lock"
    path.write_text(str(os.getpid()))  # this test process is definitely alive
    lock = CycleLock(path)
    with pytest.raises(CycleLockHeld):
        lock.acquire()


def test_graceful_shutdown_sets_flag_on_sigterm() -> None:
    with GracefulShutdown() as shutdown:
        assert shutdown.requested is False
        os.kill(os.getpid(), 15)  # SIGTERM
        assert shutdown.requested is True
