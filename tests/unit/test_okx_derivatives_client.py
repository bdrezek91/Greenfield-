"""OkxOpenInterestClient/OkxLongShortRatioClient must unwrap OKX's
{code, data, msg} envelope, surface API errors, and reject invalid
periods - the OKX counterpart to test_binance_derivatives_client.py.
"""

from __future__ import annotations

import pytest

from src.data.okx_derivatives_client import OkxLongShortRatioClient, OkxOpenInterestClient


class FakeFetcher:
    def __init__(self, response: list[dict]) -> None:
        self.response = response
        self.last_path: str | None = None
        self.last_params: dict | None = None

    def __call__(self, path: str, params: dict) -> list[dict]:
        self.last_path = path
        self.last_params = params
        return self.response


def test_open_interest_snapshot_returns_rows_and_builds_params() -> None:
    fetcher = FakeFetcher([{"instId": "BTC-USDT-SWAP", "oi": "1000", "ts": "1"}])
    client = OkxOpenInterestClient(fetcher=fetcher)

    rows = client.get_open_interest_snapshot("BTC-USDT-SWAP")

    assert rows == fetcher.response
    assert fetcher.last_path == "public/open-interest"
    assert fetcher.last_params == {"instType": "SWAP", "instId": "BTC-USDT-SWAP"}


def test_long_short_ratio_history_returns_rows_and_builds_params() -> None:
    fetcher = FakeFetcher([["1700000000000", "1.05"]])
    client = OkxLongShortRatioClient(fetcher=fetcher)

    rows = client.get_long_short_ratio_history("BTC-USDT-SWAP", "5m", limit=50)

    assert rows == fetcher.response
    assert fetcher.last_path == "rubik/stat/contracts/long-short-account-ratio-contract"
    assert fetcher.last_params == {"instId": "BTC-USDT-SWAP", "period": "5m", "limit": 50}


def test_long_short_ratio_history_omits_limit_when_not_given() -> None:
    fetcher = FakeFetcher([])
    client = OkxLongShortRatioClient(fetcher=fetcher)

    client.get_long_short_ratio_history("BTC-USDT-SWAP", "5m")

    assert "limit" not in fetcher.last_params


def test_long_short_ratio_history_rejects_invalid_period() -> None:
    client = OkxLongShortRatioClient(fetcher=FakeFetcher([]))
    with pytest.raises(ValueError, match="period"):
        client.get_long_short_ratio_history("BTC-USDT-SWAP", "9m")
