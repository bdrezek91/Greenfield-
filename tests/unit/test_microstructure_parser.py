"""Parsing of raw Bybit v5 public WebSocket messages into canonical rows -
see src/data/microstructure_parser.py's module docstring for why this is
tested in isolation from the live WebSocket connection.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.microstructure_parser import (
    apply_orderbook_message,
    parse_liquidation_messages,
    parse_trade_message,
)
from src.data.orderbook_state import OrderBookState


class TestOrderbookMessages:
    def test_snapshot_message_produces_a_row(self) -> None:
        state = OrderBookState()
        message = {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304484978,
            "data": {
                "s": "BTCUSDT",
                "b": [["16493.50", "0.006"]],
                "a": [["16611.00", "0.029"]],
                "u": 18521288,
                "seq": 7961638724,
            },
        }

        row = apply_orderbook_message(state, message)

        assert row is not None
        assert row["symbol"] == "BTCUSDT"
        assert row["best_bid"] == 16493.50
        assert row["best_ask"] == 16611.00
        assert row["timestamp"] == pd.Timestamp(1672304484978, unit="ms", tz="UTC")

    def test_delta_before_snapshot_returns_none(self) -> None:
        state = OrderBookState()
        message = {
            "topic": "orderbook.50.BTCUSDT",
            "type": "delta",
            "ts": 1672304484978,
            "data": {"s": "BTCUSDT", "b": [["100.0", "1.0"]], "a": []},
        }

        assert apply_orderbook_message(state, message) is None

    def test_unrecognized_type_raises(self) -> None:
        state = OrderBookState()
        message = {"type": "bogus", "ts": 0, "data": {"s": "BTCUSDT", "b": [], "a": []}}

        with pytest.raises(ValueError, match="unrecognized orderbook message type"):
            apply_orderbook_message(state, message)


class TestTradeMessages:
    def test_parses_one_or_more_trades(self) -> None:
        message = {
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 1672304486868,
            "data": [
                {
                    "T": 1672304486865,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "v": "0.001",
                    "p": "16578.50",
                    "L": "PlusTick",
                    "i": "20f43950-d8dd-5b31-9112-a178eb6023af",
                    "BT": False,
                }
            ],
        }

        rows = parse_trade_message(message)

        assert len(rows) == 1
        assert rows[0]["price"] == 16578.50
        assert rows[0]["size"] == 0.001
        assert rows[0]["side"] == "Buy"
        assert rows[0]["trade_id"] == "20f43950-d8dd-5b31-9112-a178eb6023af"

    def test_empty_data_returns_empty_list(self) -> None:
        assert parse_trade_message({"data": []}) == []


class TestLiquidationMessages:
    def test_parses_a_batch_of_liquidation_events(self) -> None:
        # allLiquidation.{symbol} - batched list, same envelope shape as
        # publicTrade (see parse_liquidation_messages()'s docstring for why
        # this field convention is a best-evidence guess, not confirmed).
        message = {
            "topic": "allLiquidation.BTCUSDT",
            "type": "snapshot",
            "ts": 1673251091822,
            "data": [
                {
                    "T": 1673251091822,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "v": "0.003",
                    "p": "18485.00",
                }
            ],
        }

        rows = parse_liquidation_messages(message)

        assert len(rows) == 1
        assert rows[0]["symbol"] == "BTCUSDT"
        assert rows[0]["side"] == "Buy"
        assert rows[0]["price"] == 18485.00
        assert rows[0]["size"] == 0.003

    def test_empty_data_returns_empty_list(self) -> None:
        assert parse_liquidation_messages({"data": []}) == []
