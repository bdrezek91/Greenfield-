"""OkxOpenInterestCollector/OkxLongShortRatioCollector.poll_once must
write only rows newer than the last one already written - same reasoning
and pattern as test_binance_derivatives_collector.py.
"""

from __future__ import annotations

from pathlib import Path

from src.data.okx_derivatives_collector import (
    OkxLongShortRatioCollector,
    OkxOpenInterestCollector,
)
from src.data.okx_derivatives_storage import read_okx_long_short_ratio, read_okx_open_interest


class FakeOpenInterestClient:
    def __init__(self) -> None:
        self.responses: list[list[dict]] = []
        self.calls = 0

    def get_open_interest_snapshot(self, inst_id: str) -> list[dict]:
        response = self.responses[self.calls] if self.calls < len(self.responses) else []
        self.calls += 1
        return response


class FakeLongShortRatioClient:
    def __init__(self) -> None:
        self.responses: list[list[list[str]]] = []
        self.calls = 0

    def get_long_short_ratio_history(self, inst_id: str, period: str) -> list[list[str]]:
        response = self.responses[self.calls] if self.calls < len(self.responses) else []
        self.calls += 1
        return response


def _oi_row(ts_ms: int, oi: float = 3_000_000.0) -> dict:
    return {
        "instId": "BTC-USDT-SWAP",
        "instType": "SWAP",
        "oi": str(oi),
        "oiCcy": str(oi / 100),
        "oiUsd": str(oi * 800),
        "ts": str(ts_ms),
    }


def test_open_interest_poll_once_writes_new_rows_and_dedupes_across_polls(
    tmp_path: Path,
) -> None:
    client = FakeOpenInterestClient()
    client.responses = [[_oi_row(1_700_000_000_000)], [_oi_row(1_700_000_060_000)]]
    collector = OkxOpenInterestCollector("BTC-USDT-SWAP", tmp_path, client=client)

    first_written = collector.poll_once()
    second_written = collector.poll_once()

    assert first_written == 1
    assert second_written == 1
    result = read_okx_open_interest(tmp_path, "BTC-USDT-SWAP")
    assert len(result) == 2


def test_open_interest_poll_once_ignores_a_stale_repeated_snapshot(tmp_path: Path) -> None:
    client = FakeOpenInterestClient()
    # Second poll returns the exact same reading again (not yet updated) -
    # must not be re-written or advance _last_written_ts backwards.
    client.responses = [[_oi_row(1_700_000_000_000)], [_oi_row(1_700_000_000_000)]]
    collector = OkxOpenInterestCollector("BTC-USDT-SWAP", tmp_path, client=client)

    first_written = collector.poll_once()
    second_written = collector.poll_once()

    assert first_written == 1
    assert second_written == 0
    result = read_okx_open_interest(tmp_path, "BTC-USDT-SWAP")
    assert len(result) == 1


def test_open_interest_poll_once_returns_zero_on_empty_response(tmp_path: Path) -> None:
    client = FakeOpenInterestClient()
    client.responses = [[]]
    collector = OkxOpenInterestCollector("BTC-USDT-SWAP", tmp_path, client=client)

    assert collector.poll_once() == 0


def test_long_short_ratio_poll_once_writes_new_rows_and_dedupes_across_polls(
    tmp_path: Path,
) -> None:
    client = FakeLongShortRatioClient()
    client.responses = [
        [["1700000000000", "1.05"], ["1700000300000", "1.06"]],
        [["1700000000000", "1.05"], ["1700000300000", "1.06"], ["1700000600000", "1.07"]],
    ]
    collector = OkxLongShortRatioCollector("BTC-USDT-SWAP", tmp_path, client=client, period="5m")

    first_written = collector.poll_once()
    second_written = collector.poll_once()

    assert first_written == 2
    assert second_written == 1
    result = read_okx_long_short_ratio(tmp_path, "BTC-USDT-SWAP", "5m")
    assert len(result) == 3


def test_long_short_ratio_poll_once_returns_zero_on_empty_response(tmp_path: Path) -> None:
    client = FakeLongShortRatioClient()
    client.responses = [[]]
    collector = OkxLongShortRatioCollector("BTC-USDT-SWAP", tmp_path, client=client, period="5m")

    assert collector.poll_once() == 0
