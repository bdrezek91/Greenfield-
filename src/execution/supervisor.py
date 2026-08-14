"""Run-with-restart-and-checkpoint for a long-running paper/live session
(Phase 14) - the piece scripts/paper_trade.py's single blocking `node.run()`
call was missing: a testnet disconnect (or any other transient failure)
currently kills the whole process. This wraps an arbitrary zero-argument
callable (typically `node.run`) in a bounded retry loop with exponential
backoff, checkpointing session state (src/execution/session_state.py)
before and after every attempt.

`sleep_fn`/`now_fn` are injected (default `time.sleep`/real UTC now) so
tests exercise the retry/backoff logic instantly and deterministically,
without real sleeps or wall-clock time - the same dependency-injection
pattern used throughout this project for anything otherwise untestable in
this sandbox (e.g. src/data/client.py's injectable transport).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.execution.fill_tracking import FillTrackerSummary
from src.execution.session_state import (
    SessionState,
    bump_restart,
    checkpoint,
    load_session_state,
    new_session_state,
    save_session_state,
)


@dataclass(frozen=True)
class SupervisorConfig:
    max_restarts: int = 5
    backoff_seconds: float = 30.0
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 900.0


class RestartsExhaustedError(RuntimeError):
    """Raised when `run_fn` has failed more than `max_restarts` times -
    the supervisor gives up rather than retrying forever, since an
    operator (or the next process supervisor layer up, e.g. systemd/Docker
    restart policy) needs to know this session needs attention.
    """


class PaperSessionSupervisor:
    def __init__(
        self,
        config: SupervisorConfig,
        checkpoint_path: Path,
        session_id: str,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.checkpoint_path = checkpoint_path
        self.session_id = session_id
        self._sleep_fn = sleep_fn
        self._now_fn = now_fn

    def run(
        self,
        run_fn: Callable[[], None],
        fill_summary_fn: Callable[[], FillTrackerSummary] | None = None,
    ) -> SessionState:
        """Runs `run_fn()`. On success, checkpoints and returns. On
        exception, checkpoints the failure, sleeps with exponential
        backoff, and retries - up to `config.max_restarts` times, after
        which `RestartsExhaustedError` is raised (chained to the last
        underlying exception).

        Resumes from an existing checkpoint at `checkpoint_path` if one
        exists (e.g. after a full process restart, not just a retry within
        this call) rather than starting `restart_count` back at zero.
        """
        state = load_session_state(self.checkpoint_path) or new_session_state(
            self.session_id, now=self._now_fn()
        )
        save_session_state(state, self.checkpoint_path)

        backoff = self.config.backoff_seconds
        last_exc: Exception | None = None

        while state.restart_count <= self.config.max_restarts:
            try:
                run_fn()
                summary = fill_summary_fn() if fill_summary_fn is not None else None
                state = checkpoint(state, fill_summary=summary, now=self._now_fn())
                save_session_state(state, self.checkpoint_path)
                return state
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any run_fn failure is retryable
                last_exc = exc
                state = bump_restart(state, error=repr(exc), now=self._now_fn())
                save_session_state(state, self.checkpoint_path)
                if state.restart_count > self.config.max_restarts:
                    break
                self._sleep_fn(backoff)
                backoff = min(
                    backoff * self.config.backoff_multiplier, self.config.max_backoff_seconds
                )

        raise RestartsExhaustedError(
            f"session {self.session_id!r} failed {state.restart_count} times "
            f"(max_restarts={self.config.max_restarts}); last error: {last_exc!r}"
        ) from last_exc
