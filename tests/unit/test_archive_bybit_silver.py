import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts.archive_bybit_silver import (
    PREFIX,
    archive_partition,
    candidates,
    inventory,
    verify_archive,
)


def partition(root: Path) -> Path:
    path = root / PREFIX / "symbol=BTCUSDT/date=2020-01-01"
    path.mkdir(parents=True)
    (path / "a.parquet").write_bytes(b"original data")
    (path / "a.manifest.json").write_text('{"example":true}')
    return path


def test_archive_restores_every_file_before_prune_and_is_idempotent(tmp_path: Path) -> None:
    source = partition(tmp_path)
    expected = inventory(source)
    result = archive_partition(tmp_path, "BTCUSDT", "2020-01-01", prune=True)
    assert result["restore_verified"] and result["source_pruned"]
    assert not source.exists()
    target = tmp_path / "_archives/bybit-silver-trades/BTCUSDT-2020-01-01/partition.tar"
    verify_archive(target, expected)
    assert archive_partition(tmp_path, "BTCUSDT", "2020-01-01", prune=True) == result


def test_modified_source_cannot_be_pruned_against_old_archive(tmp_path: Path) -> None:
    source = partition(tmp_path)
    archive_partition(tmp_path, "BTCUSDT", "2020-01-01", prune=False)
    (source / "a.parquet").write_bytes(b"changed data")
    with pytest.raises(ValueError, match="source changed"):
        archive_partition(tmp_path, "BTCUSDT", "2020-01-01", prune=True)
    assert (source / "a.parquet").read_bytes() == b"changed data"


@pytest.mark.parametrize("kind", ["corrupt", "missing", "duplicate", "traversal"])
def test_bad_archive_is_rejected(tmp_path: Path, kind: str) -> None:
    source = partition(tmp_path)
    entries = inventory(source)
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as bundle:
        for name in entries:
            if kind == "missing" and name == "a.parquet":
                continue
            payload = (source / name).read_bytes()
            if kind == "corrupt":
                payload = b"x" * len(payload)
            member = tarfile.TarInfo("../" + name if kind == "traversal" else name)
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))
            if kind == "duplicate":
                bundle.addfile(member, io.BytesIO(payload))
    with pytest.raises(ValueError):
        verify_archive(archive, entries)
    assert source.exists()


def test_incomplete_or_running_processing_is_not_eligible(tmp_path: Path) -> None:
    partition(tmp_path)
    status = tmp_path / "status.json"
    status.write_text(json.dumps({
        "state": "STOPPED_REQUIRES_REVIEW",
        "completed": ["normalize-trades-BTCUSDT-2020-01-01"],
    }))
    assert candidates(tmp_path, status) == []
    status.write_text(json.dumps({"state": "RUNNING", "completed": []}))
    with pytest.raises(ValueError, match="stopped"):
        candidates(tmp_path, status)


def test_symlink_partition_rejected(tmp_path: Path) -> None:
    source = partition(tmp_path)
    outside = tmp_path / "outside"
    source.rename(outside)
    try:
        source.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(ValueError, match="symlink"):
        archive_partition(tmp_path, "BTCUSDT", "2020-01-01", prune=True)
    assert (outside / "a.parquet").exists()
