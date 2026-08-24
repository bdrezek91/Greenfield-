"""Crash-safe, single-writer merge for mutable Parquet partitions."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd


class ParquetWriteLockTimeout(TimeoutError):
    pass


@contextmanager
def _exclusive_lock(path: Path, timeout_seconds: float = 30.0) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        def lock() -> None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

        def unlock() -> None:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        def lock() -> None:
            fcntl.flock(  # type: ignore[attr-defined]
                handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB  # type: ignore[attr-defined]
            )

        def unlock() -> None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            handle.seek(0)
            lock()
            break
        except OSError as exc:
            if time.monotonic() >= deadline:
                handle.close()
                raise ParquetWriteLockTimeout(f"timed out locking {path}") from exc
            time.sleep(0.05)
    try:
        yield
    finally:
        handle.seek(0)
        unlock()
        handle.close()


def merge_atomic_parquet(
    path: Path,
    incoming: pd.DataFrame,
    *,
    deduplicate_on: Sequence[str],
    sort_by: Sequence[str],
) -> None:
    """Merge, deduplicate and atomically replace one Parquet partition."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(path):
        merged = incoming.copy()
        if path.exists():
            merged = pd.concat([pd.read_parquet(path), merged], ignore_index=True)
        merged = merged.drop_duplicates(subset=list(deduplicate_on))
        merged = merged.sort_values(list(sort_by), kind="mergesort").reset_index(drop=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
            merged.to_parquet(temporary_path, index=False)
            # Windows requires a writable descriptor for fsync; the file's
            # content is already complete, this mode does not mutate it.
            with temporary_path.open("r+b") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
            if os.name != "nt":
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
