from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.data.binance_adapter import parse_binance_message, synthesize_binance_depth_snapshot_event
from src.data.binance_normalized_event import (
    normalize_binance_event,
    normalize_binance_events,
)
from src.data.normalized_event import BINANCE_NORMALIZER_VERSION, NormalizationError
from src.data.normalized_store import AtomicNormalizedWriter, read_normalized_part


def _raw(message: dict, *, receive_sequence: int = 1):
    return parse_binance_message(
        json.dumps(message, separators=(",", ":")),
        receive_ts_ns=1_700_000_000_100_000_000 + receive_sequence,
        receive_sequence=receive_sequence,
        connection_id="binance-1",
    )


def test_binance_depth_preserves_update_range_and_exact_decimal_text() -> None:
    raw = _raw(
        {
            "e": "depthUpdate",
            "E": 1_700_000_000_010,
            "T": 1_700_000_000_009,
            "s": "BTCUSDT",
            "U": 101,
            "u": 104,
            "pu": 100,
            "b": [["20000.00", "1.2500"], ["19999.50", "0"]],
            "a": [["20000.50", "2.0"]],
        }
    )

    rows = normalize_binance_event(raw)

    assert [(row.book_side, row.book_action, row.price, row.size) for row in rows] == [
        ("bid", "upsert", "20000.00", "1.2500"),
        ("bid", "delete", "19999.50", "0"),
        ("ask", "upsert", "20000.50", "2.0"),
    ]
    assert all(row.first_update_id == 101 for row in rows)
    assert all(row.update_id == 104 for row in rows)
    assert all(row.previous_update_id == 100 for row in rows)
    assert all(row.event_ts_ms == 1_700_000_000_009 for row in rows)
    assert rows[0].normalized_id == hashlib.sha256(
        f"{BINANCE_NORMALIZER_VERSION}|{raw.event_id}|0".encode("ascii")
    ).hexdigest()


@pytest.mark.parametrize(
    ("buyer_is_maker", "expected_side"), [(True, "sell"), (False, "buy")]
)
def test_binance_trade_converts_maker_flag_to_aggressor_side(
    buyer_is_maker: bool, expected_side: str
) -> None:
    raw = _raw(
        {
            "e": "aggTrade",
            "E": 1_700_000_000_010,
            "s": "ETHUSDT",
            "a": 99,
            "p": "2000.500",
            "q": "0.2500",
            "T": 1_700_000_000_009,
            "m": buyer_is_maker,
        }
    )

    (row,) = normalize_binance_event(raw)

    assert row.side == expected_side
    assert row.trade_id == "99"
    assert row.price == "2000.500"
    assert row.size == "0.2500"


def test_binance_ticker_and_stream_report_are_deterministic() -> None:
    ticker = _raw(
        {
            "e": "markPriceUpdate",
            "E": 1_700_000_000_010,
            "s": "SOLUSDT",
            "p": "140.2",
            "i": "140.1",
            "r": "0.0001",
            "T": 1_700_000_100_000,
        },
        receive_sequence=2,
    )
    control = _raw({"result": None, "id": 1}, receive_sequence=1)

    rows_a, report_a = normalize_binance_events([ticker, control])
    rows_b, report_b = normalize_binance_events([control, ticker])

    assert rows_a == rows_b
    assert report_a == report_b
    assert report_a.skipped_control_count == 1
    assert [(row.metric_name, row.metric_value) for row in rows_a] == [
        ("i", "140.1"),
        ("p", "140.2"),
        ("r", "0.0001"),
    ]


def test_binance_silver_v2_round_trip_keeps_sequence_lineage(tmp_path: Path) -> None:
    raw = _raw(
        {
            "e": "depthUpdate",
            "E": 1_700_000_000_010,
            "T": 1_700_000_000_009,
            "s": "BTCUSDT",
            "U": 101,
            "u": 102,
            "pu": 100,
            "b": [["100", "1"]],
            "a": [["101", "2"]],
        }
    )
    rows = list(normalize_binance_event(raw))

    manifest = AtomicNormalizedWriter(tmp_path).write_source_part(
        rows,
        source_events_sha256="a" * 64,
        source_part_path="raw/binance.parquet",
        utc_date="2023-11-14",
    )

    assert manifest is not None
    assert manifest.normalizer_version == BINANCE_NORMALIZER_VERSION
    assert "exchange=binance" in manifest.part_path
    assert read_normalized_part(tmp_path, manifest) == rows


