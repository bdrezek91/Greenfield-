"""Production L2 Gold is warm-started, causal, and replay-stable."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from src.data.normalized_event import (
    NORMALIZED_EVENT_SCHEMA_VERSION,
    NORMALIZER_VERSION,
    NormalizedMarketEvent,
)
from src.data.normalized_store import AtomicNormalizedWriter
from src.features.l2_materialization import (
    L2GoldMaterializationError,
    materialize_daily_l2_microstructure,
    write_l2_gold_report,
)
from src.features.store import FeaturePartManifest, verify_feature_part

DAY = pd.Timestamp("2024-01-02T00:00:00Z")


def _level(
    *,
    raw: str,
    receive_ns: int,
    update_id: int,
    row_index: int,
    message_type: str,
    side: str,
    price: str,
    size: str,
    connection: str = "c1",
) -> NormalizedMarketEvent:
    raw_id = hashlib.sha256(raw.encode()).hexdigest()
    normalized_id = hashlib.sha256(f"{raw_id}:{row_index}".encode()).hexdigest()
    return NormalizedMarketEvent(
        schema_version=NORMALIZED_EVENT_SCHEMA_VERSION,
        normalizer_version=NORMALIZER_VERSION,
        normalized_id=normalized_id,
        raw_event_id=raw_id,
        raw_payload_sha256=hashlib.sha256(f"payload:{raw}".encode()).hexdigest(),
        exchange="bybit",
        market_type="linear",
        channel="orderbook",
        record_type="book_level",
        symbol="BTCUSDT",
        event_ts_ms=receive_ns // 1_000_000,
        receive_ts_ns=receive_ns,
        receive_sequence=update_id,
        connection_id=connection,
        message_type=message_type,
        sequence=update_id * 10,
        update_id=update_id,
        row_index=row_index,
        book_side=side,
        book_action="delete" if size == "0" else "upsert",
        price=price,
        size=size,
    )


def _write(root: Path, rows: list[NormalizedMarketEvent], utc_date: str, marker: str) -> None:
    AtomicNormalizedWriter(root).write_source_part(
        rows,
        source_events_sha256=hashlib.sha256(marker.encode()).hexdigest(),
        source_part_path=f"bronze/{marker}.parquet",
        utc_date=utc_date,
    )


def _lake(root: Path) -> None:
    before = int(DAY.value) - 1_000_000_000
    _write(
        root,
        [
            _level(
                raw="snapshot",
                receive_ns=before,
                update_id=10,
                row_index=0,
                message_type="snapshot",
                side="bid",
                price="100",
                size="3",
            ),
            _level(
                raw="snapshot",
                receive_ns=before,
                update_id=10,
                row_index=1,
                message_type="snapshot",
                side="ask",
                price="101",
                size="2",
            ),
        ],
        "2024-01-01",
        "previous",
    )
    _write(
        root,
        [
            _level(
                raw="delta-1",
                receive_ns=int(DAY.value) + 10_000_000_000,
                update_id=11,
                row_index=0,
                message_type="delta",
                side="bid",
                price="100",
                size="1",
            ),
            _level(
                raw="delta-2",
                receive_ns=int(DAY.value) + 70_000_000_000,
                update_id=12,
                row_index=0,
                message_type="delta",
                side="bid",
                price="100",
                size="2",
            ),
        ],
        "2024-01-02",
        "target",
    )


def test_l2_gold_uses_pre_day_snapshot_and_writes_two_causal_minutes(tmp_path: Path) -> None:
    _lake(tmp_path)
    report = materialize_daily_l2_microstructure(
        tmp_path,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        utc_date="2024-01-02",
        as_of=pd.Timestamp("2024-01-03T00:00:00Z"),
        code_version="test-commit",
        depth_levels=1,
    )
    path = write_l2_gold_report(tmp_path, report)

    assert report.qualified is True
    assert report.source_part_count == 2
    assert report.gold_row_count == 2
    assert path.is_file()
    manifest = FeaturePartManifest.from_json(
        (tmp_path / report.gold_manifests[0]).read_text(encoding="utf-8")
    )
    verify_feature_part(tmp_path, manifest)
    frame = pd.read_parquet(tmp_path / manifest.part_path)
    assert frame["bid_cancelled"].tolist() == [2.0, 0.0]
    assert frame["bid_replenished"].tolist() == [0.0, 1.0]
    assert (frame["max_source_timestamp"] <= frame["timestamp"]).all()

    repeated = materialize_daily_l2_microstructure(
        tmp_path,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        utc_date="2024-01-02",
        as_of=pd.Timestamp("2024-01-03T00:00:00Z"),
        code_version="test-commit",
        depth_levels=1,
    )
    assert repeated.dataset_version == report.dataset_version
    assert repeated.gold_manifests == report.gold_manifests


def test_l2_gold_merges_reconnect_split_manifests_by_causal_order(tmp_path: Path) -> None:
    # A single connection's Silver rows can land in manifests whose
    # (min_receive_ts_ns, part_path) sort order does not match true
    # receive-time order once two manifests' ranges overlap - the same
    # root cause already fixed for src.data.raw_store.iter_raw_events and
    # src.features.materialization's trade builder
    # (src.data.ordered_merge). Before this L2 builder adopted the same
    # connection-aware merge, naive whole-manifest concatenation processed
    # this shape as update_id 11, 13, 12 - failing closed on a spurious
    # "L2 update gap or regression"/"L2 stream is not strictly ordered"
    # even though the underlying data is perfectly causal (11, then 12,
    # then 13).
    before = int(DAY.value) - 1_000_000_000
    _write(
        tmp_path,
        [
            _level(
                raw="snapshot",
                receive_ns=before,
                update_id=10,
                row_index=0,
                message_type="snapshot",
                side="bid",
                price="100",
                size="3",
            ),
            _level(
                raw="snapshot",
                receive_ns=before,
                update_id=10,
                row_index=1,
                message_type="snapshot",
                side="ask",
                price="101",
                size="2",
            ),
        ],
        "2024-01-01",
        "previous",
    )
    day_start = int(DAY.value)
    # This manifest's own range [100ms, 600ms] overlaps the next manifest's
    # single point (300ms) even though both are the same connection -
    # min_receive_ts_ns-sorted whole-manifest concatenation would emit
    # update_id 11, then 13 (this manifest, in file order), then 12 (the
    # next manifest) instead of the true causal 11, 12, 13.
    _write(
        tmp_path,
        [
            _level(
                raw="delta-11",
                receive_ns=day_start + 100_000_000,
                update_id=11,
                row_index=0,
                message_type="delta",
                side="bid",
                price="100",
                size="2",
            ),
            _level(
                raw="delta-13",
                receive_ns=day_start + 600_000_000,
                update_id=13,
                row_index=0,
                message_type="delta",
                side="bid",
                price="100",
                size="1",
            ),
        ],
        "2024-01-02",
        "tail-a",
    )
    _write(
        tmp_path,
        [
            _level(
                raw="delta-12",
                receive_ns=day_start + 300_000_000,
                update_id=12,
                row_index=0,
                message_type="delta",
                side="ask",
                price="101",
                size="1",
            ),
        ],
        "2024-01-02",
        "tail-b",
    )

    report = materialize_daily_l2_microstructure(
        tmp_path,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        utc_date="2024-01-02",
        as_of=pd.Timestamp("2024-01-03T00:00:00Z"),
        code_version="test-commit",
        depth_levels=1,
    )

    assert report.qualified is True
    assert report.source_part_count == 3

    manifest = FeaturePartManifest.from_json(
        (tmp_path / report.gold_manifests[0]).read_text(encoding="utf-8")
    )
    verify_feature_part(tmp_path, manifest)
    frame = pd.read_parquet(tmp_path / manifest.part_path)
    # The warmup snapshot precedes the target day and is excluded from the
    # bucket; all three target-day deltas land in one minute bucket and
    # must each be counted exactly once, in the correct causal order - not
    # lost, not duplicated, not rejected as out of order.
    assert frame["book_updates"].tolist() == [3]
    assert frame["spread_mean"].tolist() == [1.0]

    repeated = materialize_daily_l2_microstructure(
        tmp_path,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        utc_date="2024-01-02",
        as_of=pd.Timestamp("2024-01-03T00:00:00Z"),
        code_version="test-commit",
        depth_levels=1,
    )
    assert repeated.dataset_version == report.dataset_version


def test_l2_gold_fails_without_pre_day_snapshot(tmp_path: Path) -> None:
    row = _level(
        raw="delta",
        receive_ns=int(DAY.value) + 10_000_000_000,
        update_id=11,
        row_index=0,
        message_type="delta",
        side="bid",
        price="100",
        size="1",
    )
    _write(tmp_path, [row], "2024-01-02", "target")
    with pytest.raises(L2GoldMaterializationError, match="snapshot"):
        materialize_daily_l2_microstructure(
            tmp_path,
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            utc_date="2024-01-02",
            as_of=pd.Timestamp("2024-01-03T00:00:00Z"),
            code_version="test-commit",
        )
