"""Data-staleness detection for a long-running session (Phase 14) - one of
the section-32 checklist items ("data issues") applied continuously rather
than only at fill time: if no bar has arrived in longer than expected, that
is itself a data issue worth surfacing before it silently turns into a
strategy trading on stale prices.

Deliberately just a clock-in/clock-out counter, no NautilusTrader or
network dependency - takes `now` as an explicit argument everywhere so
tests don't need real wall-clock time or sleeps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class HeartbeatMonitor:
    max_gap_seconds: float
    _last_seen: datetime | None = field(default=None, repr=False)

    def record(self, now: datetime) -> None:
        self._last_seen = now

    @property
    def last_seen(self) -> datetime | None:
        return self._last_seen

    def seconds_since_last(self, now: datetime) -> float | None:
        """None if nothing has ever been recorded - distinct from 0.0
        (just recorded) or a large gap."""
        if self._last_seen is None:
            return None
        return (now - self._last_seen).total_seconds()

    def is_stale(self, now: datetime) -> bool:
        """True if nothing has ever been recorded, or the gap since the
        last record exceeds `max_gap_seconds` - "never received a bar" and
        "stopped receiving bars" are both staleness, treated identically.
        """
        gap = self.seconds_since_last(now)
        return gap is None or gap > self.max_gap_seconds
