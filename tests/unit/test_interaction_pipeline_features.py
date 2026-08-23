"""build_feature_matrix's optional liquidity-interaction feature families
(Cycle 31 - continues Cycles 26-30's wiring of orphaned src/features/
modules, this time src.features.interaction's book_liquidity_change_frame/
trade_interaction_frame). Same as-of-join pattern as trade_flow/
l2_imbalance (Cycle 26) - both built from normalized Silver order-book/
trade rows, not computed here, and independent of each other.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.data.normalized_event import normalize_bybit_event
from src.data.raw_event import parse_bybit_message
from src.features.interaction import book_liquidity_change_frame, trade_interaction_frame
from src.features.pipeline import (
    BOOK_LIQUIDITY_CHANGE_FEATURE_COLUMNS,
    FEATURE_COLUMNS,
    TRADE_INTERACTION_FEATURE_COLUMNS,
    build_feature_matrix,
)


def _ohlcv(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0.02, 0.6, size=n))
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100.0 + rng.normal(0, 10, size=n).cumsum().clip(min=0),
        }
    )


def _norm_rows(message: dict, receive_ns: int, sequence: int):
    return list(
        normalize_bybit_event(
            parse_bybit_message(
                json.dumps(message, separators=(",", ":")),
                receive_ts_ns=receive_ns,
                receive_sequence=sequence,
                connection_id="c",
            )
        )
    )


def _book(kind: str, update: int, receive_ns: int, bids, asks):
    return _norm_rows(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": kind,
            "ts": receive_ns // 1_000_000,
            "data": {"s": "BTCUSDT", "b": bids, "a": asks, "u": update, "seq": update},
        },
        receive_ns,
        update,
    )


def _book_liquidity_change_fixture() -> pd.DataFrame:
    rows = (
        _book("snapshot", 10, 1_700_000_000_010_000_000, [["100", "5"]], [["101", "4"]])
        + _book("delta", 11, 1_700_000_000_020_000_000, [["100", "2"]], [["101", "6"]])
        + _book("delta", 12, 1_700_000_000_030_000_000, [["100", "4"]], [])
    )
    return book_liquidity_change_frame(rows, symbol="BTCUSDT")


def _trade_interaction_fixture() -> pd.DataFrame:
    # Two separate WS messages (distinct receive_ts_ns) so the two buckets
    # get genuinely different emitted timestamps - matching real causality
    # (trades arrive over time, not all in one batch) and making the
    # as-of-join tests below meaningful.
    first_bucket = _norm_rows(
        {
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 60_300,
            "data": [
                {"T": 60_100, "s": "BTCUSDT", "S": "Buy", "v": "2", "p": "100", "i": "a"},
                {"T": 60_200, "s": "BTCUSDT", "S": "Buy", "v": "3", "p": "101", "i": "b"},
                {"T": 60_300, "s": "BTCUSDT", "S": "Sell", "v": "1", "p": "100", "i": "c"},
            ],
        },
        60_300_000_000,
        1,
    )
    second_bucket = _norm_rows(
        {
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 120_200,
            "data": [
                {"T": 120_100, "s": "BTCUSDT", "S": "Buy", "v": "1", "p": "102", "i": "d"},
                {"T": 120_200, "s": "BTCUSDT", "S": "Sell", "v": "2", "p": "102", "i": "e"},
            ],
        },
        120_200_000_000,
        2,
    )
    trades = first_bucket + second_bucket
    return trade_interaction_frame(trades, symbol="BTCUSDT", bucket_ms=60_000, price_tick="1")


def test_omitting_interaction_extras_leaves_output_unchanged() -> None:
    df = _ohlcv(60)
    out = build_feature_matrix(df)

    assert "bid_added" not in out.columns
    assert "buy_sweep" not in out.columns
    assert set(FEATURE_COLUMNS).issubset(out.columns)


def test_book_liquidity_change_and_trade_interaction_are_independent_extras() -> None:
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-11-14T22:13:00Z", periods=3, freq="1min"),
            "high": [100.0, 100.5, 101.0],
            "low": [99.5, 99.8, 100.2],
            "close": [99.8, 100.2, 100.8],
            "volume": [10.0, 12.0, 8.0],
        }
    )

    book_only = build_feature_matrix(df, book_liquidity_change=_book_liquidity_change_fixture())
    assert set(BOOK_LIQUIDITY_CHANGE_FEATURE_COLUMNS).issubset(book_only.columns)
    assert "buy_sweep" not in book_only.columns

    trade_only = build_feature_matrix(df, trade_interaction=_trade_interaction_fixture())
    assert set(TRADE_INTERACTION_FEATURE_COLUMNS).issubset(trade_only.columns)
    assert "bid_added" not in trade_only.columns


def test_book_liquidity_change_values_are_as_of_joined_correctly() -> None:
    df = pd.DataFrame(
        {
            # Derived from the fixture's own timestamps, not guessed by
            # hand - all three bars precede every fixture reading.
            "timestamp": pd.date_range(
                end=_book_liquidity_change_fixture()["timestamp"].min() - pd.Timedelta(minutes=1),
                periods=3,
                freq="1min",
            ),
            "high": [100.0, 100.5, 101.0],
            "low": [99.5, 99.8, 100.2],
            "close": [99.8, 100.2, 100.8],
            "volume": [10.0, 12.0, 8.0],
        }
    )
    fixture = _book_liquidity_change_fixture()
    assert fixture["timestamp"].min() > df["timestamp"].max()  # all bars precede the fixture

    out = build_feature_matrix(df, book_liquidity_change=fixture)

    # No book-liquidity reading has arrived yet by any of these bars.
    assert out["bid_added"].isna().all()


def test_trade_interaction_values_present_once_available() -> None:
    fixture = _trade_interaction_fixture()
    first_reading_ts = fixture["timestamp"].iloc[0]
    df = pd.DataFrame(
        {
            "timestamp": [
                first_reading_ts - pd.Timedelta(minutes=1),  # before the first reading
                first_reading_ts + pd.Timedelta(seconds=1),  # just after the first reading
            ],
            "high": [100.0, 100.5],
            "low": [99.5, 99.8],
            "close": [99.8, 100.2],
            "volume": [10.0, 12.0],
        }
    )

    out = build_feature_matrix(df, trade_interaction=fixture)

    assert pd.isna(out["buy_sweep"].iloc[0])  # before the first reading
    assert out["buy_sweep"].iloc[1] == fixture["buy_sweep"].iloc[0]
