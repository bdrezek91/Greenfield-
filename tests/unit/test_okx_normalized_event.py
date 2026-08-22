from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.data.normalized_event import OKX_NORMALIZER_VERSION, NormalizationError
from src.data.normalized_store import AtomicNormalizedWriter, read_normalized_part
from src.data.okx_adapter import parse_okx_message
from src.data.okx_normalized_event import normalize_okx_event, normalize_okx_events


def _raw(message: dict, *, receive_sequence: int = 1):
    return parse_okx_message(
        json.dumps(message, separators=(",", ":")),
        receive_ts_ns=1_700_000_000_100_000_000 + receive_sequence,
        receive_sequence=receive_sequence,
        connection_id="okx-1",
    )


def test_okx_books_preserve_sequence_lineage_and_exact_decimal_text() -> None:
    raw = _raw(
        {
            "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
            "action": "update",
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "ts": "1700000000010",
                    "seqId": 104,
                    "prevSeqId": 100,
                    "bids": [["20000.00", "1.2500", "0", "2"], ["19999.50", "0", "0", "0"]],
                    "asks": [["20000.50", "2.0", "0", "1"]],
                }
            ],
        }
    )

    rows = normalize_okx_event(raw)

    assert [(row.book_side, row.book_action, row.price, row.size) for row in rows] == [
        ("bid", "upsert", "20000.00", "1.2500"),
        ("bid", "delete", "19999.50", "0"),
        ("ask", "upsert", "20000.50", "2.0"),
    ]
    assert all(row.first_update_id == 104 for row in rows)
    assert all(row.update_id == 104 for row in rows)
    assert all(row.previous_update_id == 100 for row in rows)
    assert (
        rows[0].normalized_id
        == hashlib.sha256(f"{OKX_NORMALIZER_VERSION}|{raw.event_id}|0".encode("ascii")).hexdigest()
    )


def test_okx_trade_uses_documented_taker_side_and_exact_contract_size() -> None:
    raw = _raw(
        {
            "arg": {"channel": "trades", "instId": "ETH-USDT-SWAP"},
            "data": [
                {
                    "instId": "ETH-USDT-SWAP",
                    "tradeId": "99",
                    "px": "2000.500",
                    "sz": "3.0000",
                    "side": "buy",
                    "ts": "1700000000009",
                    "source": "0",
                }
            ],
        }
    )

    (row,) = normalize_okx_event(raw)

    assert row.side == "buy"
    assert row.trade_id == "99"
    assert row.price == "2000.500"
    assert row.size == "3.0000"


def test_okx_ticker_and_report_are_deterministic() -> None:
    ticker = _raw(
        {
            "arg": {"channel": "tickers", "instId": "SOL-USDT-SWAP"},
            "data": [
                {
                    "instId": "SOL-USDT-SWAP",
                    "last": "140.2",
                    "bidPx": "140.1",
                    "askPx": "140.3",
                    "ts": "1700000000010",
                }
            ],
        },
        receive_sequence=2,
    )
    control = _raw(
        {"event": "subscribe", "arg": {"channel": "tickers", "instId": "SOL-USDT-SWAP"}},
        receive_sequence=1,
    )

    rows_a, report_a = normalize_okx_events([ticker, control])
    rows_b, report_b = normalize_okx_events([control, ticker])

    assert rows_a == rows_b
    assert report_a == report_b
    assert report_a.skipped_control_count == 1
    assert [(row.metric_name, row.metric_value) for row in rows_a] == [
        ("askPx", "140.3"),
        ("bidPx", "140.1"),
        ("last", "140.2"),
    ]


def test_okx_silver_round_trip_retains_replay_lineage(tmp_path: Path) -> None:
    raw = _raw(
        {
            "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
            "action": "snapshot",
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "ts": "1700000000010",
                    "seqId": 10,
                    "prevSeqId": -1,
                    "bids": [["100", "1", "0", "1"]],
                    "asks": [["101", "2", "0", "1"]],
                }
            ],
        }
    )
    rows = list(normalize_okx_event(raw))

    manifest = AtomicNormalizedWriter(tmp_path).write_source_part(
        rows,
        source_events_sha256="a" * 64,
        source_part_path="raw/okx.parquet",
        utc_date="2023-11-14",
    )

    assert manifest is not None
    assert manifest.normalizer_version == OKX_NORMALIZER_VERSION
    assert "exchange=okx" in manifest.part_path
    assert read_normalized_part(tmp_path, manifest) == rows


def test_okx_invalid_message_type_instrument_or_trade_fails_closed() -> None:
    missing_action = _raw(
        {
            "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "ts": "10",
                    "seqId": 2,
                    "prevSeqId": 1,
                    "bids": [],
                    "asks": [],
                }
            ],
        }
    )
    with pytest.raises(NormalizationError, match="message type"):
        normalize_okx_event(missing_action)

    mismatch = _raw(
        {
            "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "instId": "ETH-USDT-SWAP",
                    "tradeId": "1",
                    "px": "2",
                    "sz": "1",
                    "side": "buy",
                    "ts": "9",
                }
            ],
        }
    )
    with pytest.raises(NormalizationError, match="instrument mismatch"):
        normalize_okx_event(mismatch)

    bad_side = _raw(
        {
            "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "tradeId": "1",
                    "px": "2",
                    "sz": "1",
                    "side": "maker",
                    "ts": "9",
                }
            ],
        }
    )
    with pytest.raises(NormalizationError, match="trade side"):
        normalize_okx_event(bad_side)
