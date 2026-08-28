"""Proves `iter_raw_events` memory is bounded relative to the size of the
raw lake it replays, not proportional to it - the actual root cause of the
production OOM kill (`python` PID 3736579, anon-rss ~5.46GB replaying the
full BTCUSDT raw lake with no date filter) that killed the prior session.

An earlier version of the connection-aware merge (`ordered_merge.py`)
declared itself a "streaming k-way merge" but actually did
`buckets.setdefault(conn, []).append(row)` for the ENTIRE input before
yielding a single row - memory grew with total row count. `read_raw_part`
also did a full `ParquetFile.read()` + `to_pylist()`, and `verify_raw_part`
read the whole part a SECOND time to recompute its checksum, including the
`payload_text` column - by far the largest field - for every event, for
every part, all at once.

This does not merely assert "no OOM" (unreliable and slow); it measures
process peak RSS delta (isolated from Python/pandas/pyarrow import
overhead, and isolated per-scenario via a subprocess so peaks don't
accumulate across scenarios) for two dataset sizes that differ by 20x in
total row count, across many parts and many overlapping connections (the
real reconnect shape, not a toy single-stream case), and asserts the
larger dataset's memory delta is NOT proportionally larger.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKER = Path(__file__).with_name("_bounded_memory_replay_worker.py")

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="peak-RSS worker uses the Unix-only resource module; CI/VPS validation is Linux",
)


def _run_worker(
    data_dir: Path, *, connections: int, parts_per_connection: int, rows_per_part: int
) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(_WORKER),
            str(data_dir),
            str(connections),
            str(parts_per_connection),
            str(rows_per_part),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"worker failed (rc={result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    # Worker prints exactly one JSON line as its last stdout line.
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_replay_memory_does_not_scale_linearly_with_event_count(tmp_path: Path) -> None:
    small_dir = tmp_path / "small"
    large_dir = tmp_path / "large"
    small_dir.mkdir()
    large_dir.mkdir()

    # Same connection/part topology (same admission-control "shape"), only
    # rows_per_part differs 20x - isolates row-count scaling specifically,
    # not part or connection count.
    small = _run_worker(small_dir, connections=10, parts_per_connection=2, rows_per_part=200)
    large = _run_worker(large_dir, connections=10, parts_per_connection=2, rows_per_part=4_000)

    assert small["row_count"] == 10 * 2 * 200
    assert large["row_count"] == 10 * 2 * 4_000
    row_count_ratio = large["row_count"] / small["row_count"]
    assert row_count_ratio == pytest.approx(20.0)

    small_delta = max(small["delta_rss_kb"], 1)
    large_delta = max(large["delta_rss_kb"], 1)
    memory_ratio = large_delta / small_delta

    # A materializing implementation (the original bug) would show
    # memory_ratio tracking row_count_ratio (~20x). A genuinely bounded,
    # streaming/chunked implementation should show far less growth - most
    # of it from Arrow/Parquet's own fixed per-process overhead and batch
    # buffers, not from holding the dataset. Generous but discriminating:
    # well under half the row-count growth.
    assert memory_ratio < row_count_ratio / 2, (
        f"replay memory grew {memory_ratio:.1f}x when row count grew "
        f"{row_count_ratio:.1f}x - suggests iter_raw_events is materializing "
        f"the raw lake instead of streaming it "
        f"(small={small}, large={large})"
    )


def test_replay_handles_many_overlapping_connections_with_bounded_open_parts(
    tmp_path: Path,
) -> None:
    """Many connections, each overlapping only its neighbor (the real
    reconnect shape) - not one giant all-overlapping cluster. Confirms
    correctness (every event present, globally causal order) at a scale
    that would have opened hundreds of file handles at once under an
    eager, non-admission-controlled merge.
    """
    data_dir = tmp_path / "many_connections"
    result = _run_worker(data_dir, connections=60, parts_per_connection=3, rows_per_part=100)
    assert result["row_count"] == 60 * 3 * 100
