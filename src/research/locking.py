"""A single-process file lock so two research-worker invocations can never
run concurrently against the same ledger/reports directory.

Uses `os.open` with `O_CREAT | O_EXCL` (atomic create-if-absent), which is
what makes this safe against a race between two processes starting at
nearly the same instant - unlike "check if the file exists, then create
it", which has a TOCTOU gap.
"""

from __future__ import annotations

import errno
import os
import signal
from pathlib import Path
from types import TracebackType

DEFAULT_LOCK_PATH = Path("reports") / "research" / "cycle.lock"


class CycleLockHeld(RuntimeError):
    """Raised when another process already holds the lock."""


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


class CycleLock:
    """Context manager: `with CycleLock(path): ...` acquires on enter,
    releases on exit (including on exception/SIGTERM propagated as one).

    A lock file whose recorded PID is no longer alive is treated as stale
    and is taken over automatically - a crashed prior worker must not
    permanently block every future cycle.
    """

    def __init__(self, path: Path = DEFAULT_LOCK_PATH) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if self._steal_if_stale():
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            else:
                raise CycleLockHeld(
                    f"another research cycle already holds the lock at {self.path}"
                ) from None
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        self._fd = 1  # marker: this instance holds the lock

    def _steal_if_stale(self) -> bool:
        try:
            held_pid = int(self.path.read_text().strip())
        except (ValueError, OSError):
            # Unreadable/corrupt lock file - safer to leave it alone than guess.
            return False
        if _pid_is_alive(held_pid):
            return False
        self.path.unlink(missing_ok=True)
        return True

    def release(self) -> None:
        if self._fd is not None:
            self.path.unlink(missing_ok=True)
            self._fd = None

    def __enter__(self) -> CycleLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class GracefulShutdown:
    """Registers a SIGTERM/SIGINT handler that sets `.requested` instead of
    killing the process immediately, so a long-running cycle/daemon can
    finish its current unit of work, release the lock, and exit cleanly.
    """

    def __init__(self) -> None:
        self.requested = False
        self._previous_term: object = None
        self._previous_int: object = None

    def _handle(self, signum: int, frame: object) -> None:
        self.requested = True

    def __enter__(self) -> GracefulShutdown:
        self._previous_term = signal.signal(signal.SIGTERM, self._handle)
        self._previous_int = signal.signal(signal.SIGINT, self._handle)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        signal.signal(signal.SIGTERM, self._previous_term)  # type: ignore[arg-type]
        signal.signal(signal.SIGINT, self._previous_int)  # type: ignore[arg-type]