def test_binance_liquidation_is_normalized_from_the_nested_order_object() -> None:
    raw = _raw(
        {
            "e": "forceOrder",
            "E": 1_700_000_000_000,
            "o": {
                "s": "BTCUSDT",
                "S": "SELL",
                "o": "LIMIT",
                "f": "IOC",
                "q": "0.014",
                "p": "77000.00",
                "ap": "77000.00",
                "X": "FILLED",
                "l": "0.014",
                "z": "0.014",
                "T": 1_700_000_000_500,
            },
        }
    )

    rows = normalize_binance_event(raw)

    assert len(rows) == 1
    row = rows[0]
    assert row.record_type == "liquidation"
    assert row.channel == "liquidations"
    assert row.symbol == "BTCUSDT"
    assert row.side == "sell"
    assert row.price == "77000.00"
    assert row.size == "0.014"
    assert row.event_ts_ms == 1_700_000_000_500


def test_binance_liquidation_rejects_missing_order_object_or_invalid_side() -> None:
    missing_order = _raw({"e": "forceOrder", "E": 1})
    with pytest.raises(NormalizationError, match="order object"):
        normalize_binance_event(missing_order)

    bad_side = _raw(
        {
            "e": "forceOrder",
            "E": 1,
            "o": {"s": "BTCUSDT", "S": "SIDEWAYS", "p": "1", "q": "1", "T": 1},
        }
    )
    with pytest.raises(NormalizationError, match="invalid side"):
        normalize_binance_event(bad_side)


def test_binance_invalid_depth_or_trade_shapes_fail_closed() -> None:
    invalid_range = _raw(
        {
            "e": "depthUpdate",
            "E": 10,
            "T": 9,
            "s": "BTCUSDT",
            "U": 5,
            "u": 4,
            "pu": 3,
            "b": [],
            "a": [],
        }
    )
    with pytest.raises(NormalizationError, match="range"):
        normalize_binance_event(invalid_range)

    invalid_trade = _raw(
        {
            "e": "aggTrade",
            "E": 10,
            "s": "BTCUSDT",
            "a": 1,
            "p": "2",
            "q": "1",
            "T": 9,
            "m": "true",
        }
    )
    with pytest.raises(NormalizationError, match="boolean"):
        normalize_binance_event(invalid_trade)


def test_binance_synthesized_snapshot_event_produces_no_silver_rows() -> None:
    """Cycle 19: the REST-depth-snapshot Bronze event exists for post-hoc
    replay tooling, not Silver's book_level delta stream - see
    src/data/binance_normalized_event.py::normalize_binance_event's
    message_type == "snapshot" branch."""
    snapshot_event = synthesize_binance_depth_snapshot_event(
        "BTCUSDT",
        {"lastUpdateId": 500, "E": 1, "T": 1, "bids": [["100", "1"]], "asks": [["101", "1"]]},
        receive_ts_ns=1,
        connection_id="binance-1",
    )

    assert normalize_binance_event(snapshot_event) == ()


def test_binance_synthesized_snapshot_event_is_counted_as_skipped_in_the_report() -> None:
    snapshot_event = synthesize_binance_depth_snapshot_event(
        "BTCUSDT",
        {"lastUpdateId": 500, "E": 1, "T": 1, "bids": [], "asks": []},
        receive_ts_ns=1,
        connection_id="binance-1",
    )
    trade_event = _raw(
        {
            "e": "aggTrade",
            "E": 10,
            "s": "BTCUSDT",
            "a": 1,
            "p": "2",
            "q": "1",
            "T": 9,
            "m": True,
        },
        receive_sequence=2,
    )

    rows, report = normalize_binance_events([snapshot_event, trade_event])

    assert len(rows) == 1  # only the trade produced a Silver row
    assert report.skipped_control_count == 1
    assert report.raw_channel_counts["orderbook"] == 1
