"""Production, fail-closed Silver-to-Gold microstructure materialization."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.data.data_quality import assess_normalized_part
from src.data.normalized_event import NormalizedMarketEvent
from src.data.normalized_store import (
    NormalizedPartManifest,
    discover_normalized_manifests,
    read_normalized_part,
)
from src.features.auction import footprint_frame, volume_profile
from src.features.order_flow import trade_flow_frame
from src.features.store import FeaturePartManifest, FeatureStore

_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")


class GoldMaterializationError(RuntimeError):
    """A production Gold build lacks closed, verified, causal Silver input."""


@dataclass(frozen=True, slots=True)
class GoldMaterializationReport:
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
    gold_row_count: int
    gold_manifests: tuple[str, ...]
    feature_sets: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def materialize_daily_trade_microstructure(
    data_dir: Path,
    *,
    exchange: str,
    market_type: str,
    symbol: str,
    utc_date: str,
    as_of: pd.Timestamp,
    code_version: str,
    price_tick: str,
    bucket_ms: int = 60_000,
    imbalance_ratio: float = 3.0,
) -> GoldMaterializationReport:
    """Build daily CVD/trade-flow and ATAS-like footprint Gold partitions.

    A UTC day is eligible only after it has closed. Every selected Silver
    part is verified and independently quality-checked at ``as_of``. The
    immutable dataset identity includes exact source content hashes and build
    parameters; no raw or Silver input is mutated.
    """
    root = Path(data_dir)
    cutoff = _utc_timestamp(as_of)
    day = _parse_date(utc_date)
    if cutoff < pd.Timestamp(day + timedelta(days=1), tz="UTC"):
        raise GoldMaterializationError("UTC partition is not closed at as_of")
    for value in (exchange, market_type, symbol, code_version):
        if not _SAFE.fullmatch(value):
            raise GoldMaterializationError(f"unsafe materialization identity: {value!r}")
    if bucket_ms <= 0:
        raise GoldMaterializationError("bucket_ms must be positive")

    manifests = discover_normalized_manifests(
        root,
        exchange=exchange,
        market_type=market_type,
        channel="trades",
        symbol=symbol,
        utc_date=utc_date,
    )
    if not manifests:
        raise GoldMaterializationError("no Silver trade parts found for closed UTC date")

    rows: list[NormalizedMarketEvent] = []
    for manifest in manifests:
        quality = assess_normalized_part(root, manifest, observed_at=cutoff)
        if not quality.qualified:
            failed = ",".join(check.name for check in quality.checks if not check.passed)
            raise GoldMaterializationError(
                f"Silver part failed quality gate: {manifest.part_path}: {failed}"
            )
        rows.extend(read_normalized_part(root, manifest))

    cutoff_ns = int(cutoff.timestamp() * 1_000_000_000)
    eligible = [
        row
        for row in rows
        if row.record_type == "trade"
        and row.receive_ts_ns <= cutoff_ns
        and pd.Timestamp(row.event_ts_ms, unit="ms", tz="UTC").strftime("%Y-%m-%d")
        == utc_date
    ]
    eligible.sort(
        key=lambda row: (
            row.event_ts_ms,
            row.receive_ts_ns,
            row.receive_sequence,
            row.row_index,
            row.normalized_id,
        )
    )
    ids = [row.normalized_id for row in eligible]
    if not eligible:
        raise GoldMaterializationError("closed Silver partition contains no eligible trades")
    if len(ids) != len(set(ids)):
        raise GoldMaterializationError("duplicate normalized trade IDs across Silver parts")

    dataset_version, parts_sha256, eligible_ids_sha256 = _dataset_identity(
        manifests=manifests,
        eligible_ids=ids,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        utc_date=utc_date,
    )
    trade = trade_flow_frame(eligible, symbol=symbol, bucket_ms=bucket_ms)
    footprint = footprint_frame(
        eligible,
        symbol=symbol,
        bucket_ms=bucket_ms,
        price_tick=price_tick,
        imbalance_ratio=imbalance_ratio,
    )
    auction = _auction_summary(footprint, imbalance_ratio=imbalance_ratio)
    if trade.empty or auction.empty:
        raise GoldMaterializationError("feature builders emitted no Gold rows")

    store = FeatureStore(root)
    output: list[FeaturePartManifest] = []
    output.extend(
        store.write(
            trade,
            feature_set=f"trade-flow-{bucket_ms}ms-v1",
            symbol=symbol,
            dataset_version=dataset_version,
            code_version=code_version,
        )
    )
    output.extend(
        store.write(
            auction,
            feature_set=f"footprint-auction-{bucket_ms}ms-v1",
            symbol=symbol,
            dataset_version=dataset_version,
            code_version=code_version,
        )
    )
    return GoldMaterializationReport(
        schema_version=1,
        qualified=True,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        utc_date=utc_date,
        as_of_utc=cutoff.isoformat(),
        code_version=code_version,
        dataset_version=dataset_version,
        source_part_count=len(manifests),
        source_row_count=len(eligible),
        source_parts_sha256=parts_sha256,
        eligible_ids_sha256=eligible_ids_sha256,
        gold_row_count=sum(item.row_count for item in output),
        gold_manifests=tuple(item.manifest_path for item in output),
        feature_sets=tuple(sorted({item.feature_set for item in output})),
    )


def write_gold_materialization_report(
    data_dir: Path, report: GoldMaterializationReport
) -> Path:
    identity = hashlib.sha256(
        json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    path = (
        Path(data_dir)
        / "reports"
        / "gold-materialization"
        / "v1"
        / f"{report.utc_date}-{report.exchange}-{report.symbol}-{identity[:16]}.json"
    )
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != value:
            raise GoldMaterializationError(f"immutable report collision: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _auction_summary(footprint: pd.DataFrame, *, imbalance_ratio: float) -> pd.DataFrame:
    output: list[dict[str, object]] = []
    for _, bucket in footprint.groupby("bucket_start_ms", sort=True):
        profile = volume_profile(bucket)
        output.append(
            {
                "timestamp": bucket["timestamp"].max(),
                "max_source_timestamp": bucket["max_source_timestamp"].max(),
                "footprint_total_volume": float(bucket["total_volume"].sum()),
                "footprint_delta": float(bucket["delta"].sum()),
                "buy_imbalance_levels": int(
                    (bucket["diagonal_buy_ratio"] >= imbalance_ratio).sum()
                ),
                "sell_imbalance_levels": int(
                    (bucket["diagonal_sell_ratio"] >= imbalance_ratio).sum()
                ),
                "max_stacked_buy_levels": int(bucket["stacked_buy_levels"].max()),
                "max_stacked_sell_levels": int(bucket["stacked_sell_levels"].max()),
                "poc": profile.poc,
                "vah": profile.vah,
                "val": profile.val,
                "value_area_fraction": profile.value_area_fraction,
            }
        )
    return pd.DataFrame(output)


def _dataset_identity(
    *,
    manifests: list[NormalizedPartManifest],
    eligible_ids: list[str],
    exchange: str,
    market_type: str,
    symbol: str,
    utc_date: str,
) -> tuple[str, str, str]:
    parts = [
        {
            "part_path": manifest.part_path,
            "content_sha256": manifest.content_sha256,
            "normalized_ids_sha256": manifest.normalized_ids_sha256,
        }
        for manifest in manifests
    ]
    parts.sort(key=lambda item: item["part_path"])
    parts_encoded = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    parts_sha256 = hashlib.sha256(parts_encoded.encode("utf-8")).hexdigest()
    eligible_ids_sha256 = hashlib.sha256("\n".join(eligible_ids).encode("ascii")).hexdigest()
    identity = {
        "schema_version": 1,
        "layer": "silver",
        "exchange": exchange,
        "market_type": market_type,
        "channel": "trades",
        "symbol": symbol,
        "utc_date": utc_date,
        "parts_sha256": parts_sha256,
        "eligible_ids_sha256": eligible_ids_sha256,
    }
    dataset_version = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return dataset_version, parts_sha256, eligible_ids_sha256


def _parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise GoldMaterializationError("utc_date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise GoldMaterializationError("utc_date must be canonical YYYY-MM-DD")
    return parsed


def _utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise GoldMaterializationError("as_of must be timezone-aware")
    return result.tz_convert("UTC")
