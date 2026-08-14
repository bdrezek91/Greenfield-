"""trades_to_intents must convert signed quantity into BUY/SELL correctly
and use entry_price/entry_time as the intent's reference."""

from __future__ import annotations

import pandas as pd
import pytest

from src.execution.backtest_bridge import trades_to_intents
from src.execution.intent import IntentSide


def test_positive_quantity_is_buy() -> None:
    trades = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01T00:00"], utc=True),
            "quantity": [1.5],
            "entry_price": [100.0],
        }
    )
    intents = trades_to_intents(trades, symbol="BTCUSD")
    assert len(intents) == 1
    assert intents[0].side == IntentSide.BUY
    assert intents[0].quantity == pytest.approx(1.5)
    assert intents[0].reference_price == pytest.approx(100.0)
    assert intents[0].symbol == "BTCUSD"


def test_negative_quantity_is_sell() -> None:
    trades = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01T00:00"], utc=True),
            "quantity": [-2.0],
            "entry_price": [50.0],
        }
    )
    intents = trades_to_intents(trades, symbol="ETHUSD")
    assert intents[0].side == IntentSide.SELL
    assert intents[0].quantity == pytest.approx(2.0)  # magnitude, not signed


def test_multiple_trades_preserve_order() -> None:
    trades = pd.DataFrame(
        {
            "entry_time": pd.to_datetime(["2024-01-01T00:00", "2024-01-02T00:00"], utc=True),
            "quantity": [1.0, -1.0],
            "entry_price": [100.0, 105.0],
        }
    )
    intents = trades_to_intents(trades, symbol="BTCUSD")
    assert len(intents) == 2
    assert intents[0].side == IntentSide.BUY
    assert intents[1].side == IntentSide.SELL


def test_empty_trades_returns_empty_list() -> None:
    trades = pd.DataFrame(columns=["entry_time", "quantity", "entry_price"])
    assert trades_to_intents(trades, symbol="BTCUSD") == []
