from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.execution.intent import IntentSide, OrderIntent
from src.execution.kraken_adapter import KrakenExecutionAdapter
from src.execution.mode import TradingMode


def _intent(side: IntentSide = IntentSide.BUY) -> OrderIntent:
    return OrderIntent(
        symbol="BTCUSD",
        side=side,
        quantity=1.0,
        reference_price=50_000.0,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        reason="test",
    )


class FakeTransport:
    def __init__(self, response: dict | None = None, raises: Exception | None = None) -> None:
        self.response = response
        self.raises = raises
        self.last_call: dict | None = None

    def create_order(self, symbol: str, type: str, side: str, amount: float) -> dict:
        self.last_call = {"symbol": symbol, "type": type, "side": side, "amount": amount}
        if self.raises is not None:
            raise self.raises
        return self.response


class TestKrakenExecutionAdapterConstruction:
    def test_rejects_research_mode(self) -> None:
        with pytest.raises(ValueError, match="PAPER or LIVE"):
            KrakenExecutionAdapter(TradingMode.RESEARCH, "k", "s", transport=FakeTransport({}))

    def test_rejects_backtest_mode(self) -> None:
        with pytest.raises(ValueError, match="PAPER or LIVE"):
            KrakenExecutionAdapter(TradingMode.BACKTEST, "k", "s", transport=FakeTransport({}))

    def test_accepts_paper_mode(self) -> None:
        KrakenExecutionAdapter(TradingMode.PAPER, "k", "s", transport=FakeTransport({}))

    def test_accepts_live_mode(self) -> None:
        KrakenExecutionAdapter(TradingMode.LIVE, "k", "s", transport=FakeTransport({}))


class TestKrakenExecutionAdapterSubmit:
    def test_translates_symbol_and_side(self) -> None:
        transport = FakeTransport(
            {"average": 50_010.0, "filled": 1.0, "timestamp": 1_700_000_000_000}
        )
        adapter = KrakenExecutionAdapter(TradingMode.PAPER, "k", "s", transport=transport)

        adapter.submit(_intent(IntentSide.BUY))

        assert transport.last_call["symbol"] == "PF_XBTUSD"
        assert transport.last_call["side"] == "buy"
        assert transport.last_call["amount"] == 1.0

    def test_sell_side_translated(self) -> None:
        transport = FakeTransport({"average": 50_000.0, "filled": 1.0, "timestamp": 1})
        adapter = KrakenExecutionAdapter(TradingMode.PAPER, "k", "s", transport=transport)

        adapter.submit(_intent(IntentSide.SELL))

        assert transport.last_call["side"] == "sell"

    def test_successful_fill(self) -> None:
        transport = FakeTransport(
            {"average": 50_010.0, "filled": 1.0, "timestamp": 1_700_000_000_000}
        )
        adapter = KrakenExecutionAdapter(TradingMode.PAPER, "k", "s", transport=transport)

        fill = adapter.submit(_intent())

        assert fill.rejected is False
        assert fill.filled_price == 50_010.0
        assert fill.filled_quantity == 1.0

    def test_falls_back_to_reference_price_when_no_average_or_price(self) -> None:
        transport = FakeTransport({"filled": 1.0, "timestamp": 1})
        adapter = KrakenExecutionAdapter(TradingMode.PAPER, "k", "s", transport=transport)

        fill = adapter.submit(_intent())

        assert fill.filled_price == 50_000.0  # intent.reference_price

    def test_transport_exception_becomes_rejected_fill(self) -> None:
        transport = FakeTransport(raises=RuntimeError("connection reset"))
        adapter = KrakenExecutionAdapter(TradingMode.PAPER, "k", "s", transport=transport)

        fill = adapter.submit(_intent())

        assert fill.rejected is True
        assert "connection reset" in fill.reject_reason

    def test_zero_filled_quantity_becomes_rejected_fill(self) -> None:
        transport = FakeTransport({"average": 50_000.0, "filled": 0.0, "timestamp": 1})
        adapter = KrakenExecutionAdapter(TradingMode.PAPER, "k", "s", transport=transport)

        fill = adapter.submit(_intent())

        assert fill.rejected is True
