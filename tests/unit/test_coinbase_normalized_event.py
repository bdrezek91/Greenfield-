from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.data.coinbase_adapter import parse_coinbase_message
from src.data.coinbase_normalized_event import (
    normalize_coinbase_event,
    normalize_coinbase_events,
)
from src.data.normalized_event import COINBASE_NORMALIZER_VERSION, NormalizationError
from src.data.normalized_store import AtomicNormalizedWriter, read_normalized_part


def _raw(message: dict, *, receive_sequence: int = 1):
    return parse_coinbase_message(
        json.dumps(message, separators=(",", ":")),
        receive_ts_ns=1_700_000_000_100_000_000 + receive_sequence,
        receive_sequence=receive_sequence,
        connection_id="coinbase-1",
    )


def test_coinbase_l2_preserves_exact_values_and_snapshot_availability_time() -> None:
    raw = _raw(
        {
            "channel": "l2_data",
            "timestamp": "2023-02-09T20:32:50.714Z",
            "sequence_num": 10,
            "events": [
                {
                    "type": "snapshot",
                    "product_id": "BTC-USD",
                    "updates": [
                        {
                            "side": "bid",
                            "event_time": "1970-01-01T00:00:00Z",
                            "price_level": "100.00",
                            "new_quantity": "1.2500",
                        },
                        {
                            "side": "offer",
                            "event_time": "1970-01-01T00:00:00Z",
                            "price_level": "101.00",
                            "new_quantity": "0",
                        },
                    ],
                }
            ],
        }
    )

    rows = normalize_coinbase_event(raw)

    assert [(row.book_side, row.book_action, row.price, row.size) for row in rows] == [
        ("bid", "upsert", "100.00", "1.2500"),
        ("ask", "delete", "101.00", "0"),
    ]
    assert all(row.event_ts_ms == raw.exchange_ts_ms for row in rows)
    assert all(row.first_update_id == 10 for row in rows)
    assert (
        rows[0].normalized_id
        == hashlib.sha256(
            f"{COINBASE_NORMALIZER_VERSION}|{raw.event_id}|0".encode("ascii")
        ).hexdigest()
    )


def test_coinbase_trade_converts_documented_maker_side_to_aggressor_side() -> None:
    raw = _raw(
        {
            "channel": "market_trades",
            "timestamp": "2023-02-09T20:19:35Z",
            "sequence_num": 11,
            "events": [
                {
                    "type": "update",
                    "trades": [
                        {
                            "trade_id": "99",
                            "product_id": "ETH-USD",
                            "price": "2000.500",
                            "size": "0.2500",
                            "side": "BUY",
                            "time": "2023-02-09T20:19:34.900Z",
                        }
                    ],
                }
            ],
        }
    )

    (row,) = normalize_coinbase_event(raw)

    assert row.side == "sell"
    assert row.trade_id == "99"
    assert row.price == "2000.500"
    assert row.size == "0.2500"


def test_coinbase_ticker_report_and_silver_round_trip_are_deterministic(tmp_path: Path) -> None:
    ticker = _raw(
        {
            "channel": "ticker",
            "timestamp": "2023-02-09T20:19:35Z",
            "sequence_num": 12,
            "events": [
                {
                    "type": "update",
                    "tickers": [
                        {
                            "product_id": "SOL-USD",
                            "price": "140.2",
                            "best_bid": "140.1",
                            "best_ask": "140.3",
                        }
                    ],
                }
            ],
        },
        receive_sequence=2,
    )
    control = _raw(
        {
            "channel": "heartbeats",
            "timestamp": "2023-02-09T20:19:34Z",
            "sequence_num": 1,
            "events": [],
        },
        receive_sequence=1,
    )

    rows_a, report_a = normalize_coinbase_events([ticker, control])
    rows_b, report_b = normalize_coinbase_events([control, ticker])

    assert rows_a == rows_b
    assert report_a == report_b
    assert report_a.skipped_control_count == 1
    assert [(row.metric_name, row.metric_value) for row in rows_a] == [
        ("best_ask", "140.3"),
        ("best_bid", "140.1"),
        ("price", "140.2"),
    ]
    manifest = AtomicNormalizedWriter(tmp_path).write_source_part(
        rows_a,
        source_events_sha256="a" * 64,
        source_part_path="raw/coinbase.parquet",
        utc_date="2023-02-09",
    )
    assert manifest is not None
    assert manifest.normalizer_version == COINBASE_NORMALIZER_VERSION
    assert read_normalized_part(tmp_path, manifest) == rows_a


def test_coinbase_ambiguous_product_or_bad_side_fails_closed() -> None:
    ambiguous = _raw(
        {
            "channel": "market_trades",
            "timestamp": "2023-02-09T20:19:35Z",
            "sequence_num": 1,
            "events": [
                {"type": "update", "trades": [{"product_id": "BTC-USD"}, {"product_id": "ETH-USD"}]}
            ],
        }
    )
    with pytest.raises(NormalizationError, match="resolve one product"):
        normalize_coinbase_event(ambiguous)

    bad_side = _raw(
        {
            "channel": "market_trades",
            "timestamp": "2023-02-09T20:19:35Z",
            "sequence_num": 2,
            "events": [
                {
                    "type": "update",
                    "trades": [
                        {
                            "trade_id": "1",
                            "product_id": "BTC-USD",
                            "price": "2",
                            "size": "1",
                            "side": "TAKER",
                            "time": "2023-02-09T20:19:34Z",
                        }
                    ],
                }
            ],
        }
    )
    with pytest.raises(NormalizationError, match="maker side"):
        normalize_coinbase_event(bad_side)
