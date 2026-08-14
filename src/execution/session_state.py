"""Durable checkpoint for a long-running paper/live trading session (Phase
14). A session that runs for days/weeks needs to survive process
restarts (a crash, a deploy, a supervised restart after a disconnect -
src/execution/supervisor.py) without losing track of how many times it's
restarted or what its fill-quality numbers looked like going in.

This is NOT trade/position state (NautilusTrader's own cache/database
persistence handles that - see docs/VPS_DEPLOYMENT.md) - it's operational
metadata about the SESSION itself, checkpointed as plain JSON so it's
trivial to inspect by hand during an incident.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.execution.fill_tracking import FillTrackerSummary


@dataclass
class SessionState:
    session_id: str
    started_at: str
    last_checkpoint_at: str
    restart_count: int
    last_error: str | None
    fill_summary: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> SessionState:
        return SessionState(**data)


def new_session_state(session_id: str, now: datetime | None = None) -> SessionState:
    ts = (now or datetime.now(UTC)).isoformat()
    return SessionState(
        session_id=session_id,
        started_at=ts,
        last_checkpoint_at=ts,
        restart_count=0,
        last_error=None,
        fill_summary=None,
    )


def checkpoint(
    state: SessionState,
    *,
    fill_summary: FillTrackerSummary | None = None,
    last_error: str | None = None,
    now: datetime | None = None,
) -> SessionState:
    """Return a new SessionState with `last_checkpoint_at` refreshed and
    the given fields updated - state objects are treated as immutable
    snapshots so a caller can't accidentally checkpoint a half-updated one.
    """
    return SessionState(
        session_id=state.session_id,
        started_at=state.started_at,
        last_checkpoint_at=(now or datetime.now(UTC)).isoformat(),
        restart_count=state.restart_count,
        last_error=last_error if last_error is not None else state.last_error,
        fill_summary=(asdict(fill_summary) if fill_summary is not None else state.fill_summary),
    )


def bump_restart(state: SessionState, *, error: str, now: datetime | None = None) -> SessionState:
    """A crash-and-retry, distinct from a normal checkpoint(): increments
    `restart_count` and records `error` as the reason - used by
    src.execution.supervisor.PaperSessionSupervisor right before it sleeps
    and retries.
    """
    return SessionState(
        session_id=state.session_id,
        started_at=state.started_at,
        last_checkpoint_at=(now or datetime.now(UTC)).isoformat(),
        restart_count=state.restart_count + 1,
        last_error=error,
        fill_summary=state.fill_summary,
    )


def save_session_state(state: SessionState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2))


def load_session_state(path: Path) -> SessionState | None:
    """None if no checkpoint exists yet - the caller's cue to start a
    fresh session rather than an error condition.
    """
    if not path.exists():
        return None
    return SessionState.from_dict(json.loads(path.read_text()))
