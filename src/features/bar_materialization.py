"""Fail-closed historical OHLCV to Market-Cipher-like Gold materialization."""

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

from src.data.config import TIMEFRAME_MS
from src.data.point_in_time import select_closed_klines
from src.data.schema import COLUMNS, assert_schema
from src.data.validate import validate_dataset
from src.features.momentum_flow import momentum_money_flow_frame
from src.features.store import FeatureStore

_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")
_VENUE_PREFIX = {"bybit": "klines", "binance": "binance_klines", "okx": "okx_klines"}


class BarGoldMaterializationError(RuntimeError):
    """Historical bar input cannot support a causal, reproducible Gold build."""


@dataclass(frozen=True, slots=True)
class BarGoldMaterializationReport:
    schema_version: int
    qualified: bool
    venue: str
    source_symbol: str
    symbol: str
    timeframe: str
    utc_date: str
    as_of_utc: str
    code_version: str
    dataset_version: str
    source_part_count: int
    source_row_count: int
    source_parts_sha256: str
    eligible_rows_sha256: str
    gold_row_count: int
    gold_manifests: tuple[str, ...]
    feature_set: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def materialize_daily_momentum_flow(
    data_dir: Path,
    *,
    venue: str,
    source_symbol: str,
    symbol: str,
    timeframe: str,
    utc_date: str,
    as_of: pd.Timestamp,
    code_version: str,
    warmup_rows: int = 256,
) -> BarGoldMaterializationReport:
    """Build one closed UTC availability day of original MC-like features."""
    for value in (venue, source_symbol, symbol, timeframe, code_version):
        if not _SAFE.fullmatch(value):
            raise BarGoldMaterializationError(f"unsafe bar materialization identity: {value!r}")
    if venue not in _VENUE_PREFIX:
        raise BarGoldMaterializationError(f"unsupported venue: {venue!r}")
    if timeframe not in TIMEFRAME_MS:
        raise BarGoldMaterializationError(f"unsupported timeframe: {timeframe!r}")
    if warmup_rows < 64:
        raise BarGoldMaterializationError("warmup_rows must be at least 64")

    day = _parse_date(utc_date)
    cutoff = _utc_timestamp(as_of)
    day_start = pd.Timestamp(day, tz="UTC")
    day_end = pd.Timestamp(day + timedelta(days=1), tz="UTC")
    if cutoff < day_end:
        raise BarGoldMaterializationError("UTC availability partition is not closed at as_of")

    root = Path(data_dir)
    partition_root = root / _VENUE_PREFIX[venue] / source_symbol / timeframe
    paths, loaded = _bounded_history(
        partition_root,
        day_start=day_start,
        day_end=day_end,
        warmup_rows=warmup_rows,
    )
    if loaded.empty:
        raise BarGoldMaterializationError("no historical bars found for closed UTC date")
    assert_schema(loaded)
    if set(loaded["symbol"].astype(str)) != {source_symbol}:
        raise BarGoldMaterializationError("historical partition contains an unexpected symbol")
    if set(loaded["timeframe"].astype(str)) != {timeframe}:
        raise BarGoldMaterializationError("historical partition contains an unexpected timeframe")

    loaded = loaded.sort_values("timestamp").reset_index(drop=True)
    eligible, _ = select_closed_klines(loaded, timeframe=timeframe, as_of=cutoff)
    target = eligible[(eligible["timestamp"] >= day_start) & (eligible["timestamp"] < day_end)]
    if target.empty:
        raise BarGoldMaterializationError("closed UTC date contains no eligible bars")
    context = eligible[eligible["timestamp"] < day_start].tail(warmup_rows)
    duration = pd.Timedelta(milliseconds=TIMEFRAME_MS[timeframe])
    if (
        len(context) < warmup_rows
        or target["timestamp"].min() != day_start
        or target["timestamp"].max() + duration != day_end
    ):
        raise BarGoldMaterializationError("historical bars do not cover the complete build window")
    selected = pd.concat([context, target], ignore_index=True)
    quality = validate_dataset(selected, timeframe, now=cutoff)
    if not quality.is_valid:
        raise BarGoldMaterializationError("historical bars failed integrity validation")

    feature_input = selected.copy()
    feature_input["timestamp"] = feature_input["timestamp"] + duration
    feature_input["max_source_timestamp"] = feature_input["timestamp"]
    features = momentum_money_flow_frame(feature_input)
    features = features[
        (features["timestamp"] > day_start) & (features["timestamp"] <= day_end)
    ].reset_index(drop=True)
    if features.empty:
        raise BarGoldMaterializationError("momentum/money-flow warmup emitted no Gold rows")

    rows_sha = _frame_sha256(selected)
    parts_sha = _parts_sha256(paths)
    dataset_version = _dataset_version(
        venue=venue,
        source_symbol=source_symbol,
        symbol=symbol,
        timeframe=timeframe,
        utc_date=utc_date,
        eligible_rows_sha256=rows_sha,
    )
    feature_set = f"momentum-money-flow-{venue}-{timeframe}-v1"
    manifests = FeatureStore(root).write(
        features,
        feature_set=feature_set,
        symbol=symbol,
        dataset_version=dataset_version,
        code_version=code_version,
    )
    return BarGoldMaterializationReport(
        schema_version=1,
        qualified=True,
        venue=venue,
        source_symbol=source_symbol,
        symbol=symbol,
        timeframe=timeframe,
        utc_date=utc_date,
        as_of_utc=cutoff.isoformat(),
        code_version=code_version,
        dataset_version=dataset_version,
        source_part_count=len(paths),
        source_row_count=len(selected),
        source_parts_sha256=parts_sha,
        eligible_rows_sha256=rows_sha,
        gold_row_count=sum(item.row_count for item in manifests),
        gold_manifests=tuple(item.manifest_path for item in manifests),
        feature_set=feature_set,
    )


