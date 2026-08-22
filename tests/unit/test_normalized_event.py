"""Bronze-to-Silver normalization preserves exact values and lineage."""

from __future__ import annotations

import hashlib
import json

import pytest

from src.data.normalized_event import (
    NORMALIZER_VERSION,
    NormalizationError,
    normalize_bybit_event,
    normalize_bybit_events,
)
from src.data.raw_event import parse_bybit_message


def _raw(message: dict, *, sequence: int = 1):
    return parse_bybit_message(
        json.dumps(message, separators=(",", ":")),
        receive_ts_ns=1_700_000_000_001_000_000 + sequence,
        receive_sequence=sequence,
        connection_id="connection-1",
    )


def test_trade_normalization_preserves_decimal_text_and_lineage() -> None:
    raw = _raw(
        {
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 1_700_000_000_010,
            "data": [
                {
                    "T": 1_700_000_000_009,
                    "s": "BTCUSDT",
                    "S": "Buy",
                    "v": "0.0012300",
                    "p": "16578.500",
                    "L": "PlusTick",
                    "i": "trade-1",
                    "BT": False,
                    "RPI": True,
                }
            ],
        }
    )

    (row,) = normalize_bybit_event(raw)

    assert row.record_type == "trade"
    assert row.side == "buy"
    assert row.price == "16578.500"
    assert row.size == "0.0012300"
    assert row.trade_id == "trade-1"
    assert row.is_block_trade is False
    assert row.is_rpi_trade is True
    assert row.raw_event_id == raw.event_id
    assert row.raw_payload_sha256 == raw.payload_sha256
    assert row.normalized_id == hashlib.sha256(
        f"{NORMALIZER_VERSION}|{raw.event_id}|0".encode("ascii")
    ).hexdigest()


def test_orderbook_expands_every_level_and_marks_deletes() -> None:
    raw = _raw(
        {
            "topic": "orderbook.50.ETHUSDT",
            "type": "delta",
            "ts": 1_700_000_000_010,
            "cts": 1_700_000_000_009,
            "data": {
                "s": "ETHUSDT",
                "b": [["2000.0", "3.5"], ["1999.5", "0"]],
                "a": [["2000.5", "1.0"]],
                "u": 7,
                "seq": 9,
            },
        }
    )

    rows = normalize_bybit_event(raw)

    assert [(row.book_side, row.book_action, row.price, row.size) for row in rows] == [
        ("bid", "upsert", "2000.0", "3.5"),
        ("bid", "delete", "1999.5", "0"),
        ("ask", "upsert", "2000.5", "1.0"),
    ]
    assert all(row.event_ts_ms == 1_700_000_000_009 for row in rows)
    assert [row.row_index for row in rows] == [0, 1, 2]


def test_liquidation_and_ticker_messages_are_normalized() -> None:
    liquidation = _raw(
        {
            "topic": "allLiquidation.SOLUSDT",
            "type": "snapshot",
            "ts": 1_700_000_000_010,
            "data": [
                {
                    "T": 1_700_000_000_009,
                    "s": "SOLUSDT",
                    "S": "Sell",
                    "v": "20",
                    "p": "140.25",
                }
            ],
        }
    )
    ticker = _raw(
        {
            "topic": "tickers.SOLUSDT",
            "type": "delta",
            "ts": 1_700_000_000_011,
            "cs": 12,
            "data": {"symbol": "SOLUSDT", "markPrice": "140.2", "fundingRate": "0.0001"},
        },
        sequence=2,
    )

    (liq,) = normalize_bybit_event(liquidation)
    ticker_rows = normalize_bybit_event(ticker)

    assert (liq.record_type, liq.side, liq.price, liq.size) == (
        "liquidation",
        "sell",
        "140.25",
        "20",
    )
    assert [(row.metric_name, row.metric_value) for row in ticker_rows] == [
        ("fundingRate", "0.0001"),
        ("markPrice", "140.2"),
    ]


def test_stream_report_is_deterministic_and_counts_controls() -> None:
    trade = _raw(
        {
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 10,
            "data": [{"T": 9, "s": "BTCUSDT", "S": "Buy", "v": "1", "p": "2", "i": "t"}],
        },
        sequence=2,
    )
    control = _raw({"success": True, "op": "subscribe"}, sequence=1)

    rows_a, report_a = normalize_bybit_events([trade, control])
    rows_b, report_b = normalize_bybit_events([control, trade])

    assert rows_a == rows_b
    assert report_a == report_b
    assert report_a.raw_event_count == 2
    assert report_a.normalized_row_count == 1
    assert report_a.skipped_control_count == 1
    assert report_a.raw_channel_counts == {"control": 1, "trades": 1}


def test_bad_shapes_fail_closed() -> None:
    raw = _raw(
        {
            "topic": "publicTrade.BTCUSDT",
            "type": "snapshot",
            "ts": 10,
            "data": [{"T": 9, "s": "BTCUSDT", "S": "Sideways", "v": "1", "p": "2", "i": "t"}],
        }
    )

    with pytest.raises(NormalizationError, match="invalid side"):
        normalize_bybit_event(raw)
