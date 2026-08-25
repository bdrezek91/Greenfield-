"""The lake pipeline verifies Bronze and idempotently materializes Silver."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data.binance_adapter import parse_binance_message
from src.data.coinbase_adapter import parse_coinbase_message
from src.data.deribit_adapter import parse_deribit_message
from src.data.normalization_pipeline import normalize_raw_lake
from src.data.okx_adapter import parse_okx_message
from src.data.raw_event import parse_bybit_message
from src.data.raw_store import AtomicRawWriter


def _event(message: dict, sequence: int):
    return parse_bybit_message(
        json.dumps(message, separators=(",", ":")),
        receive_ts_ns=1_700_000_000_000_000_000 + sequence,
        receive_sequence=sequence,
        connection_id="c",
    )


def test_pipeline_is_idempotent_and_reports_lineage(tmp_path: Path) -> None:
    source = tmp_path / "bronze"
    output = tmp_path / "silver"
    events = [
        _event({"success": True, "op": "subscribe"}, 1),
        _event(
            {
                "topic": "publicTrade.BTCUSDT",
                "type": "snapshot",
                "ts": 1_700_000_000_002,
                "data": [
                    {
                        "T": 1_700_000_000_001,
                        "s": "BTCUSDT",
                        "S": "Buy",
                        "v": "1",
                        "p": "2",
                        "i": "trade-1",
                    }
                ],
            },
            2,
        ),
    ]
    AtomicRawWriter(source).write(events)

    first = normalize_raw_lake(source, output)
    second = normalize_raw_lake(source, output)

    assert first == second
    assert first.source_part_count == 2
    assert first.source_raw_event_count == 2
    assert first.normalized_part_count == 1
    assert first.normalized_row_count == 1
    assert first.skipped_control_count == 1
    assert first.raw_channel_counts == {"control": 1, "trades": 1}
    assert first.normalized_record_counts == {"trade": 1}
    assert len(first.normalized_parts) == 1


def test_pipeline_filters_symbol(tmp_path: Path) -> None:
    source = tmp_path / "bronze"
    output = tmp_path / "silver"
    AtomicRawWriter(source).write(
        [
            _event(
                {
                    "topic": f"publicTrade.{symbol}",
                    "type": "snapshot",
                    "ts": 1_700_000_000_002,
                    "data": [
                        {
                            "T": 1_700_000_000_001,
                            "s": symbol,
                            "S": "Buy",
                            "v": "1",
                            "p": "2",
                            "i": symbol,
                        }
                    ],
                },
                index,
            )
            for index, symbol in enumerate(("BTCUSDT", "ETHUSDT"), start=1)
        ]
    )

    report = normalize_raw_lake(source, output, symbol="ETHUSDT")

    assert report.source_raw_event_count == 1
    assert report.normalized_row_count == 1
    assert "symbol=ETHUSDT" in report.normalized_parts[0]


def test_pipeline_filters_exact_utc_date_before_reading_parts(tmp_path: Path) -> None:
    source = tmp_path / "bronze"
    output = tmp_path / "silver"
    events = []
    for sequence, day in enumerate(("2023-11-14", "2023-11-15"), start=1):
        timestamp_ms = int(pd.Timestamp(f"{day}T12:00:00Z").timestamp() * 1000)
        events.append(
            parse_bybit_message(
                json.dumps(
                    {
                        "topic": "publicTrade.BTCUSDT",
                        "type": "snapshot",
                        "ts": timestamp_ms,
                        "data": [
                            {
                                "T": timestamp_ms,
                                "s": "BTCUSDT",
                                "S": "Buy",
                                "v": "1",
                                "p": "2",
                                "i": f"trade-{sequence}",
                            }
                        ],
                    },
                    separators=(",", ":"),
                ),
                receive_ts_ns=timestamp_ms * 1_000_000,
                receive_sequence=sequence,
                connection_id="c",
            )
        )
    AtomicRawWriter(source).write(events)

    report = normalize_raw_lake(source, output, utc_date="2023-11-15")

    assert report.source_part_count == 1
    assert report.source_raw_event_count == 1
    assert report.normalized_row_count == 1
    assert "date=2023-11-15" in report.normalized_parts[0]


def test_pipeline_dispatches_binance_normalizer_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "bronze"
    output = tmp_path / "silver"
    event = parse_binance_message(
        json.dumps(
            {
                "e": "aggTrade",
                "E": 1_700_000_000_002,
                "s": "BTCUSDT",
                "a": 1,
                "p": "2.00",
                "q": "1.50",
                "T": 1_700_000_000_001,
                "m": False,
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=1_700_000_000_003_000_000,
        connection_id="binance-c",
    )
    AtomicRawWriter(source).write([event])

    first = normalize_raw_lake(source, output, exchange="binance")
    second = normalize_raw_lake(source, output, exchange="binance")

    assert first == second
    assert first.exchange == "binance"
    assert first.market_type == "linear"
    assert first.normalized_row_count == 1
    assert "exchange=binance" in first.normalized_parts[0]


def test_pipeline_dispatches_okx_normalizer_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "bronze"
    output = tmp_path / "silver"
    event = parse_okx_message(
        json.dumps(
            {
                "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "tradeId": "1",
                        "px": "2.00",
                        "sz": "1.50",
                        "side": "buy",
                        "ts": "1700000000001",
                    }
                ],
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=1_700_000_000_003_000_000,
        connection_id="okx-c",
    )
    AtomicRawWriter(source).write([event])

    first = normalize_raw_lake(source, output, exchange="okx", market_type="swap")
    second = normalize_raw_lake(source, output, exchange="okx", market_type="swap")

    assert first == second
    assert first.exchange == "okx"
    assert first.market_type == "swap"
    assert first.normalized_row_count == 1
    assert "exchange=okx" in first.normalized_parts[0]


def test_pipeline_dispatches_coinbase_normalizer(tmp_path: Path) -> None:
    source = tmp_path / "bronze"
    output = tmp_path / "silver"
    event = parse_coinbase_message(
        json.dumps(
            {
                "channel": "market_trades",
                "timestamp": "2023-02-09T20:19:35Z",
                "sequence_num": 1,
                "events": [
                    {
                        "type": "update",
                        "trades": [
                            {
                                "trade_id": "1",
                                "product_id": "BTC-USD",
                                "price": "2.00",
                                "size": "1.50",
                                "side": "SELL",
                                "time": "2023-02-09T20:19:34Z",
                            }
                        ],
                    }
                ],
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=1_700_000_000_003_000_000,
        connection_id="coinbase-c",
    )
    AtomicRawWriter(source).write([event])

    report = normalize_raw_lake(source, output, exchange="coinbase", market_type="spot")

    assert report.exchange == "coinbase"
    assert report.market_type == "spot"
    assert report.normalized_row_count == 1
    assert "exchange=coinbase" in report.normalized_parts[0]


def test_pipeline_dispatches_deribit_option_normalizer(tmp_path: Path) -> None:
    source = tmp_path / "bronze"
    output = tmp_path / "silver"
    event = parse_deribit_message(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "subscription",
                "params": {
                    "channel": "ticker.BTC-30DEC26-100000-C.100ms",
                    "data": {
                        "timestamp": 1_700_000_000_001,
                        "instrument_name": "BTC-30DEC26-100000-C",
                        "mark_iv": 52.0,
                        "greeks": {"delta": 0.42},
                    },
                },
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=1_700_000_000_003_000_000,
        connection_id="deribit-c",
    )
    AtomicRawWriter(source).write([event])

    report = normalize_raw_lake(source, output, exchange="deribit", market_type="option")

    assert report.exchange == "deribit"
    assert report.market_type == "option"
    assert report.normalized_row_count == 2
    assert "exchange=deribit" in report.normalized_parts[0]


def test_pipeline_rejects_exchange_without_registered_normalizer(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no registered normalizer"):
        normalize_raw_lake(tmp_path, tmp_path, exchange="unknown")
