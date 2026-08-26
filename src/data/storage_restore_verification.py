"""Deterministic source-versus-restored storage tree verification evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StorageRestoreVerificationError(RuntimeError):
    """Storage restore evidence is unsafe, malformed, or not equivalent."""


@dataclass(frozen=True, slots=True)
class StorageTreeDigest:
    root: str
    tree_sha256: str
    file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class StorageRestoreVerificationReport:
    schema_version: int
    generated_at_utc: str
    qualified: bool
    source: StorageTreeDigest
    restored: StorageTreeDigest
    checks: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify_storage_restore(
    source_root: Path, restored_root: Path
) -> StorageRestoreVerificationReport:
    source = Path(source_root).resolve(strict=True)
    restored = Path(restored_root).resolve(strict=True)
    if source == restored or source in restored.parents or restored in source.parents:
        raise StorageRestoreVerificationError(
            "source and restored roots must be distinct and non-overlapping"
        )
    source_digest = _digest_tree(source)
    restored_digest = _digest_tree(restored)
    checks = {
        "nonempty_source": source_digest.file_count > 0,
        "file_count_equal": source_digest.file_count == restored_digest.file_count,
        "byte_count_equal": source_digest.total_bytes == restored_digest.total_bytes,
        "tree_sha256_equal": source_digest.tree_sha256 == restored_digest.tree_sha256,
    }
    return StorageRestoreVerificationReport(
        schema_version=1,
        generated_at_utc=datetime.now(UTC).isoformat(),
        qualified=all(checks.values()),
        source=source_digest,
        restored=restored_digest,
        checks=checks,
    )


def write_storage_restore_verification_report(
    path: Path, report: StorageRestoreVerificationReport
) -> None:
    document = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    destination = Path(path)
    resolved_destination = destination.resolve()
    source = Path(report.source.root)
    restored = Path(report.restored.root)
    if (
        resolved_destination in {source, restored}
        or source in resolved_destination.parents
        or restored in resolved_destination.parents
    ):
        raise StorageRestoreVerificationError(
            "verification report must be outside both compared trees"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise FileExistsError(
            f"restore verification already exists and will not be overwritten: {destination}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def load_storage_restore_verification_report(
    path: Path,
) -> StorageRestoreVerificationReport:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        report = StorageRestoreVerificationReport(
            schema_version=int(value["schema_version"]),
            generated_at_utc=str(value["generated_at_utc"]),
            qualified=value["qualified"] is True,
            source=_load_digest(value["source"]),
            restored=_load_digest(value["restored"]),
            checks={str(key): item is True for key, item in value["checks"].items()},
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StorageRestoreVerificationError(
            "malformed storage restore verification report"
        ) from exc
    try:
        timestamp = datetime.fromisoformat(report.generated_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StorageRestoreVerificationError(
            "storage restore verification timestamp is invalid"
        ) from exc
    if (
        report.schema_version != 1
        or timestamp.tzinfo is None
        or not report.qualified
        or not report.checks
        or not all(report.checks.values())
        or report.source.file_count <= 0
        or report.source.file_count != report.restored.file_count
        or report.source.total_bytes != report.restored.total_bytes
        or report.source.tree_sha256 != report.restored.tree_sha256
    ):
        raise StorageRestoreVerificationError(
            "storage restore verification report is not qualified"
        )
    return report


def _digest_tree(root: Path) -> StorageTreeDigest:
    if not root.is_dir():
        raise StorageRestoreVerificationError(f"storage root is not a directory: {root}")
    entries: list[dict[str, str | int]] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise StorageRestoreVerificationError(f"symlink is forbidden: {relative}")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise StorageRestoreVerificationError(
                f"special filesystem entry is forbidden: {relative}"
            )
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        entries.append({"path": relative, "size_bytes": size, "sha256": digest.hexdigest()})
        total_bytes += size
    material = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return StorageTreeDigest(
        root=str(root),
        tree_sha256=hashlib.sha256(material).hexdigest(),
        file_count=len(entries),
        total_bytes=total_bytes,
    )


def _load_digest(value: Any) -> StorageTreeDigest:
    if not isinstance(value, dict):
        raise TypeError("tree digest must be an object")
    digest = StorageTreeDigest(
        root=str(value["root"]),
        tree_sha256=str(value["tree_sha256"]),
        file_count=int(value["file_count"]),
        total_bytes=int(value["total_bytes"]),
    )
    if (
        not Path(digest.root).is_absolute()
        or not _SHA256.fullmatch(digest.tree_sha256)
        or set(digest.tree_sha256) == {"0"}
        or digest.file_count < 0
        or digest.total_bytes < 0
    ):
        raise ValueError("invalid tree digest")
    return digest
