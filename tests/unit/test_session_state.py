from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.execution.fill_tracking import FillTrackerSummary
from src.execution.session_state import (
    bump_restart,
    checkpoint,
    load_session_state,
    new_session_state,
    save_session_state,
)


class TestNewSessionState:
    def test_starts_with_zero_restarts_and_no_error(self) -> None:
        state = new_session_state("s1", now=datetime(2024, 1, 1, tzinfo=UTC))
        assert state.restart_count == 0
        assert state.last_error is None
        assert state.fill_summary is None
        assert state.started_at == state.last_checkpoint_at


class TestSaveLoadRoundtrip:
    def test_roundtrip(self, tmp_path: Path) -> None:
        state = new_session_state("s1", now=datetime(2024, 1, 1, tzinfo=UTC))
        path = tmp_path / "session.json"
        save_session_state(state, path)
        loaded = load_session_state(path)
        assert loaded == state

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert load_session_state(tmp_path / "nope.json") is None

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        state = new_session_state("s1")
        path = tmp_path / "nested" / "dir" / "session.json"
        save_session_state(state, path)
        assert path.exists()


class TestCheckpoint:
    def test_refreshes_timestamp_and_preserves_identity(self) -> None:
        state = new_session_state("s1", now=datetime(2024, 1, 1, tzinfo=UTC))
        later = checkpoint(state, now=datetime(2024, 1, 2, tzinfo=UTC))
        assert later.session_id == state.session_id
        assert later.started_at == state.started_at
        assert later.last_checkpoint_at != state.last_checkpoint_at
        assert later.restart_count == state.restart_count

    def test_updates_fill_summary(self) -> None:
        state = new_session_state("s1")
        summary = FillTrackerSummary(
            n_intents=5,
            n_rejected=1,
            rejection_rate=0.2,
            mean_latency_seconds=1.0,
            median_latency_seconds=1.0,
            mean_slippage=0.1,
            median_slippage=0.1,
            mean_slippage_pct=0.001,
            data_issue_count=0,
        )
        updated = checkpoint(state, fill_summary=summary)
        assert updated.fill_summary is not None
        assert updated.fill_summary["n_intents"] == 5

    def test_preserves_fill_summary_when_not_given(self) -> None:
        state = new_session_state("s1")
        state.fill_summary = {"n_intents": 3}
        updated = checkpoint(state)
        assert updated.fill_summary == {"n_intents": 3}


class TestBumpRestart:
    def test_increments_restart_count_and_sets_error(self) -> None:
        state = new_session_state("s1")
        bumped = bump_restart(state, error="ConnectionError()")
        assert bumped.restart_count == 1
        assert bumped.last_error == "ConnectionError()"

    def test_stacks_across_multiple_bumps(self) -> None:
        state = new_session_state("s1")
        state = bump_restart(state, error="e1")
        state = bump_restart(state, error="e2")
        assert state.restart_count == 2
        assert state.last_error == "e2"
