"""LongShortRatioCollector.poll_once must write only rows newer than the
last one already written - Bybit re-returns the same recent readings on
every call until the next period rolls over, so a naive write would
duplicate-attempt every poll (harmless given storage's own dedup, but
wasteful and noisy) or, worse, reset _last_written_ts backwards on a
partial/reordered response.
"""

from __future__ import annotations

from pathlib import Path

from src.data.long_short_ratio_collector import LongShortRatioCollector
from src.data.storage import read_long_short_ratio


class FakeClient:
    def __init__(self) -> None:
        self.responses: list[list[dict]] = []
        self.calls = 0

    def get_long_short_ratio(self, *, category: str, symbol: str, period: str) -> list[dict]:
        response = self.responses[self.calls] if self.calls < len(self.responses) else []
        self.calls += 1
        return response


def _row(ts_ms: int, buy: float = 0.5) -> dict:
    return {
        "symbol": "BTCUSDT",
        "buyRatio": str(buy),
        "sellRatio": str(1 - buy),
        "timestamp": str(ts_ms),
    }


def test_poll_once_writes_new_rows_and_dedupes_across_polls(tmp_path: Path) -> None:
    client = FakeClient()
    # First poll: two readings. Second poll: same two plus one new one -
    # only the new one should be written the second time.
    client.responses = [
        [_row(1_700_000_000_000), _row(1_700_000_300_000)],
        [_row(1_700_000_000_000), _row(1_700_000_300_000), _row(1_700_000_600_000)],
    ]
    collector = LongShortRatioCollector("BTCUSDT", tmp_path, client=client, period="5min")

    first_written = collector.poll_once()
    second_written = collector.poll_once()

    assert first_written == 2
    assert second_written == 1
    result = read_long_short_ratio(tmp_path, "BTCUSDT", "5min")
    assert len(result) == 3


def test_poll_once_returns_zero_on_empty_response(tmp_path: Path) -> None:
    client = FakeClient()
    client.responses = [[]]
    collector = LongShortRatioCollector("BTCUSDT", tmp_path, client=client, period="5min")

    assert collector.poll_once() == 0
