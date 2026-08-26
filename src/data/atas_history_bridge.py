"""Validated, immutable landing zone for exports produced by the ATAS probe.

ATAS remains an external data source.  Its exports are never relabelled as
native exchange Bronze and never used to fill native-collector gaps silently.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

ATAS_EXPORT_SCHEMA_VERSION = 1
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


class AtasHistoryExportError(ValueError):
    """An ATAS export is malformed, incomplete, or violates provenance rules."""


@dataclass(frozen=True, slots=True)
class AtasHistoryManifest:
    schema_version: int
    source: str
    connector: str
    instrument: str
    requested_from_utc: str
    requested_to_utc: str
    exported_at_utc: str
    cumulative_trade_count: int
    market_depth_snapshot_count: int
    export_sha256: str
    export_size_bytes: int
    relative_export_path: str


def ingest_atas_history_export(
    export_path: Path,
    data_dir: Path,
    *,
    expected_sha256: str | None = None,
) -> AtasHistoryManifest:
    """Validate and content-address one JSONL export under Bronze/source=atas."""

    digest = _sha256(export_path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise AtasHistoryExportError("ATAS export SHA-256 does not match")
    header: dict[str, object] | None = None
    footer: dict[str, object] | None = None
    cumulative_trade_count = 0
    depth_count = 0
    first_timestamp: datetime | None = None
    previous_timestamp: datetime | None = None
    with export_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise AtasHistoryExportError(f"blank JSONL record at line {line_number}")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AtasHistoryExportError(
                    f"invalid JSON at line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(record, dict):
                raise AtasHistoryExportError(f"record at line {line_number} is not an object")
            record_type = record.get("record_type")
            if footer is not None:
                raise AtasHistoryExportError("records follow the ATAS export footer")
            if record_type == "header":
                if header is not None or line_number != 1:
                    raise AtasHistoryExportError("ATAS export has a misplaced/duplicate header")
                header = record
                continue
            if header is None:
                raise AtasHistoryExportError("ATAS export must start with a header")
            if record_type == "cumulative_trade":
                timestamp = _validate_trade(record, line_number)
                cumulative_trade_count += 1
            elif record_type == "market_depth_snapshot":
                timestamp = _validate_depth(record, line_number)
                depth_count += 1
            elif record_type == "footer":
                footer = record
                continue
            else:
                raise AtasHistoryExportError(
                    f"unsupported record_type at line {line_number}: {record_type!r}"
                )
            if previous_timestamp is not None and timestamp < previous_timestamp:
                raise AtasHistoryExportError("ATAS export timestamps are not monotonic")
            if first_timestamp is None:
                first_timestamp = timestamp
            previous_timestamp = timestamp
    if header is None or footer is None:
        raise AtasHistoryExportError("ATAS export is missing header or footer")
    metadata = _validate_envelope(header, footer)
    if _footer_count(footer, "cumulative_trade_count") != cumulative_trade_count:
        raise AtasHistoryExportError("ATAS cumulative-trade count does not match footer")
    if _footer_count(footer, "market_depth_snapshot_count") != depth_count:
        raise AtasHistoryExportError("ATAS depth-snapshot count does not match footer")
    if cumulative_trade_count + depth_count == 0:
        raise AtasHistoryExportError("ATAS export contains no historical records")
    requested_from = _utc(metadata["requested_from_utc"], "requested_from_utc")
    requested_to = _utc(metadata["requested_to_utc"], "requested_to_utc")
    if requested_to <= requested_from or requested_to - requested_from > timedelta(days=7):
        raise AtasHistoryExportError("ATAS export request must span >0 and <=7 days")
    if first_timestamp is not None and first_timestamp < requested_from:
        raise AtasHistoryExportError("ATAS export contains data before its request window")
    if previous_timestamp is not None and previous_timestamp > requested_to:
        raise AtasHistoryExportError("ATAS export contains data after its request window")
    connector = _component(metadata["connector"], "connector")
    instrument = _component(metadata["instrument"], "instrument")
    relative = Path(
        "bronze",
        "source=atas",
        f"connector={connector}",
        f"instrument={instrument}",
        f"year={requested_from:%Y}",
        f"month={requested_from:%m}",
        f"day={requested_from:%d}",
        f"{digest}.jsonl",
    )
    destination = data_dir / relative
    _copy_immutable(export_path, destination, digest)
    manifest = AtasHistoryManifest(
        schema_version=ATAS_EXPORT_SCHEMA_VERSION,
        source="atas",
        connector=connector,
        instrument=instrument,
        requested_from_utc=metadata["requested_from_utc"],
        requested_to_utc=metadata["requested_to_utc"],
        exported_at_utc=metadata["exported_at_utc"],
        cumulative_trade_count=cumulative_trade_count,
        market_depth_snapshot_count=depth_count,
        export_sha256=digest,
        export_size_bytes=destination.stat().st_size,
        relative_export_path=relative.as_posix(),
    )
    _write_manifest_immutable(
        destination.with_suffix(".manifest.json"),
        json.dumps(asdict(manifest), sort_keys=True, indent=2, allow_nan=False) + "\n",
    )
    return manifest


def _validate_envelope(
    header: dict[str, object], footer: dict[str, object]
) -> dict[str, str]:
    if header.get("schema_version") != ATAS_EXPORT_SCHEMA_VERSION:
        raise AtasHistoryExportError("unsupported ATAS export schema")
    if header.get("source") != "atas":
        raise AtasHistoryExportError("ATAS export source must be 'atas'")
    values: dict[str, str] = {}
    for key in (
        "connector",
        "instrument",
        "requested_from_utc",
        "requested_to_utc",
        "exported_at_utc",
    ):
        value = header.get(key)
        if not isinstance(value, str) or not value:
            raise AtasHistoryExportError(f"ATAS export header {key} is missing")
        values[key] = value
    _utc(values["exported_at_utc"], "exported_at_utc")
    if footer.get("complete") is not True:
        raise AtasHistoryExportError("ATAS export footer is not complete")
    return values


def _footer_count(footer: dict[str, object], key: str) -> int:
    value = footer.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AtasHistoryExportError(f"ATAS export footer {key} is invalid")
    return value


def _validate_trade(record: dict[str, object], line_number: int) -> datetime:
    timestamp = _record_timestamp(record, line_number)
    _positive_decimal(record.get("first_price"), "first_price", line_number)
    _positive_decimal(record.get("last_price"), "last_price", line_number)
    _positive_decimal(record.get("volume"), "volume", line_number)
    if record.get("direction") not in {"BUY", "SELL", "BETWEEN"}:
        raise AtasHistoryExportError(f"invalid trade direction at line {line_number}")
    tick_count = record.get("tick_count")
    if isinstance(tick_count, bool) or not isinstance(tick_count, int) or tick_count < 0:
        raise AtasHistoryExportError(f"invalid tick_count at line {line_number}")
    return timestamp


def _validate_depth(record: dict[str, object], line_number: int) -> datetime:
    timestamp = _record_timestamp(record, line_number)
    bids = _levels(record.get("bids"), "bids", line_number, reverse=True)
    asks = _levels(record.get("asks"), "asks", line_number, reverse=False)
    if not bids or not asks:
        raise AtasHistoryExportError(f"empty depth snapshot at line {line_number}")
    if bids and asks and bids[0][0] >= asks[0][0]:
        raise AtasHistoryExportError(f"crossed depth snapshot at line {line_number}")
    return timestamp


def _levels(
    value: object, name: str, line_number: int, *, reverse: bool
) -> list[tuple[Decimal, Decimal]]:
    if not isinstance(value, list):
        raise AtasHistoryExportError(f"{name} is not a list at line {line_number}")
    levels: list[tuple[Decimal, Decimal]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise AtasHistoryExportError(f"invalid {name} level at line {line_number}")
        levels.append(
            (
                _positive_decimal(item[0], f"{name}.price", line_number),
                _positive_decimal(item[1], f"{name}.volume", line_number),
            )
        )
    expected = sorted(levels, key=lambda item: item[0], reverse=reverse)
    if levels != expected or len({price for price, _volume in levels}) != len(levels):
        raise AtasHistoryExportError(f"{name} levels are not strictly ordered")
    return levels


def _record_timestamp(record: dict[str, object], line_number: int) -> datetime:
    value = record.get("timestamp_utc")
    if not isinstance(value, str):
        raise AtasHistoryExportError(f"timestamp_utc missing at line {line_number}")
    return _utc(value, f"timestamp_utc at line {line_number}")


def _positive_decimal(value: object, name: str, line_number: int) -> Decimal:
    if not isinstance(value, str):
        raise AtasHistoryExportError(f"{name} must be a decimal string at line {line_number}")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise AtasHistoryExportError(f"invalid {name} at line {line_number}") from exc
    if not result.is_finite() or result <= 0:
        raise AtasHistoryExportError(f"invalid {name} at line {line_number}")
    return result


def _utc(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AtasHistoryExportError(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise AtasHistoryExportError(f"{name} must be UTC")
    return parsed.astimezone(UTC)


def _component(value: str, name: str) -> str:
    if not _SAFE_COMPONENT.fullmatch(value):
        raise AtasHistoryExportError(f"unsafe ATAS {name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AtasHistoryExportError(f"cannot read ATAS export: {path}") from exc
    return digest.hexdigest()


def _copy_immutable(source: Path, destination: Path, digest: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if _sha256(destination) != digest:
            raise AtasHistoryExportError("existing ATAS landing object has wrong checksum")
        return
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        if _sha256(temporary) != digest:
            raise AtasHistoryExportError("ATAS export changed while it was being landed")
        os.link(temporary, destination)
    except FileExistsError:
        if _sha256(destination) != digest:
            raise AtasHistoryExportError("ATAS landing collision") from None
    finally:
        temporary.unlink(missing_ok=True)


def _write_manifest_immutable(path: Path, value: str) -> None:
    encoded = value.encode()
    if path.exists():
        if path.read_bytes() != encoded:
            raise AtasHistoryExportError("existing ATAS manifest conflicts")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError:
        if path.read_bytes() != encoded:
            raise AtasHistoryExportError("ATAS manifest collision") from None
    finally:
        temporary.unlink(missing_ok=True)