def write_bar_gold_report(data_dir: Path, report: BarGoldMaterializationReport) -> Path:
    encoded = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
    identity = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    path = (
        Path(data_dir)
        / "reports"
        / "bar-gold-materialization"
        / "v1"
        / (
            f"{report.utc_date}-{report.venue}-{report.symbol}-"
            f"{report.timeframe}-{identity[:16]}.json"
        )
    )
    value = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != value:
            raise BarGoldMaterializationError(f"immutable report collision: {path}")
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


def _bounded_history(
    root: Path,
    *,
    day_start: pd.Timestamp,
    day_end: pd.Timestamp,
    warmup_rows: int,
) -> tuple[list[Path], pd.DataFrame]:
    candidates = [
        path
        for path in sorted(root.glob("*.parquet"), reverse=True)
        if path.stem <= day_start.strftime("%Y-%m")
    ]
    selected_paths: list[Path] = []
    frames: list[pd.DataFrame] = []
    prior_rows = 0
    target_found = False
    for path in candidates:
        try:
            frame = pd.read_parquet(path, columns=list(COLUMNS))
        except (OSError, ValueError) as exc:
            raise BarGoldMaterializationError(f"unreadable historical partition: {path}") from exc
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
        bounded = frame[frame["timestamp"] < day_end]
        if bounded.empty:
            continue
        selected_paths.append(path)
        frames.append(bounded)
        prior_rows += int((bounded["timestamp"] < day_start).sum())
        target_found = target_found or bool(
            ((bounded["timestamp"] >= day_start) & (bounded["timestamp"] < day_end)).any()
        )
        if target_found and prior_rows >= warmup_rows:
            break
    if not frames:
        return [], pd.DataFrame(columns=COLUMNS)
    selected_paths.reverse()
    frames.reverse()
    return selected_paths, pd.concat(frames, ignore_index=True)


def _parts_sha256(paths: list[Path]) -> str:
    records = []
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        records.append({"path": path.name, "content_sha256": digest.hexdigest()})
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _frame_sha256(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    ordered = frame.sort_values("timestamp")
    for row in ordered.itertuples(index=False):
        values: list[object] = []
        for name, value in zip(ordered.columns, row, strict=True):
            if name == "timestamp":
                values.append(int(pd.Timestamp(value).value))
            elif name in {"symbol", "timeframe"}:
                values.append(str(value))
            else:
                values.append(float(value))
        digest.update(json.dumps(values, separators=(",", ":"), allow_nan=False).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _dataset_version(
    *,
    venue: str,
    source_symbol: str,
    symbol: str,
    timeframe: str,
    utc_date: str,
    eligible_rows_sha256: str,
) -> str:
    value = {
        "schema_version": 1,
        "layer": "historical_ohlcv",
        "venue": venue,
        "source_symbol": source_symbol,
        "symbol": symbol,
        "timeframe": timeframe,
        "utc_date": utc_date,
        "eligible_rows_sha256": eligible_rows_sha256,
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _parse_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise BarGoldMaterializationError("utc_date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise BarGoldMaterializationError("utc_date must be canonical YYYY-MM-DD")
    return parsed


def _utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise BarGoldMaterializationError("as_of must be timezone-aware")
    return result.tz_convert("UTC")
