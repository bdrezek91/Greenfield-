"""MicrostructureCollector: buffers messages, flushes each stream on its
own interval, writes nothing until due. The live WebSocket connection
itself (`run_forever`'s `ws_factory`) is injected so none of this touches
the network - see src/data/microstructure_collector.py's module docstring
for what's NOT verified.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.microstructure_collector import MicrostructureCollector
from src.data.microstructure_writer import read_range


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _orderbook_snapshot(ts_ms: int) -> dict:
    return {
        "type": "snapshot",
        "ts": ts_ms,
        "data": {"s": "BTCUSDT", "b": [["100.0", "1.0"]], "a": [["101.0", "1.0"]]},
    }


def _trade_message(ts_ms: int) -> dict:
    return {
        "data": [
            {
                "T": ts_ms,
                "s": "BTCUSDT",
                "S": "Buy",
                "v": "0.01",
                "p": "100.5",
                "i": "abc",
            }
        ]
    }


def _liquidation_message(ts_ms: int) -> dict:
    return {
        "data": [
            {
                "T": ts_ms,
                "s": "BTCUSDT",
                "S": "Sell",
                "p": "99.0",
                "v": "0.5",
            }
        ]
    }


def test_buffers_and_does_not_write_before_interval_elapses(tmp_path: Path) -> None:
    clock = FakeClock()
    collector = MicrostructureCollector(
        "BTCUSDT", tmp_path, flush_interval_secs=30.0, clock=clock
    )

    collector.on_orderbook_message(_orderbook_snapshot(1_700_000_000_000))

    result = read_range(
        tmp_path,
        "orderbook",
        "BTCUSDT",
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2030-01-01", tz="UTC"),
    )
    assert result.empty  # not flushed yet


def test_flushes_once_the_interval_elapses(tmp_path: Path) -> None:
    clock = FakeClock()
    collector = MicrostructureCollector(
        "BTCUSDT", tmp_path, flush_interval_secs=30.0, clock=clock
    )

    collector.on_orderbook_message(_orderbook_snapshot(1_700_000_000_000))
    clock.advance(31.0)
    collector.on_orderbook_message(_orderbook_snapshot(1_700_000_000_500))

    result = read_range(
        tmp_path,
        "orderbook",
        "BTCUSDT",
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2030-01-01", tz="UTC"),
    )
    assert len(result) == 2


def test_streams_flush_independently(tmp_path: Path) -> None:
    clock = FakeClock()
    collector = MicrostructureCollector(
        "BTCUSDT", tmp_path, flush_interval_secs=30.0, clock=clock
    )

    collector.on_orderbook_message(_orderbook_snapshot(1_700_000_000_000))
    clock.advance(31.0)
    # Only a trade arrives now - only the trades stream's clock resets/flushes.
    collector.on_trade_message(_trade_message(1_700_000_031_000))

    orderbook = read_range(
        tmp_path,
        "orderbook",
        "BTCUSDT",
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2030-01-01", tz="UTC"),
    )
    trades = read_range(
        tmp_path,
        "trades",
        "BTCUSDT",
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2030-01-01", tz="UTC"),
    )
    # Orderbook's own check only runs when an orderbook message arrives -
    # none has since t=0, so its buffered snapshot is still unflushed even
    # though 31s (> the 30s interval) have passed.
    assert orderbook.empty
    # Trades' last-flush baseline is also t=0 (both streams start there),
    # so this first trade message's own arrival-time check (31s >= 30s)
    # flushes it immediately, including itself.
    assert len(trades) == 1


def test_liquidation_messages_are_parsed_and_buffered(tmp_path: Path) -> None:
    clock = FakeClock()
    collector = MicrostructureCollector(
        "BTCUSDT", tmp_path, flush_interval_secs=0.0, clock=clock
    )

    collector.on_liquidation_message(_liquidation_message(1_700_000_000_000))

    result = read_range(
        tmp_path,
        "liquidations",
        "BTCUSDT",
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2030-01-01", tz="UTC"),
    )
    assert len(result) == 1
    assert result["side"].iloc[0] == "Sell"


def test_explicit_flush_writes_all_streams_regardless_of_interval(tmp_path: Path) -> None:
    clock = FakeClock()
    collector = MicrostructureCollector(
        "BTCUSDT", tmp_path, flush_interval_secs=999.0, clock=clock
    )

    collector.on_orderbook_message(_orderbook_snapshot(1_700_000_000_000))
    collector.on_trade_message(_trade_message(1_700_000_000_100))
    collector.on_liquidation_message(_liquidation_message(1_700_000_000_200))
    collector.flush()

    for stream in ("orderbook", "trades", "liquidations"):
        result = read_range(
            tmp_path,
            stream,
            "BTCUSDT",
            start=pd.Timestamp("2020-01-01", tz="UTC"),
            end=pd.Timestamp("2030-01-01", tz="UTC"),
        )
        assert len(result) == 1


def test_run_forever_subscribes_all_three_streams_and_flushes_on_interrupt(
    tmp_path: Path,
) -> None:
    class FakeWS:
        def __init__(self) -> None:
            self.subscribed: list[str] = []

        def orderbook_stream(self, depth, symbol, callback) -> None:
            self.subscribed.append("orderbook")
            callback(_orderbook_snapshot(1_700_000_000_000))

        def trade_stream(self, symbol, callback) -> None:
            self.subscribed.append("trades")
            callback(_trade_message(1_700_000_000_100))

        def all_liquidation_stream(self, symbol, callback) -> None:
            self.subscribed.append("liquidations")
            callback(_liquidation_message(1_700_000_000_200))

    fake_ws = FakeWS()

    def raise_keyboard_interrupt(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    clock = FakeClock()
    collector = MicrostructureCollector(
        "BTCUSDT",
        tmp_path,
        flush_interval_secs=999.0,
        clock=clock,
        ws_factory=lambda: fake_ws,
    )
    import time as time_module

    original_sleep = time_module.sleep
    time_module.sleep = raise_keyboard_interrupt
    try:
        collector.run_forever()
    finally:
        time_module.sleep = original_sleep

    assert set(fake_ws.subscribed) == {"orderbook", "trades", "liquidations"}
    for stream in ("orderbook", "trades", "liquidations"):
        result = read_range(
            tmp_path,
            stream,
            "BTCUSDT",
            start=pd.Timestamp("2020-01-01", tz="UTC"),
            end=pd.Timestamp("2030-01-01", tz="UTC"),
        )
        assert len(result) == 1  # final flush on KeyboardInterrupt wrote everything


def test_sigterm_also_triggers_a_final_flush(tmp_path: Path) -> None:
    # docker stop sends SIGTERM, not SIGINT - Python only auto-converts
    # SIGINT to KeyboardInterrupt, so without an explicit SIGTERM handler
    # a `docker stop` would kill the process with buffered-but-unflushed
    # data silently lost. This sends a real SIGTERM to this test process
    # to prove run_forever's handler actually catches it.
    import os
    import signal
    import time as time_module

    class FakeWS:
        def orderbook_stream(self, depth, symbol, callback) -> None:
            callback(_orderbook_snapshot(1_700_000_000_000))

        def trade_stream(self, symbol, callback) -> None:
            pass

        def all_liquidation_stream(self, symbol, callback) -> None:
            pass

    def send_sigterm_to_self(*args: object, **kwargs: object) -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    clock = FakeClock()
    collector = MicrostructureCollector(
        "BTCUSDT",
        tmp_path,
        flush_interval_secs=999.0,
        clock=clock,
        ws_factory=lambda: FakeWS(),
    )

    original_sleep = time_module.sleep
    time_module.sleep = send_sigterm_to_self
    try:
        collector.run_forever()
    finally:
        time_module.sleep = original_sleep
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    result = read_range(
        tmp_path,
        "orderbook",
        "BTCUSDT",
        start=pd.Timestamp("2020-01-01", tz="UTC"),
        end=pd.Timestamp("2030-01-01", tz="UTC"),
    )
    assert len(result) == 1
