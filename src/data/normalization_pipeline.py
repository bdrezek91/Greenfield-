"""Verified Bronze-to-Silver lake normalization pipeline."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from src.data.binance_normalized_event import normalize_binance_events
from src.data.coinbase_normalized_event import normalize_coinbase_events
from src.data.deribit_normalized_event import normalize_deribit_events
from src.data.normalized_event import normalize_bybit_events
from src.data.normalized_store import AtomicNormalizedWriter
from src.data.okx_normalized_event import normalize_okx_events
from src.data.raw_store import discover_manifests, read_raw_part, verify_raw_part


@dataclass(frozen=True, slots=True)
class NormalizationLakeReport:
    exchange: str
    market_type: str
    source_part_count: int
    source_raw_event_count: int
    normalized_part_count: int
    normalized_row_count: int
    skipped_control_count: int
    raw_channel_counts: dict[str, int]
    normalized_record_counts: dict[str, int]
    source_parts_sha256: str
    normalized_parts_sha256: str
    normalized_parts: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_raw_lake(
    source_data_dir: Path,
    output_data_dir: Path,
    *,
    exchange: str = "bybit",
    market_type: str = "linear",
    symbol: str | None = None,
    channel: str | None = None,
    utc_date: str | None = None,
    minimum_free_bytes: int = 0,
) -> NormalizationLakeReport:
    """Verify every selected Bronze part and materialize idempotent Silver parts."""
    if minimum_free_bytes < 0:
        raise ValueError("minimum_free_bytes must be non-negative")
    if minimum_free_bytes:
        Path(output_data_dir).mkdir(parents=True, exist_ok=True)
        _require_free_space(output_data_dir, minimum_free_bytes)
    normalizers = {
        "bybit": normalize_bybit_events,
        "binance": normalize_binance_events,
        "coinbase": normalize_coinbase_events,
        "deribit": normalize_deribit_events,
        "okx": normalize_okx_events,
    }
    try:
        normalize_events = normalizers[exchange]
    except KeyError as exc:
        raise ValueError(f"no registered normalizer for exchange: {exchange!r}") from exc
    manifests = discover_manifests(
        source_data_dir,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        channel=channel,
        utc_date=utc_date,
    )
    writer = AtomicNormalizedWriter(output_data_dir)
    source_raw_event_count = 0
    normalized_row_count = 0
    skipped_control_count = 0
    raw_channel_counts: dict[str, int] = {}
    normalized_record_counts: dict[str, int] = {}
    output_manifests = []

    for manifest in manifests:
        _require_free_space(output_data_dir, minimum_free_bytes)
        verify_raw_part(source_data_dir, manifest)
        events = read_raw_part(source_data_dir, manifest)
        rows, report = normalize_events(events)
        source_raw_event_count += report.raw_event_count
        normalized_row_count += report.normalized_row_count
        skipped_control_count += report.skipped_control_count
        _merge_counts(raw_channel_counts, report.raw_channel_counts)
        _merge_counts(normalized_record_counts, report.normalized_record_counts)
        _require_free_space(output_data_dir, minimum_free_bytes)
        output = writer.write_source_part(
            rows,
            source_events_sha256=manifest.events_sha256,
            source_part_path=manifest.part_path,
            utc_date=manifest.utc_date,
        )
        if output is not None:
            output_manifests.append(output)

    output_manifests.sort(key=lambda item: item.part_path)
    return NormalizationLakeReport(
        exchange=exchange,
        market_type=market_type,
        source_part_count=len(manifests),
        source_raw_event_count=source_raw_event_count,
        normalized_part_count=len(output_manifests),
        normalized_row_count=normalized_row_count,
        skipped_control_count=skipped_control_count,
        raw_channel_counts=dict(sorted(raw_channel_counts.items())),
        normalized_record_counts=dict(sorted(normalized_record_counts.items())),
        source_parts_sha256=_text_checksum(
            [f"{item.part_path}|{item.events_sha256}" for item in manifests]
        ),
        normalized_parts_sha256=_text_checksum(
            [f"{item.part_path}|{item.normalized_ids_sha256}" for item in output_manifests]
        ),
        normalized_parts=tuple(item.part_path for item in output_manifests),
    )


def _require_free_space(data_dir: Path, minimum_free_bytes: int) -> None:
    # Recheck during the run: live collectors share the destination filesystem.
    # Operators must leave headroom above the hard floor for an in-flight part.
    if minimum_free_bytes and shutil.disk_usage(data_dir).free <= minimum_free_bytes:
        raise RuntimeError("Silver normalization stopped at free-space reserve")


def _merge_counts(target: dict[str, int], values: dict[str, int]) -> None:
    for name, count in values.items():
        target[name] = target.get(name, 0) + count


def _text_checksum(values: list[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()
