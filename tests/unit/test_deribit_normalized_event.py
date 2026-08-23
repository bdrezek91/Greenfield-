from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.data.deribit_adapter import parse_deribit_message
from src.data.deribit_normalized_event import (
    normalize_deribit_event,
    normalize_deribit_events,
)
from src.data.normalized_event import DERIBIT_NORMALIZER_VERSION, NormalizationError
from src.data.normalized_store import AtomicNormalizedWriter, read_normalized_part


def _raw(channel: str, data: object, *, sequence: int = 1, market_type: str = "option"):
    return parse_deribit_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "subscription",
                "params": {"channel": channel, "data": data},
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=1_700_000_000_100_000_000 + sequence,
        receive_sequence=sequence,
        connection_id="deribit-1",
        market_type=market_type,
    )


def test_deribit_book_preserves_actions_exact_values_and_sequence_lineage() -> None:
    raw = _raw(
        "book.BTC-30DEC26-100000-C.100ms",
        {
            "type": "change",
            "timestamp": 1_700_000_000_010,
            "instrument_name": "BTC-30DEC26-100000-C",
            "change_id": 104,
            "prev_change_id": 100,
            "bids": [["change", 0.0500, 1.2500], ["delete", 0.0495, 0]],
            "asks": [["new", 0.051, 2]],
        },
    )

    rows = normalize_deribit_event(raw)

    assert [(row.book_side, row.book_action, row.price, row.size) for row in rows] == [
        ("bid", "upsert", "0.05", "1.25"),
        ("bid", "delete", "0.0495", "0"),
        ("ask", "upsert", "0.051", "2"),
    ]
    assert all(row.first_update_id == 104 for row in rows)
    assert all(row.previous_update_id == 100 for row in rows)
    assert (
        rows[0].normalized_id
        == hashlib.sha256(
            f"{DERIBIT_NORMALIZER_VERSION}|{raw.event_id}|0".encode("ascii")
        ).hexdigest()
    )


def test_deribit_trade_retains_taker_direction_and_trade_sequence() -> None:
    raw = _raw(
        "trades.BTC-PERPETUAL.100ms",
        [
            {
                "trade_seq": 30289442,
                "trade_id": "48079269",
                "timestamp": 1_590_484_512_188,
                "tick_direction": 2,
                "price": 8950,
                "instrument_name": "BTC-PERPETUAL",
                "direction": "sell",
                "amount": 10,
                "iv": 50.25,
            }
        ],
        market_type="perpetual",
    )

    (row,) = normalize_deribit_event(raw)

    assert row.side == "sell"
    assert row.trade_id == "48079269"
    assert row.tick_direction == "2"
    assert row.first_update_id == 30_289_442
    assert row.price == "8950"
    assert row.size == "10"
    assert raw.payload()["params"]["data"][0]["iv"] == 50.25


def test_deribit_option_ticker_retains_iv_greeks_and_underlying_metrics() -> None:
    raw = _raw(
        "ticker.BTC-30DEC26-100000-C.100ms",
        {
            "timestamp": 1_700_000_000_010,
            "instrument_name": "BTC-30DEC26-100000-C",
            "bid_iv": 51.25,
            "ask_iv": 52.75,
            "mark_iv": 52.0,
            "underlying_price": 100500.5,
            "open_interest": 123.4,
            "greeks": {"delta": 0.42, "gamma": 0.00001, "vega": 12.5},
        },
    )

    rows = normalize_deribit_event(raw)
    metrics = {row.metric_name: row.metric_value for row in rows}

    assert metrics["bid_iv"] == "51.25"
    assert metrics["ask_iv"] == "52.75"
    assert metrics["mark_iv"] == "52.0"
    assert metrics["underlying_price"] == "100500.5"
    assert metrics["open_interest"] == "123.4"
    assert metrics["greeks"] == '{"delta":"0.42","gamma":"0.00001","vega":"12.5"}'


def test_deribit_report_and_silver_round_trip_are_deterministic(tmp_path: Path) -> None:
    ticker = _raw(
        "ticker.ETH-30DEC26-5000-P.100ms",
        {
            "timestamp": 1_700_000_000_010,
            "instrument_name": "ETH-30DEC26-5000-P",
            "mark_iv": 60.0,
        },
        sequence=2,
    )
    control = parse_deribit_message(
        '{"jsonrpc":"2.0","id":42,"result":[]}',
        receive_ts_ns=1_700_000_000_100_000_001,
        receive_sequence=1,
        connection_id="deribit-1",
    )

    rows_a, report_a = normalize_deribit_events([ticker, control])
    rows_b, report_b = normalize_deribit_events([control, ticker])

    assert rows_a == rows_b
    assert report_a == report_b
    assert report_a.skipped_control_count == 1
    manifest = AtomicNormalizedWriter(tmp_path).write_source_part(
        rows_a,
        source_events_sha256="a" * 64,
        source_part_path="raw/deribit.parquet",
        utc_date="2026-12-30",
    )
    assert manifest is not None
    assert manifest.normalizer_version == DERIBIT_NORMALIZER_VERSION
    assert read_normalized_part(tmp_path, manifest) == rows_a


def test_deribit_bad_delete_or_instrument_mismatch_fails_closed() -> None:
    bad_delete = _raw(
        "book.BTC-PERPETUAL.100ms",
        {
            "type": "snapshot",
            "timestamp": 10,
            "instrument_name": "BTC-PERPETUAL",
            "change_id": 1,
            "bids": [["delete", 100, 1]],
            "asks": [],
        },
        market_type="perpetual",
    )
    with pytest.raises(NormalizationError, match="zero size"):
        normalize_deribit_event(bad_delete)

    mismatch = _raw(
        "ticker.BTC-PERPETUAL.100ms",
        {"timestamp": 10, "instrument_name": "ETH-PERPETUAL", "mark_price": 1},
        market_type="perpetual",
    )
    with pytest.raises(NormalizationError, match="instrument mismatch"):
        normalize_deribit_event(mismatch)
