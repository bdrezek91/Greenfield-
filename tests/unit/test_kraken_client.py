"""KrakenKlineClient must adapt ccxt's fetch_ohlcv rows into Bybit-shaped
kline rows (so ingest.py's parser stays unchanged), derive turnover, and
translate our canonical symbol into Kraken's raw contract code."""

from __future__ import annotations

import pytest

from src.data.kraken_client import KrakenKlineClient, to_kraken_symbol


class FakeTransport:
    def __init__(self, rows: list[list[float]]) -> None:
        self.rows = rows
        self.last_call: dict | None = None

    def fetch_ohlcv(self, symbol: str, timeframe: str, since=None, limit=None) -> list[list]:
        self.last_call = {"symbol": symbol, "timeframe": timeframe, "since": since, "limit": limit}
        return self.rows


def test_get_kline_page_converts_ohlcv_rows() -> None:
    transport = FakeTransport([[1_700_000_000_000, 100.0, 101.0, 99.0, 100.5, 10.0]])
    client = KrakenKlineClient(transport=transport)

    rows = client.get_kline_page(symbol="BTCUSD", interval="1h", start_ms=1, end_ms=2)

    assert rows == [["1700000000000", "100.0", "101.0", "99.0", "100.5", "10.0", "1005.0"]]
    assert transport.last_call["symbol"] == "PF_XBTUSD"  # translated, not our canonical symbol
    assert transport.last_call["timeframe"] == "1h"
    assert transport.last_call["since"] == 1


def test_get_kline_page_derives_turnover_as_volume_times_close() -> None:
    transport = FakeTransport([[0, 1.0, 1.0, 1.0, 50.0, 4.0]])
    client = KrakenKlineClient(transport=transport)

    rows = client.get_kline_page(symbol="ETHUSD", interval="1h")

    assert rows[0][-1] == "200.0"  # 4.0 * 50.0


def test_get_kline_page_empty_response() -> None:
    transport = FakeTransport([])
    client = KrakenKlineClient(transport=transport)

    rows = client.get_kline_page(symbol="BTCUSD", interval="1h")

    assert rows == []


class TestToKrakenSymbol:
    def test_translates_btc_ticker_override(self) -> None:
        assert to_kraken_symbol("BTCUSD") == "PF_XBTUSD"

    def test_passes_through_other_tickers_unchanged(self) -> None:
        assert to_kraken_symbol("ETHUSD") == "PF_ETHUSD"
        assert to_kraken_symbol("SOLUSD") == "PF_SOLUSD"

    def test_rejects_non_usd_symbol(self) -> None:
        with pytest.raises(ValueError, match="TICKER.*USD"):
            to_kraken_symbol("BTCEUR")
