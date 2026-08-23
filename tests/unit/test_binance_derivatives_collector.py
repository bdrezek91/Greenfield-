"""BinanceOpenInterestCollector/BinanceLongShortRatioCollector.poll_once
must write only rows newer than the last one already written - Binance
re-returns the same recent readings on every call until the next period
rolls over, so a naive write would duplicate-attempt every poll (harmless
given storage's own dedup, but wasteful) or, worse, reset
_last_written_ts backwards on a partial/reordered response. Same pattern
as test_long_short_ratio_collector.py, for both Binance datasets.
"""

from __future__ import annotations

from pathlib import Path

from src.data.binance_derivatives_collector import (
    BinanceLongShortRatioCollector,
    BinanceOpenInterestCollector,
)
from src.data.binance_derivatives_storage import (
    read_binance_long_short_ratio,
    read_binance_open_interest,
)


class FakeOpenInterestClient:
    def __init__(self) -> None:
        self.responses: list[list[dict]] = []
        self.calls = 0

    def get_open_interest_history(self, symbol: str, period: str) -> list[dict]:
        response = self.responses[self.calls] if self.calls < len(self.responses) else []
        self.calls += 1
        return response


class FakeLongShortRatioClient:
    def __init__(self) -> None:
        self.responses: list[list[dict]] = []
        self.calls = 0

    def get_long_short_ratio_history(self, symbol: str, period: str) -> list[dict]:
        response = self.responses[self.calls] if self.calls < len(self.responses) else []
        self.calls += 1
        return response


def _oi_row(ts_ms: int, oi: float = 100000.0) -> dict:
    return {
        "symbol": "BTCUSDT",
        "sumOpenInterest": str(oi),
        "sumOpenInterestValue": str(oi * 80000),
        "timestamp": str(ts_ms),
    }


def _ratio_row(ts_ms: int, long_account: float = 0.51) -> dict:
    return {
        "symbol": "BTCUSDT",
        "longAccount": str(long_account),
        "shortAccount": str(1 - long_account),
        "longShortRatio": str(long_account / (1 - long_account)),
        "timestamp": str(ts_ms),
    }


def test_open_interest_poll_once_writes_new_rows_and_dedupes_across_polls(
    tmp_path: Path,
) -> None:
    client = FakeOpenInterestClient()
    client.responses = [
        [_oi_row(1_700_000_000_000), _oi_row(1_700_000_300_000)],
        [_oi_row(1_700_000_000_000), _oi_row(1_700_000_300_000), _oi_row(1_700_000_600_000)],
    ]
    collector = BinanceOpenInterestCollector("BTCUSDT", tmp_path, client=client, period="5m")

    first_written = collector.poll_once()
    second_written = collector.poll_once()

    assert first_written == 2
    assert second_written == 1
    result = read_binance_open_interest(tmp_path, "BTCUSDT", "5m")
    assert len(result) == 3


def test_open_interest_poll_once_returns_zero_on_empty_response(tmp_path: Path) -> None:
    client = FakeOpenInterestClient()
    client.responses = [[]]
    collector = BinanceOpenInterestCollector("BTCUSDT", tmp_path, client=client, period="5m")

    assert collector.poll_once() == 0


def test_long_short_ratio_poll_once_writes_new_rows_and_dedupes_across_polls(
    tmp_path: Path,
) -> None:
    client = FakeLongShortRatioClient()
    client.responses = [
        [_ratio_row(1_700_000_000_000), _ratio_row(1_700_000_300_000)],
        [
            _ratio_row(1_700_000_000_000),
            _ratio_row(1_700_000_300_000),
            _ratio_row(1_700_000_600_000),
        ],
    ]
    collector = BinanceLongShortRatioCollector("BTCUSDT", tmp_path, client=client, period="5m")

    first_written = collector.poll_once()
    second_written = collector.poll_once()

    assert first_written == 2
    assert second_written == 1
    result = read_binance_long_short_ratio(tmp_path, "BTCUSDT", "5m")
    assert len(result) == 3


def test_long_short_ratio_poll_once_returns_zero_on_empty_response(tmp_path: Path) -> None:
    client = FakeLongShortRatioClient()
    client.responses = [[]]
    collector = BinanceLongShortRatioCollector("BTCUSDT", tmp_path, client=client, period="5m")

    assert collector.poll_once() == 0
