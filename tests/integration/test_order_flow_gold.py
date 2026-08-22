"""Normalized trade flow can be persisted through the causal Gold contract."""

from __future__ import annotations

import json
from pathlib import Path

from src.data.normalized_event import normalize_bybit_event
from src.data.raw_event import parse_bybit_message
from src.features.order_flow import trade_flow_frame
from src.features.store import FeatureStore, verify_feature_part


def test_trade_tape_to_gold_feature_part(tmp_path: Path) -> None:
    raw = parse_bybit_message(
        json.dumps(
            {
                "topic": "publicTrade.BTCUSDT",
                "type": "snapshot",
                "ts": 1_700_000_060_100,
                "data": [
                    {
                        "T": 1_700_000_000_100,
                        "s": "BTCUSDT",
                        "S": "Buy",
                        "v": "2",
                        "p": "100",
                        "i": "a",
                    },
                    {
                        "T": 1_700_000_000_200,
                        "s": "BTCUSDT",
                        "S": "Sell",
                        "v": "1",
                        "p": "101",
                        "i": "b",
                    },
                ],
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=1_700_000_000_300_000_000,
        receive_sequence=1,
        connection_id="c",
    )
    frame = trade_flow_frame(
        list(normalize_bybit_event(raw)), symbol="BTCUSDT", bucket_ms=60_000
    )

    manifest = FeatureStore(tmp_path).write(
        frame,
        feature_set="trade-flow-v1",
        symbol="BTCUSDT",
        dataset_version="a" * 64,
        code_version="commit-atas-1",
    )[0]

    assert manifest.row_count == 1
    assert "trade_delta" in manifest.feature_columns
    assert "cvd" in manifest.feature_columns
    assert manifest.max_source_ts_ns <= manifest.max_feature_ts_ns
    verify_feature_part(tmp_path, manifest)
