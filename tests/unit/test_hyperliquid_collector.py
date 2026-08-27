"""HyperliquidMarketSnapshotCollector must filter to its configured coin
universe, stamp undated snapshot endpoints with its own poll time, use
`l2Book`'s own time for BBO, and write only non-empty datasets - the
Hyperliquid counterpart to test_okx_derivatives_collector.py.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.hyperliquid_collector import HyperliquidMarketSnapshotCollector
from src.data.hyperliquid_storage import (
    read_hyperliquid_asset_ctx,
    read_hyperliquid_bbo,
    read_hyperliquid_predicted_funding,
)

OBSERVED_AT = pd.Timestamp("2026-08-27T09:00:00Z")


class FakeHyperliquidClient:
    def __init__(self) -> None:
        self.l2_book_calls: list[str] = []

    def get_meta_and_asset_ctxs(self):
        universe = [{"name": "BTC"}, {"name": "ETH"}, {"name": "DOGE"}]
        ctxs = [
            {
                "funding": "0.0000125",
                "openInterest": "38325.13",
                "markPx": "80225.0",
                "oraclePx": "80225.9",
                "midPx": "80210.5",
                "premium": "-0.0001857256",
                "dayNtlVlm": "3421216797.8",
            },
            {
                "funding": "0.0000200",
                "openInterest": "500000.0",
                "markPx": "3000.0",
                "oraclePx": "3000.1",
                "midPx": "2999.9",
                "premium": "0.0000500",
                "dayNtlVlm": "900000000.0",
            },
            {
                "funding": "0.0001000",
                "openInterest": "1000.0",
                "markPx": "0.1",
                "oraclePx": "0.1001",
                "midPx": "0.0999",
                "premium": "0.0",
                "dayNtlVlm": "5000000.0",
            },
        ]
        return universe, ctxs

    def get_predicted_fundings(self):
        return [
            [
                "BTC",
                [
                    [
                        "HlPerp",
                        {
                            "fundingRate": "0.0000125",
                            "nextFundingTime": 1,
                            "fundingIntervalHours": 1,
                        },
                    ]
                ],
            ],
            [
                "ETH",
                [
                    [
                        "HlPerp",
                        {
                            "fundingRate": "0.0000200",
                            "nextFundingTime": 1,
                            "fundingIntervalHours": 1,
                        },
                    ]
                ],
            ],
            [
                "DOGE",
                [
                    [
                        "HlPerp",
                        {
                            "fundingRate": "0.0001000",
                            "nextFundingTime": 1,
                            "fundingIntervalHours": 1,
                        },
                    ]
                ],
            ],
        ]

    def get_l2_book(self, coin: str):
        self.l2_book_calls.append(coin)
        return {
            "coin": coin,
            "time": 1787814000000,
            "levels": [
                [{"px": "100.0", "sz": "1.0", "n": 1}],
                [{"px": "100.1", "sz": "2.0", "n": 1}],
            ],
        }


def test_poll_once_filters_to_configured_coins(tmp_path: Path) -> None:
    client = FakeHyperliquidClient()
    collector = HyperliquidMarketSnapshotCollector(
        ("BTC", "ETH"), tmp_path, client=client, now=lambda: OBSERVED_AT
    )

    written = collector.poll_once()

    assert written > 0
    assert set(client.l2_book_calls) == {"BTC", "ETH"}
    asset_ctx = read_hyperliquid_asset_ctx(tmp_path, "BTC")
    assert len(asset_ctx) == 1
    assert asset_ctx["timestamp"].iloc[0] == OBSERVED_AT
    assert asset_ctx["mark_px"].iloc[0] == 80225.0
    # DOGE was not in the configured coin universe - never written.
    assert read_hyperliquid_asset_ctx(tmp_path, "DOGE").empty


def test_poll_once_stamps_predicted_funding_with_poll_time_and_l2_book_with_its_own(
    tmp_path: Path,
) -> None:
    client = FakeHyperliquidClient()
    collector = HyperliquidMarketSnapshotCollector(
        ("BTC",), tmp_path, client=client, now=lambda: OBSERVED_AT
    )

    collector.poll_once()

    predicted = read_hyperliquid_predicted_funding(tmp_path, "BTC")
    assert predicted["timestamp"].iloc[0] == OBSERVED_AT

    bbo = read_hyperliquid_bbo(tmp_path, "BTC")
    assert bbo["timestamp"].iloc[0] == pd.Timestamp(1787814000000, unit="ms", tz="UTC")
    assert bbo["bid_price"].iloc[0] == 100.0
    assert bbo["ask_price"].iloc[0] == 100.1


def test_rejects_empty_coin_universe(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="at least one coin"):
        HyperliquidMarketSnapshotCollector((), tmp_path, client=FakeHyperliquidClient())
