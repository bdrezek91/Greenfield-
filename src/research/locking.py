"""A single-process file lock so two research-worker invocations can never
run concurrently against the same ledger/reports directory.

Uses `os.open` with `O_CREAT | O_EXCL` (atomic create-if-absent), which is
what makes this safe against a race between two processes starting at
nearly the same instant - unlike "check if the file exists, then create
it", which has a TOCTOU gap.

Staleness is detected by AGE, not by checking whether the recorded PID is
still alive. An earlier version used `os.kill(pid, 0)` - that is correct
for same-host, same-PID-namespace processes, but wrong for this project's
actual deployment model: `docker compose run` starts a brand-new container
- with its own PID namespace starting again from low numbers - for every
invocation. A PID recorded by a previous, now-dead container can coincide
with a live PID inside a completely unrelated new container (e.g. both
happen to have a process at PID 7), which made the old liveness check
falsely report an already-dead lock as "still held" (observed in practice:
a crashed `research-worker` container left a lock that a fresh
`docker compose run` could not take over). Age-based staleness has no such
cross-namespace ambiguity and is correct for both a long-running same-host
worker and ephemeral per-invocation containers alike.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from types import TracebackType

DEFAULT_LOCK_PATH = Path("reports") / "research" / "cycle.lock"

# Generous relative to configs/research_protocol.yaml's
# max_wall_clock_minutes_per_cycle (default 360 min / 6h) - long enough that
# a slow-but-alive cycle is never mistaken for stale, short enough that a
# crashed worker doesn't block the next scheduled cycle for days.
DEFAULT_STALE_AFTER_SECONDS = 8 * 3600


class CycleLockHeld(RuntimeError):
    """Raised when another process already holds the lock."""


class CycleLock:
    """Context manager: `with CycleLock(path): ...` acquires on enter,
    releases on exit (including on exception/SIGTERM propagated as one).

    A lock file older than `stale_after_seconds` is treated as abandoned
    and is taken over automatically - a crashed prior worker (in this
    container or a previous one) must not permanently block every future
    cycle.
    """

    def __init__(
        self,
        path: Path = DEFAULT_LOCK_PATH,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
    ) -> None:
        self.path = Path(path)
        self.stale_after_seconds = stale_after_seconds
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
        os.write(fd, f"pid={os.getpid()} started_at={time.time()}".encode())
        os.close(fd)
        self._fd = 1  # marker: this instance holds the lock

    def _steal_if_stale(self) -> bool:
        try:
            age_seconds = time.time() - self.path.stat().st_mtime
        except OSError:
            # Disappeared between the failed open and this check (another
            # process just released it) - safest to just retry the open.
            return True
        if age_seconds < self.stale_after_seconds:
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
