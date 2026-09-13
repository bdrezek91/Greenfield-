"""Archive explicitly completed Bybit Silver trade days, verifying every byte before pruning.

Run exclusively with respect to materialization/restores. The systemd unit
serializes archival runs; operators must stop it before catch-up or restore.
This is same-volume inode reclamation,
not an off-host backup or an OOS quality certificate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

PREFIX = (
    "silver/v2/normalizer=greenfield-bybit-normalizer-v2/"
    "exchange=bybit/market=linear/channel=trades"
)
IDENTITY = re.compile(r"gold-trades-(BTCUSDT|ETHUSDT|SOLUSDT)-(\d{4}-\d{2}-\d{2})$")
RESERVE = 6 * 1024**3


class Readable(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


def digest(stream: Readable) -> str:
    result = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        result.update(chunk)
    return result.hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return digest(stream)


def inventory(source: Path, *, allow_empty: bool = False) -> dict[str, dict]:
    result = {}
    for path in sorted(source.iterdir()):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"only regular, flat partition files allowed: {path}")
        result[path.name] = {"size": path.stat().st_size, "sha256": file_hash(path)}
    if not result and not allow_empty:
        raise ValueError("empty partition")
    return result


def verify_archive(archive: Path, entries: dict[str, dict]) -> None:
    seen = set()
    with tarfile.open(archive, "r|") as bundle:
        for member in bundle:
            if (
                not member.isfile() or member.name not in entries or member.name in seen
                or "/" in member.name or "\\" in member.name or member.name in (".", "..")
            ):
                raise ValueError("unexpected, duplicate or unsafe archive member")
            expected = entries[member.name]
            stream = bundle.extractfile(member)
            if stream is None or member.size != expected["size"]:
                raise ValueError("archive member size mismatch")
            # Restore every member to one temporary file at a time. This proves
            # actual disk round-trip without requiring another 30k free inodes.
            with stream, tempfile.TemporaryFile(dir=archive.parent) as restored:
                shutil.copyfileobj(stream, restored, length=1024 * 1024)
                restored.flush()
                os.fsync(restored.fileno())
                restored.seek(0)
                if digest(restored) != expected["sha256"]:
                    raise ValueError("restored archive content mismatch")
            seen.add(member.name)
    if seen != entries.keys():
        raise ValueError("archive is missing files")


def safe_path(root: Path, relative: Path) -> Path:
    path = root / relative
    if path.resolve() != path or not path.is_relative_to(root) or path == root:
        raise ValueError("partition/archive path escapes root or contains symlink")
    return path


def archive_partition(root: Path, symbol: str, day: str, *, prune: bool) -> dict:
    root = root.resolve(strict=True)
    if symbol not in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        raise ValueError("unsupported symbol")
    parsed_day = date.fromisoformat(day)
    if parsed_day.isoformat() != day or parsed_day >= datetime.now(UTC).date():
        raise ValueError("only closed UTC dates allowed")
    relative = Path(PREFIX) / f"symbol={symbol}" / f"date={day}"
    source = safe_path(root, relative)
    destination = safe_path(root, Path("_archives/bybit-silver-trades") / f"{symbol}-{day}")
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "partition.tar"
    evidence = destination / "manifest.json"
    if evidence.exists():
        report = json.loads(evidence.read_text())
        if (
            report["source"] != relative.as_posix()
            or file_hash(archive) != report["archive_sha256"]
        ):
            raise ValueError("existing archive identity/checksum mismatch")
        entries = report["files"]
        if report.get("restore_verified") is not True:
            raise ValueError("archive lacks restore evidence")
    else:
        if archive.exists():
            raise ValueError("archive without evidence requires review; source retained")
        entries = inventory(source)
        needed = sum(v["size"] + 4096 for v in entries.values())
        needed += max(v["size"] for v in entries.values()) + RESERVE
        if shutil.disk_usage(root).free < needed:
            raise OSError("insufficient archive/restore capacity plus six-GiB reserve")
        temporary = destination / "partition.tar.partial"
        # A crashed partial is left for review, never accepted as a valid archive.
        with temporary.open("xb") as output:
            with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as bundle:
                for name in entries:
                    bundle.add(source / name, arcname=name, recursive=False)
            output.flush()
            os.fsync(output.fileno())
        verify_archive(temporary, entries)
        if inventory(source) != entries:
            raise ValueError("source changed while archiving; source retained")
        temporary.replace(archive)
        report = {
            "source": relative.as_posix(), "files": entries,
            "archive_sha256": file_hash(archive), "restore_verified": True,
            "source_pruned": False, "oos_ready": False,
        }
        with evidence.open("x", encoding="utf-8") as output:
            json.dump(report, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        if hasattr(os, "O_DIRECTORY"):
            fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    if prune and source.exists():
        verify_archive(archive, entries)
        current = inventory(source, allow_empty=True)
        if any(name not in entries or entries[name] != value for name, value in current.items()):
            raise ValueError("source changed before pruning")
        for name in current:
            (source / name).unlink()
        source.rmdir()
    report["source_pruned"] = not source.exists()
    return {k: v for k, v in report.items() if k != "files"} | {"file_count": len(entries)}


def candidates(root: Path, status_path: Path) -> list[tuple[str, str]]:
    state = json.loads(status_path.read_text())
    if state["state"] not in ("STOPPED_REQUIRES_REVIEW", "PROCESSED_PENDING_COVERAGE_AUDIT"):
        raise ValueError("processing queue must be stopped before archiving")
    completed = set(state["completed"])
    result = []
    for name in sorted(completed):
        match = IDENTITY.fullmatch(name)
        if not match:
            continue
        symbol, day = match.groups()
        if f"normalize-trades-{symbol}-{day}" not in completed:
            continue
        source = safe_path(root, Path(PREFIX) / f"symbol={symbol}" / f"date={day}")
        if source.exists():
            result.append((symbol, day))
    return sorted(result, key=lambda item: (item[1], item[0]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--prune", action="store_true")
    parser.add_argument("--target-free-inodes", type=int, default=400_000)
    args = parser.parse_args()
    if args.prune and not args.execute:
        parser.error("--prune requires --execute")
    if args.target_free_inodes <= 100_000:
        parser.error("target must exceed the 100000 inode emergency reserve")
    root = args.data_dir.resolve(strict=True)
    for symbol, day in candidates(root, args.status_file):
        if hasattr(os, "statvfs") and os.statvfs(root).f_favail >= args.target_free_inodes:
            break
        if not args.execute:
            print(json.dumps({"symbol": symbol, "day": day, "action": "PLAN"}), flush=True)
            continue
        print(json.dumps({"symbol": symbol, "day": day, "action": "START"}), flush=True)
        print(json.dumps(archive_partition(root, symbol, day, prune=args.prune)), flush=True)
    if args.execute and hasattr(os, "statvfs"):
        free = os.statvfs(root).f_favail
        reached = free >= args.target_free_inodes
        print(json.dumps({
            "status": "TARGET_REACHED" if reached else "ELIGIBLE_PARTITIONS_EXHAUSTED",
            "free_inodes": free, "target_free_inodes": args.target_free_inodes,
        }), flush=True)
        if not reached:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
