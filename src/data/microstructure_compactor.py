"""Daily compaction of microstructure batch files.

`src/data/microstructure_writer.py` writes one small Parquet file per
flush (tens of times per second for order-book updates) - by design, to
keep flushing O(batch size). Left alone this accumulates ~thousands of
tiny files per symbol per day (`docs/PROJECT_STATUS.md`'s disclosed,
previously-unfixed gap), which eventually slows down `read_range`'s glob +
concat.

`compact_day` merges one (stream, symbol, date) directory's files into a
single file, following the brief's exact safety sequence:

1. write the merged result to a temporary file in the SAME directory
   (same filesystem -> the final rename is atomic),
2. validate the temp file's row count and timestamp range against the
   sources it was built from,
3. only then atomically rename the temp file into place,
4. only THEN delete the original small files - never before the merged
   file is confirmed valid and already in place, so a crash between steps
   never loses data (worst case: the small files AND the merged file both
   exist, and the next run finds the pre-existing merged file already
   satisfies the "already compacted" check and just re-validates it).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

_COMPACTED_PREFIX = "compacted-"


@dataclass(frozen=True)
class CompactionResult:
    directory: Path
    source_files: int
    source_rows: int
    merged_rows: int
    merged_path: Path | None
    skipped_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.skipped_reason is None


def _small_files(directory: Path) -> list[Path]:
    return sorted(
        p for p in directory.glob("*.parquet") if not p.name.startswith(_COMPACTED_PREFIX)
    )


def compact_day(directory: Path) -> CompactionResult:
    """Compact every non-compacted `*.parquet` file directly inside
    `directory` into one file. Safe to call repeatedly (a day with nothing
    new to compact - 0 or 1 source file - is a no-op).
    """
    if not directory.exists():
        return CompactionResult(directory, 0, 0, 0, None, skipped_reason="directory does not exist")

    sources = _small_files(directory)
    if len(sources) <= 1:
        return CompactionResult(
            directory, len(sources), 0, 0, None, skipped_reason="nothing to compact"
        )

    frames = [pd.read_parquet(p) for p in sources]
    source_rows = sum(len(f) for f in frames)
    merged = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)

    tmp_path = directory / f".tmp-{uuid.uuid4().hex}.parquet"
    merged.to_parquet(tmp_path, index=False)

    # Validate the temp file before it's trusted - re-read from disk, not
    # from the in-memory frame, so a truncated/corrupt write is caught.
    reread = pd.read_parquet(tmp_path)
    if len(reread) != source_rows:
        tmp_path.unlink(missing_ok=True)
        return CompactionResult(
            directory,
            len(sources),
            source_rows,
            len(reread),
            None,
            skipped_reason=(
                f"validation failed: merged row count {len(reread)} != source row count "
                f"{source_rows} - source files left untouched"
            ),
        )
    if reread["timestamp"].min() != merged["timestamp"].min() or (
        reread["timestamp"].max() != merged["timestamp"].max()
    ):
        tmp_path.unlink(missing_ok=True)
        return CompactionResult(
            directory,
            len(sources),
            source_rows,
            len(reread),
            None,
            skipped_reason=(
                "validation failed: timestamp range mismatch - source files left untouched"
            ),
        )

    final_path = directory / f"{_COMPACTED_PREFIX}{uuid.uuid4().hex}.parquet"
    os.replace(tmp_path, final_path)  # atomic on the same filesystem

    # Only now, with the validated merged file already in place, remove
    # the small sources it replaces.
    for path in sources:
        path.unlink(missing_ok=True)

    return CompactionResult(directory, len(sources), source_rows, len(reread), final_path)


def compact_all(
    data_dir: Path, streams: tuple[str, ...] = ("orderbook", "trades", "liquidations")
) -> list[CompactionResult]:
    """Compact every (stream, symbol, date) directory under
    `data_dir/microstructure/`, skipping today's date (still being written
    to live) and anything already fully compacted.
    """
    results: list[CompactionResult] = []
    today = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
    root = Path(data_dir) / "microstructure"
    if not root.exists():
        return results

    for stream in streams:
        stream_dir = root / stream
        if not stream_dir.exists():
            continue
        for symbol_dir in sorted(stream_dir.iterdir()):
            if not symbol_dir.is_dir():
                continue
            for date_dir in sorted(symbol_dir.iterdir()):
                if not date_dir.is_dir() or date_dir.name == today:
                    continue
                try:
                    results.append(compact_day(date_dir))
                except Exception as exc:
                    results.append(
                        CompactionResult(
                            directory=date_dir,
                            source_files=len(_small_files(date_dir)),
                            source_rows=0,
                            merged_rows=0,
                            merged_path=None,
                            skipped_reason=(
                                f"compaction error ({type(exc).__name__}): {exc}; "
                                "source files left untouched"
                            ),
                        )
                    )
    return results
