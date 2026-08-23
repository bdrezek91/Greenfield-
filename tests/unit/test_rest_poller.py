"""run_polling_loop must poll until KeyboardInterrupt, keep looping after
a bad poll, and never let SIGTERM crash out unhandled - extracted from
src/data/binance_derivatives_collector.py in Cycle 18, now shared by both
the Binance and OKX derivatives collectors.
"""

from __future__ import annotations

from src.data.rest_poller import run_polling_loop


def test_stops_after_keyboard_interrupt_from_sleep() -> None:
    calls = {"poll": 0, "sleep": 0}

    def poll_once() -> int:
        calls["poll"] += 1
        return 1

    def sleep(_seconds: float) -> None:
        calls["sleep"] += 1
        if calls["sleep"] >= 3:
            raise KeyboardInterrupt

    run_polling_loop(name="test", poll_once=poll_once, poll_interval_secs=0.0, sleep=sleep)

    assert calls["poll"] == 3
    assert calls["sleep"] == 3


def test_continues_after_a_failing_poll() -> None:
    calls = {"poll": 0, "sleep": 0}

    def poll_once() -> int:
        calls["poll"] += 1
        if calls["poll"] == 1:
            raise RuntimeError("transient failure")
        return 1

    def sleep(_seconds: float) -> None:
        calls["sleep"] += 1
        if calls["sleep"] >= 2:
            raise KeyboardInterrupt

    run_polling_loop(name="test", poll_once=poll_once, poll_interval_secs=0.0, sleep=sleep)

    assert calls["poll"] == 2
