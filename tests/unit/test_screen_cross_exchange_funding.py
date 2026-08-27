"""scripts/screen_cross_exchange_funding.py: empty --symbols is rejected
before any network connection is attempted, and the per-venue quote
builders normalize each venue's own funding cadence to an hourly rate
before handing off to src.engines.neutral_market.
"""

from __future__ import annotations

from datetime import UTC, datetime

from typer.testing import CliRunner

from scripts.screen_cross_exchange_funding import _bybit_quote, _hyperliquid_quote, app

runner = CliRunner()

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def test_empty_symbols_is_rejected() -> None:
    result = runner.invoke(app, ["--symbols", ""])
    assert result.exit_code != 0
    assert "symbols must list" in str(result.output)


class FakeBybitClient:
    def get_ticker(self, symbol: str):
        assert symbol == "BTCUSDT"
        return {
            "bid1Price": "80000.0",
            "ask1Price": "80001.0",
            "bid1Size": "1.5",
            "fundingRate": "0.0001",
            "fundingIntervalHour": "8",
        }


def test_bybit_quote_normalizes_8h_funding_to_hourly() -> None:
    quote = _bybit_quote(FakeBybitClient(), "BTC", as_of=NOW)

    assert quote.venue == "bybit"
    assert quote.symbol == "BTC"
    assert quote.bid == 80000.0
    assert quote.ask == 80001.0
    assert quote.funding_rate_per_period == 0.0001 / 8
    assert quote.received_at_utc == NOW


class FakeHyperliquidClient:
    def get_predicted_fundings(self):
        return [
            [
                "BTC",
                [["HlPerp", {"fundingRate": "0.0000125", "fundingIntervalHours": 1}]],
            ]
        ]

    def get_l2_book(self, coin: str):
        assert coin == "BTC"
        return {
            "time": 1787814000000,
            "levels": [
                [{"px": "79995.0", "sz": "2.0", "n": 1}],
                [{"px": "79996.0", "sz": "3.0", "n": 1}],
            ],
        }


def test_hyperliquid_quote_normalizes_1h_funding_to_hourly_and_uses_book_time() -> None:
    quote = _hyperliquid_quote(FakeHyperliquidClient(), "BTC")

    assert quote.venue == "hyperliquid"
    assert quote.bid == 79995.0
    assert quote.ask == 79996.0
    assert quote.funding_rate_per_period == 0.0000125
    assert quote.received_at_utc.isoformat() == "2026-08-27T07:00:00+00:00"
