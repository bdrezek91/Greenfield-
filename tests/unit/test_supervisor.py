from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.execution.session_state import load_session_state
from src.execution.supervisor import (
    PaperSessionSupervisor,
    RestartsExhaustedError,
    SupervisorConfig,
)


class TestPaperSessionSupervisorSuccess:
    def test_succeeds_on_first_try_without_sleeping(self, tmp_path: Path) -> None:
        sleeps: list[float] = []
        supervisor = PaperSessionSupervisor(
            SupervisorConfig(max_restarts=3, backoff_seconds=1.0),
            checkpoint_path=tmp_path / "session.json",
            session_id="s1",
            sleep_fn=sleeps.append,
            now_fn=lambda: datetime(2024, 1, 1, tzinfo=UTC),
        )
        calls = []
        state = supervisor.run(lambda: calls.append(1))
        assert calls == [1]
        assert state.restart_count == 0
        assert sleeps == []

    def test_checkpoint_file_reflects_final_state(self, tmp_path: Path) -> None:
        path = tmp_path / "session.json"
        supervisor = PaperSessionSupervisor(
            SupervisorConfig(),
            checkpoint_path=path,
            session_id="s1",
            sleep_fn=lambda s: None,
            now_fn=lambda: datetime(2024, 1, 1, tzinfo=UTC),
        )
        supervisor.run(lambda: None)
        loaded = load_session_state(path)
        assert loaded is not None
        assert loaded.session_id == "s1"


class TestPaperSessionSupervisorRetries:
    def test_retries_and_eventually_succeeds(self, tmp_path: Path) -> None:
        sleeps: list[float] = []
        supervisor = PaperSessionSupervisor(
            SupervisorConfig(max_restarts=5, backoff_seconds=1.0, backoff_multiplier=2.0),
            checkpoint_path=tmp_path / "session.json",
            session_id="s1",
            sleep_fn=sleeps.append,
            now_fn=lambda: datetime(2024, 1, 1, tzinfo=UTC),
        )
        attempts = {"n": 0}

        def flaky() -> None:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ConnectionError("simulated disconnect")

        state = supervisor.run(flaky)
        assert attempts["n"] == 3
        assert state.restart_count == 2
        assert sleeps == [1.0, 2.0]  # exponential backoff between the two failures

    def test_gives_up_after_max_restarts(self, tmp_path: Path) -> None:
        supervisor = PaperSessionSupervisor(
            SupervisorConfig(max_restarts=2, backoff_seconds=0.01),
            checkpoint_path=tmp_path / "session.json",
            session_id="s1",
            sleep_fn=lambda s: None,
            now_fn=lambda: datetime(2024, 1, 1, tzinfo=UTC),
        )

        def always_fails() -> None:
            raise RuntimeError("always broken")

        with pytest.raises(RestartsExhaustedError):
            supervisor.run(always_fails)

    def test_checkpoint_records_last_error_after_exhaustion(self, tmp_path: Path) -> None:
        path = tmp_path / "session.json"
        supervisor = PaperSessionSupervisor(
            SupervisorConfig(max_restarts=1, backoff_seconds=0.01),
            checkpoint_path=path,
            session_id="s1",
            sleep_fn=lambda s: None,
            now_fn=lambda: datetime(2024, 1, 1, tzinfo=UTC),
        )
        with pytest.raises(RestartsExhaustedError):
            supervisor.run(lambda: (_ for _ in ()).throw(ValueError("boom")))

        loaded = load_session_state(path)
        assert loaded is not None
        # max_restarts=1 -> tries at count 0 and 1, then bumps to 2 and gives up.
        assert loaded.restart_count == 2
        assert "boom" in (loaded.last_error or "")


class TestPaperSessionSupervisorResume:
    def test_resumes_restart_count_from_existing_checkpoint(self, tmp_path: Path) -> None:
        path = tmp_path / "session.json"
        first = PaperSessionSupervisor(
            SupervisorConfig(max_restarts=5, backoff_seconds=0.01),
            checkpoint_path=path,
            session_id="s1",
            sleep_fn=lambda s: None,
            now_fn=lambda: datetime(2024, 1, 1, tzinfo=UTC),
        )
        with pytest.raises(RestartsExhaustedError):
            first.run(lambda: (_ for _ in ()).throw(RuntimeError("x")))

        second = PaperSessionSupervisor(
            SupervisorConfig(max_restarts=100, backoff_seconds=0.01),
            checkpoint_path=path,
            session_id="s1",
            sleep_fn=lambda s: None,
            now_fn=lambda: datetime(2024, 1, 1, tzinfo=UTC),
        )
        state = second.run(lambda: None)
        assert state.restart_count == load_session_state(path).restart_count  # type: ignore[union-attr]
