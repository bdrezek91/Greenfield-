"""Closed-day, connection-safe Silver L2 to minute Gold materialization."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import cast

import pandas as pd

from src.data.data_quality import assess_normalized_part
from src.data.normalized_event import NormalizedMarketEvent
from src.data.normalized_store import (
    NormalizedPartManifest,
    discover_normalized_manifests,
    read_normalized_part,
)
from src.features.interaction import BookLiquidityAccumulator
from src.features.order_flow import L2ImbalanceAccumulator
from src.features.store import FeatureStore

_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


class L2GoldMaterializationError(RuntimeError):
    """L2 input cannot establish complete, causal state for the requested day."""


@dataclass(frozen=True, slots=True)
class L2GoldMaterializationReport:
    schema_version: int
    qualified: bool
    exchange: str
    market_type: str
    symbol: str
    utc_date: str
    as_of_utc: str
    code_version: str
    dataset_version: str
    source_part_count: int
    source_row_count: int
    source_parts_sha256: str
    eligible_ids_sha256: str
    warmup_snapshot_receive_ts_ns: int
    gold_row_count: int
    gold_manifests: tuple[str, ...]
    feature_set: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def materialize_daily_l2_microstructure(
    data_dir: Path,
    *,
    exchange: str,
    market_type: str,
    symbol: str,
    utc_date: str,
    as_of: pd.Timestamp,
    code_version: str,
    bucket_ms: int = 60_000,
    depth_levels: int = 5,
    replenishment_window_updates: int = 5,
) -> L2GoldMaterializationReport:
    """Replay from the last pre-day snapshot and write receive-time causal Gold."""
    for value in (exchange, market_type, symbol, code_version):
        if not _SAFE.fullmatch(value):
            raise L2GoldMaterializationError(f"unsafe L2 identity: {value!r}")
    if bucket_ms <= 0 or depth_levels <= 0 or replenishment_window_updates <= 0:
        raise L2GoldMaterializationError("L2 materialization parameters must be positive")
    day = _parse_date(utc_date)
    start = pd.Timestamp(day, tz="UTC")
    end = pd.Timestamp(day + timedelta(days=1), tz="UTC")
    cutoff = _utc_timestamp(as_of)
    if cutoff < end:
        raise L2GoldMaterializationError("UTC partition is not closed at as_of")
    start_ns, end_ns = int(start.value), int(end.value)

    manifests = discover_normalized_manifests(
        Path(data_dir),
        exchange=exchange,
        market_type=market_type,
        channel="orderbook",
        symbol=symbol,
    )
    manifests = sorted(
        (item for item in manifests if item.utc_date <= utc_date),
        key=lambda item: (item.min_receive_ts_ns, item.part_path),
    )
    snapshot_index, snapshot_id, snapshot_receive_ns = _find_warmup_snapshot(
        Path(data_dir), manifests, start_ns=start_ns
    )
    selected = manifests[snapshot_index:]
    if not selected:
        raise L2GoldMaterializationError("no L2 Silver parts follow warmup snapshot")

    ids = hashlib.sha256()
    seen: set[str] = set()
    first = True
    row_count = 0
    target_rows = 0
    started = False
    for manifest in selected:
        quality = assess_normalized_part(Path(data_dir), manifest, observed_at=cutoff)
        if not quality.qualified:
            raise L2GoldMaterializationError(
                f"Silver L2 part failed quality gate: {manifest.part_path}"
            )
        rows, started = _selected_rows(
            read_normalized_part(Path(data_dir), manifest),
            snapshot_id=snapshot_id,
            end_ns=end_ns,
            started=started,
        )
        for row in rows:
            if row.normalized_id in seen:
                raise L2GoldMaterializationError("duplicate normalized L2 IDs")
            seen.add(row.normalized_id)
            if not first:
                ids.update(b"\n")
            ids.update(row.normalized_id.encode("ascii"))
            first = False
            row_count += 1
            target_rows += row.receive_ts_ns >= start_ns
    if not started or target_rows == 0:
        raise L2GoldMaterializationError("warmup snapshot or target-day L2 rows are missing")

    dataset_version, parts_sha = _dataset_identity(
        selected,
        eligible_ids_sha256=ids.hexdigest(),
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        utc_date=utc_date,
        bucket_ms=bucket_ms,
        depth_levels=depth_levels,
        replenishment_window_updates=replenishment_window_updates,
    )
    seen.clear()
    book = L2ImbalanceAccumulator(symbol, depth_levels=depth_levels)
    liquidity = BookLiquidityAccumulator(
        symbol, replenishment_window_updates=replenishment_window_updates
    )
    buckets = _L2MinuteBuckets(bucket_ms=bucket_ms, start_ns=start_ns, end_ns=end_ns)
    started = False
    for manifest in selected:
        rows, started = _selected_rows(
            read_normalized_part(Path(data_dir), manifest),
            snapshot_id=snapshot_id,
            end_ns=end_ns,
            started=started,
        )
        _consume_pairs(buckets, book.update(rows), liquidity.update(rows))
    _consume_pairs(buckets, book.finalize(), liquidity.finalize())
    frame = pd.DataFrame(buckets.finalize())
    if frame.empty:
        raise L2GoldMaterializationError("L2 feature builder emitted no target-day rows")
    feature_set = f"l2-liquidity-{bucket_ms}ms-v1"
    output = FeatureStore(Path(data_dir)).write(
        frame,
        feature_set=feature_set,
        symbol=symbol,
        dataset_version=dataset_version,
        code_version=code_version,
    )
    return L2GoldMaterializationReport(
        schema_version=1,
        qualified=True,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        utc_date=utc_date,
        as_of_utc=cutoff.isoformat(),
        code_version=code_version,
        dataset_version=dataset_version,
        source_part_count=len(selected),
        source_row_count=row_count,
        source_parts_sha256=parts_sha,
        eligible_ids_sha256=ids.hexdigest(),
        warmup_snapshot_receive_ts_ns=snapshot_receive_ns,
        gold_row_count=sum(item.row_count for item in output),
        gold_manifests=tuple(item.manifest_path for item in output),
        feature_set=feature_set,
    )


def write_l2_gold_report(data_dir: Path, report: L2GoldMaterializationReport) -> Path:
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    identity = hashlib.sha256(value.encode()).hexdigest()
    path = (
        Path(data_dir)
        / "reports"
        / "l2-gold-materialization"
        / "v1"
        / f"{report.utc_date}-{report.exchange}-{report.symbol}-{identity[:16]}.json"
    )
    if path.exists():
        if path.read_text(encoding="utf-8") != value:
            raise L2GoldMaterializationError(f"immutable report collision: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


class _L2MinuteBuckets:
    def __init__(self, *, bucket_ms: int, start_ns: int, end_ns: int) -> None:
        self.bucket_ns = bucket_ms * 1_000_000
        self.start_ns, self.end_ns = start_ns, end_ns
        self.current: int | None = None
        self.rows: list[dict[str, object]] = []
        self.output: list[dict[str, object]] = []

    def add(self, row: dict[str, object]) -> None:
        source_ns = int(pd.Timestamp(row["max_source_timestamp"]).value)
        if source_ns < self.start_ns:
            return
        if source_ns >= self.end_ns:
            raise L2GoldMaterializationError("post-day L2 row entered target aggregation")
        bucket = source_ns // self.bucket_ns * self.bucket_ns
        if self.current is not None and bucket != self.current:
            if bucket < self.current:
                raise L2GoldMaterializationError("L2 receive bucket regressed")
            self._emit()
        if self.current is None:
            self.current = bucket
        self.rows.append(row)

    def finalize(self) -> list[dict[str, object]]:
        if self.rows:
            self._emit()
        return self.output

    def _emit(self) -> None:
        assert self.current is not None and self.rows
        frame = pd.DataFrame(self.rows)
        mid = frame["mid_price"].astype(float)
        micro = frame["microprice"].astype(float)
        cancel_total = float(frame["bid_cancelled"].sum() + frame["ask_cancelled"].sum())
        replenished = float(frame["bid_replenished"].sum() + frame["ask_replenished"].sum())
        denominator = cancel_total or 1.0
        result: dict[str, object] = {
            "timestamp": pd.Timestamp(self.current + self.bucket_ns, unit="ns", tz="UTC"),
            "max_source_timestamp": frame["max_source_timestamp"].max(),
            "book_updates": len(frame),
            "spread_mean": float(frame["spread"].mean()),
            "spread_p95": float(frame["spread"].quantile(0.95)),
            "mid_price_last": float(mid.iloc[-1]),
            "microprice_last": float(micro.iloc[-1]),
            "microprice_offset_bps_mean": float(((micro - mid) / mid * 10_000).mean()),
            "bid_depth_mean": float(frame["bid_depth"].mean()),
            "ask_depth_mean": float(frame["ask_depth"].mean()),
            "bid_depth_min": float(frame["bid_depth"].min()),
            "ask_depth_min": float(frame["ask_depth"].min()),
            "book_imbalance_mean": float(frame["book_imbalance"].mean()),
            "book_imbalance_std": float(frame["book_imbalance"].std(ddof=0)),
            "book_imbalance_last": float(frame["book_imbalance"].iloc[-1]),
            "bid_added": float(frame["bid_added"].sum()),
            "ask_added": float(frame["ask_added"].sum()),
            "bid_cancelled": float(frame["bid_cancelled"].sum()),
            "ask_cancelled": float(frame["ask_cancelled"].sum()),
            "bid_replenished": float(frame["bid_replenished"].sum()),
            "ask_replenished": float(frame["ask_replenished"].sum()),
            "cancel_imbalance": float(
                (frame["ask_cancelled"].sum() - frame["bid_cancelled"].sum()) / denominator
            ),
            "replenishment_fraction": replenished / denominator,
        }
        if any(
            not math.isfinite(float(cast(float | int, value)))
            for key, value in result.items()
            if key not in {"timestamp", "max_source_timestamp"}
        ):
            raise L2GoldMaterializationError("non-finite L2 aggregate")
        self.output.append(result)
        self.current, self.rows = None, []


def _consume_pairs(
    buckets: _L2MinuteBuckets,
    book_rows: list[dict[str, object]],
    liquidity_rows: list[dict[str, object]],
) -> None:
    if len(book_rows) != len(liquidity_rows):
        raise L2GoldMaterializationError("L2 feature accumulators emitted different counts")
    for book, liquidity in zip(book_rows, liquidity_rows, strict=True):
        if (
            book["book_update_id"] != liquidity["book_update_id"]
            or book["max_source_timestamp"] != liquidity["max_source_timestamp"]
        ):
            raise L2GoldMaterializationError("L2 feature accumulators lost alignment")
        buckets.add({**book, **liquidity})


def _find_warmup_snapshot(
    data_dir: Path, manifests: list[NormalizedPartManifest], *, start_ns: int
) -> tuple[int, str, int]:
    for index in range(len(manifests) - 1, -1, -1):
        rows = read_normalized_part(data_dir, manifests[index])
        for row in reversed(rows):
            if row.receive_ts_ns <= start_ns and row.message_type == "snapshot":
                return index, row.raw_event_id, row.receive_ts_ns
    raise L2GoldMaterializationError("no L2 snapshot exists at or before target day")


def _selected_rows(
    rows: list[NormalizedMarketEvent],
    *,
    snapshot_id: str,
    end_ns: int,
    started: bool,
) -> tuple[list[NormalizedMarketEvent], bool]:
    output = []
    for row in rows:
        if not started and row.raw_event_id == snapshot_id:
            started = True
        if started and row.receive_ts_ns < end_ns:
            output.append(row)
    return output, started


def _dataset_identity(
    manifests: list[NormalizedPartManifest],
    *,
    eligible_ids_sha256: str,
    exchange: str,
    market_type: str,
    symbol: str,
    utc_date: str,
    bucket_ms: int,
    depth_levels: int,
    replenishment_window_updates: int,
) -> tuple[str, str]:
    parts = sorted(
        (
            item.part_path,
            item.content_sha256,
            item.normalized_ids_sha256,
        )
        for item in manifests
    )
    parts_sha = hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()
    identity = {
        "schema_version": 1,
        "layer": "silver-l2",
        "exchange": exchange,
        "market_type": market_type,
        "symbol": symbol,
        "utc_date": utc_date,
        "parts_sha256": parts_sha,
        "eligible_ids_sha256": eligible_ids_sha256,
        "bucket_ms": bucket_ms,
        "depth_levels": depth_levels,
        "replenishment_window_updates": replenishment_window_updates,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest(), parts_sha


def _parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise L2GoldMaterializationError("utc_date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise L2GoldMaterializationError("utc_date must be canonical YYYY-MM-DD")
    return parsed


def _utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise L2GoldMaterializationError("as_of must be timezone-aware")
    return result.tz_convert("UTC")
