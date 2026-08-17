"""parse_long_short_ratio_rows must map Bybit's raw field names to the
canonical schema, dedupe, and sort chronologically."""

from __future__ import annotations

from src.data.ingest_long_short_ratio import parse_long_short_ratio_rows


def test_parse_empty_rows_returns_empty_frame() -> None:
    df = parse_long_short_ratio_rows([], "BTCUSDT")
    assert df.empty
    assert list(df.columns) == ["timestamp", "symbol", "buy_ratio", "sell_ratio"]


def test_parse_maps_fields_and_sorts() -> None:
    rows = [
        {"buyRatio": "0.6", "sellRatio": "0.4", "timestamp": "1700000600000"},
        {"buyRatio": "0.5", "sellRatio": "0.5", "timestamp": "1700000000000"},
    ]
    df = parse_long_short_ratio_rows(rows, "BTCUSDT")
    assert list(df["buy_ratio"]) == [0.5, 0.6]
    assert (df["symbol"] == "BTCUSDT").all()
    assert df["timestamp"].dt.tz is not None


def test_parse_dedupes_identical_timestamps() -> None:
    rows = [
        {"buyRatio": "0.6", "sellRatio": "0.4", "timestamp": "1700000000000"},
        {"buyRatio": "0.6", "sellRatio": "0.4", "timestamp": "1700000000000"},
    ]
    df = parse_long_short_ratio_rows(rows, "BTCUSDT")
    assert len(df) == 1
