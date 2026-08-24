"""Strict public-Bybit adapter for the autonomous Demo opportunity scanner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import pandas as pd
from pybit.unified_trading import HTTP

from src.execution.bybit_demo_gateway import BYBIT_PUBLIC_REST_URL
from src.execution.demo_opportunity_scanner import (
    BybitOpportunitySnapshot,
    PublicTrade,
)


class BybitOpportunityFeedError(RuntimeError):
    """Public market data is incomplete, malformed, or from the wrong host."""


class _PublicClient(Protocol):
    endpoint: str

    def get_kline(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_public_trade_history(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_mark_price_kline(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_index_price_kline(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_open_interest(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_tickers(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_instruments_info(self, **kwargs: Any) -> dict[str, Any]: ...


class PybitBybitOpportunityFeed:
    """Fetch public mainnet evidence while execution remains pinned to Demo."""

    endpoint = BYBIT_PUBLIC_REST_URL

    def __init__(self, *, client: _PublicClient | None = None) -> None:
        self._client: _PublicClient = client or cast(
            _PublicClient, HTTP(testnet=False)
        )
        if self._client.endpoint != self.endpoint:
            raise BybitOpportunityFeedError(
                f"refusing non-mainnet public Bybit endpoint: {self._client.endpoint!r}"
            )

    def fetch(
        self,
        *,
        symbol: str,
        observed_at_utc: datetime | None = None,
    ) -> BybitOpportunitySnapshot:
        if not symbol or symbol != symbol.upper():
            raise ValueError("opportunity feed symbol must be uppercase")
        requested_observed = (
            observed_at_utc.astimezone(UTC) if observed_at_utc is not None else None
        )
        candles_response = self._client.get_kline(
            category="linear", symbol=symbol, interval="5", limit=200
        )
        trades_response = self._client.get_public_trade_history(
            category="linear", symbol=symbol, limit=1000
        )
        mark_response = self._client.get_mark_price_kline(
            category="linear", symbol=symbol, interval="5", limit=60
        )
        index_response = self._client.get_index_price_kline(
            category="linear", symbol=symbol, interval="5", limit=60
        )
        interest_response = self._client.get_open_interest(
            category="linear", symbol=symbol, intervalTime="5min", limit=60
        )
        ticker_response = self._client.get_tickers(category="linear", symbol=symbol)
        instrument_response = self._client.get_instruments_info(
            category="linear", symbol=symbol
        )
        responses = (
            candles_response,
            trades_response,
            mark_response,
            index_response,
            interest_response,
            ticker_response,
            instrument_response,
        )
        # For a live call, take the cutoff only after every response arrived.
        # A busy venue can legitimately return a trade a few milliseconds after
        # the call started; fixing the cutoff before I/O would label that row as
        # future data even though it was already known when the scan began.
        observed = requested_observed or datetime.now(UTC)
        for response in responses:
            _validate_response_time(response, observed)
        candles = _candles(_rows(candles_response, "klines"), observed)
        trades = _trades(_rows(trades_response, "public trades"), observed, symbol)
        derivatives = _derivatives(
            mark_rows=_rows(mark_response, "mark-price klines"),
            index_rows=_rows(index_response, "index-price klines"),
            interest_rows=_rows(interest_response, "open interest"),
            ticker_rows=_rows(ticker_response, "ticker"),
            observed=observed,
        )
        price_tick = _price_tick(_rows(instrument_response, "instrument"), symbol)
        return BybitOpportunitySnapshot(
            symbol=symbol,
            observed_at_utc=observed,
            candles=candles,
            trades=trades,
            derivatives=derivatives,
            price_tick=price_tick,
        )


def _result(response: dict[str, Any], operation: str) -> dict[str, Any]:
    if response.get("retCode") != 0:
        raise BybitOpportunityFeedError(
            f"Bybit public {operation} failed: {response.get('retMsg', 'unknown error')}"
        )
    result = response.get("result")
    if not isinstance(result, dict):
        raise BybitOpportunityFeedError(f"Bybit public {operation} result is invalid")
    return result


def _rows(response: dict[str, Any], operation: str) -> list[Any]:
    rows = _result(response, operation).get("list")
    if not isinstance(rows, list) or not rows:
        raise BybitOpportunityFeedError(f"Bybit public {operation} rows are empty")
    return rows


def _validate_response_time(response: dict[str, Any], observed: datetime) -> None:
    provider_ms = response.get("time")
    if not isinstance(provider_ms, int):
        raise BybitOpportunityFeedError("Bybit public response has no server time")
    provider = datetime.fromtimestamp(provider_ms / 1000, tz=UTC)
    if abs((provider - observed).total_seconds()) > 60:
        raise BybitOpportunityFeedError("Bybit public response time is stale or from the future")


def _candles(rows: list[Any], observed: datetime) -> pd.DataFrame:
    output = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            raise BybitOpportunityFeedError("invalid Bybit public kline row")
        started = datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC)
        feature_at = min(started, observed)
        output.append(
            {
                "timestamp": pd.Timestamp(feature_at),
                "max_source_timestamp": pd.Timestamp(feature_at),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
    return pd.DataFrame(output).sort_values("timestamp").drop_duplicates("timestamp")


def _trades(
    rows: list[Any], observed: datetime, symbol: str
) -> tuple[PublicTrade, ...]:
    output = []
    for row in rows:
        if not isinstance(row, dict) or row.get("symbol") != symbol:
            raise BybitOpportunityFeedError("invalid Bybit public trade row")
        timestamp = datetime.fromtimestamp(int(row["time"]) / 1000, tz=UTC)
        if timestamp > observed + timedelta(seconds=1):
            raise BybitOpportunityFeedError("Bybit public trade is from the future")
        output.append(
            PublicTrade(
                trade_id=str(row["execId"]),
                timestamp_utc=timestamp,
                side=str(row["side"]).casefold(),
                price=float(row["price"]),
                size=float(row["size"]),
            )
        )
    return tuple(sorted(output, key=lambda item: (item.timestamp_utc, item.trade_id)))


def _derivatives(
    *,
    mark_rows: list[Any],
    index_rows: list[Any],
    interest_rows: list[Any],
    ticker_rows: list[Any],
    observed: datetime,
) -> pd.DataFrame:
    if not isinstance(ticker_rows[0], dict):
        raise BybitOpportunityFeedError("invalid Bybit public ticker row")
    funding_rate = float(ticker_rows[0]["fundingRate"])
    mark = _close_series(mark_rows, "mark price")
    index = _close_series(index_rows, "index price")
    interest_records = []
    for row in interest_rows:
        if not isinstance(row, dict):
            raise BybitOpportunityFeedError("invalid Bybit public open-interest row")
        interest_records.append(
            {
                "timestamp": pd.to_datetime(int(row["timestamp"]), unit="ms", utc=True),
                "open_interest": float(row["openInterest"]),
            }
        )
    interest = pd.DataFrame(interest_records).sort_values("timestamp")
    value = pd.merge_asof(
        mark,
        index,
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("5min"),
    )
    value = pd.merge_asof(
        value.sort_values("timestamp"),
        interest,
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("5min"),
    ).dropna()
    if len(value) < 20:
        raise BybitOpportunityFeedError("insufficient aligned Bybit derivatives history")
    value["timestamp"] = value["timestamp"].map(
        lambda item: min(item.to_pydatetime(), observed)
    )
    value["max_source_timestamp"] = value["timestamp"]
    value["funding_rate"] = funding_rate
    return value[
        [
            "timestamp",
            "max_source_timestamp",
            "mark_price",
            "index_price",
            "open_interest",
            "funding_rate",
        ]
    ]


def _close_series(rows: list[Any], name: str) -> pd.DataFrame:
    output = []
    column = name.replace(" ", "_")
    for row in rows:
        if not isinstance(row, list) or len(row) < 5:
            raise BybitOpportunityFeedError(f"invalid Bybit public {name} row")
        output.append(
            {
                "timestamp": pd.to_datetime(int(row[0]), unit="ms", utc=True),
                column: float(row[4]),
            }
        )
    return pd.DataFrame(output).sort_values("timestamp").drop_duplicates("timestamp")


def _price_tick(rows: list[Any], symbol: str) -> float:
    row = rows[0]
    if not isinstance(row, dict) or row.get("symbol") != symbol:
        raise BybitOpportunityFeedError("invalid Bybit public instrument row")
    price_filter = row.get("priceFilter")
    if not isinstance(price_filter, dict):
        raise BybitOpportunityFeedError("Bybit public instrument has no price filter")
    return float(price_filter["tickSize"])
