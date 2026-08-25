"""Closed, verified Silver trade days materialize reproducible Gold."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data.normalized_event import normalize_bybit_event
from src.data.normalized_store import AtomicNormalizedWriter
from src.data.raw_event import parse_bybit_message
from src.features.materialization import (
    GoldMaterializationError,
    materialize_daily_trade_microstructure,
    write_gold_materialization_report,
)
from src.features.store import FeaturePartManifest, verify_feature_part


def _silver_day(root: Path) -> None:
    rows = []
    for sequence, (timestamp, side, price, size) in enumerate(
        (
            (1_700_006_400_100, "Buy", "100.0", "2"),
            (1_700_006_400_200, "Sell", "100.1", "1"),
            (1_700_006_460_100, "Buy", "100.2", "3"),
        ),
        start=1,
    ):
        raw = parse_bybit_message(
            json.dumps(
                {
                    "topic": "publicTrade.BTCUSDT",
                    "type": "snapshot",
                    "ts": timestamp + 10,
                    "data": [
                        {
                            "T": timestamp,
                            "s": "BTCUSDT",
                            "S": side,
                            "v": size,
                            "p": price,
                            "i": f"trade-{sequence}",
                        }
                    ],
                },
                separators=(",", ":"),
            ),
            receive_ts_ns=(timestamp + 20) * 1_000_000,
            receive_sequence=sequence,
            connection_id="connection",
        )
        rows.extend(normalize_bybit_event(raw))
    manifest = AtomicNormalizedWriter(root).write_source_part(
        rows,
        source_events_sha256="a" * 64,
        source_part_path="raw/source.parquet",
        utc_date="2023-11-15",
    )
    assert manifest is not None


def _build(root: Path):
    return materialize_daily_trade_microstructure(
        root,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        utc_date="2023-11-15",
        as_of=pd.Timestamp("2023-11-16T00:00:00Z"),
        code_version="commit-1",
        price_tick="0.1",
        bucket_ms=60_000,
    )


def test_closed_verified_silver_materializes_two_gold_feature_sets(tmp_path: Path) -> None:
    _silver_day(tmp_path)

    report = _build(tmp_path)
    report_path = write_gold_materialization_report(tmp_path, report)

    assert report.qualified is True
    assert report.source_part_count == 1
    assert report.source_row_count == 3
    assert report.gold_row_count == 4
    assert report.feature_sets == (
        "footprint-auction-60000ms-v1",
        "trade-flow-60000ms-v1",
    )
    assert report_path.is_file()
    assert write_gold_materialization_report(tmp_path, report) == report_path
    for relative in report.gold_manifests:
        manifest = FeaturePartManifest.from_json(
            Path(tmp_path, relative).read_text(encoding="utf-8")
        )
        verify_feature_part(tmp_path, manifest)


def test_materialization_is_idempotent(tmp_path: Path) -> None:
    _silver_day(tmp_path)
    first = _build(tmp_path)
    second = _build(tmp_path)

    assert first == second
    assert first.gold_manifests == second.gold_manifests
    later = materialize_daily_trade_microstructure(
        tmp_path,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        utc_date="2023-11-15",
        as_of=pd.Timestamp("2023-11-17T00:00:00Z"),
        code_version="commit-1",
        price_tick="0.1",
    )
    assert later.dataset_version == first.dataset_version
    assert later.eligible_ids_sha256 == first.eligible_ids_sha256


def test_open_day_and_corrupt_silver_fail_closed(tmp_path: Path) -> None:
    _silver_day(tmp_path)
    with pytest.raises(GoldMaterializationError, match="not closed"):
        materialize_daily_trade_microstructure(
            tmp_path,
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            utc_date="2023-11-15",
            as_of=pd.Timestamp("2023-11-15T23:59:59Z"),
            code_version="commit-1",
            price_tick="0.1",
        )

    part = next(tmp_path.rglob("*.parquet"))
    part.write_bytes(b"corrupt")
    with pytest.raises(GoldMaterializationError, match="quality gate"):
        _build(tmp_path)
