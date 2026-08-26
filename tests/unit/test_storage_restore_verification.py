"""Storage restore proof hashes complete, independent file trees."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.data.storage_restore_verification import (
    StorageRestoreVerificationError,
    load_storage_restore_verification_report,
    verify_storage_restore,
    write_storage_restore_verification_report,
)


def _tree(root: Path) -> None:
    (root / "nested").mkdir(parents=True)
    (root / "manifest.json").write_text('{"schema":1}\n', encoding="utf-8")
    (root / "nested" / "part.bin").write_bytes(b"market-data\x00\x01")


def test_identical_independent_trees_qualify_and_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source"
    restored = tmp_path / "restored"
    _tree(source)
    _tree(restored)

    report = verify_storage_restore(source, restored)
    path = tmp_path / "report.json"
    write_storage_restore_verification_report(path, report)
    loaded = load_storage_restore_verification_report(path)

    assert report.qualified is True
    assert report.source.tree_sha256 == report.restored.tree_sha256
    assert report.source.file_count == 2
    assert loaded == report
    with pytest.raises(FileExistsError, match="will not be overwritten"):
        write_storage_restore_verification_report(path, report)


def test_changed_file_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    restored = tmp_path / "restored"
    _tree(source)
    _tree(restored)
    (restored / "nested" / "part.bin").write_bytes(b"different")

    report = verify_storage_restore(source, restored)

    assert report.qualified is False
    assert report.checks["tree_sha256_equal"] is False


def test_report_cannot_mutate_either_compared_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    restored = tmp_path / "restored"
    _tree(source)
    _tree(restored)
    report = verify_storage_restore(source, restored)

    with pytest.raises(StorageRestoreVerificationError, match="outside"):
        write_storage_restore_verification_report(source / "report.json", report)
    with pytest.raises(StorageRestoreVerificationError, match="outside"):
        write_storage_restore_verification_report(restored / "report.json", report)


def test_same_or_nested_roots_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _tree(source)

    with pytest.raises(StorageRestoreVerificationError, match="non-overlapping"):
        verify_storage_restore(source, source)
    with pytest.raises(StorageRestoreVerificationError, match="non-overlapping"):
        verify_storage_restore(source, source / "nested")


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation needs privileges")
def test_symlink_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    restored = tmp_path / "restored"
    _tree(source)
    _tree(restored)
    (restored / "link").symlink_to(restored / "manifest.json")

    with pytest.raises(StorageRestoreVerificationError, match="symlink"):
        verify_storage_restore(source, restored)


def test_loader_rejects_forged_qualification(tmp_path: Path) -> None:
    path = tmp_path / "forged.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at_utc": "2026-08-26T12:00:00Z",
                "qualified": True,
                "source": {
                    "root": str((tmp_path / "a").resolve()),
                    "tree_sha256": "a" * 64,
                    "file_count": 1,
                    "total_bytes": 1,
                },
                "restored": {
                    "root": str((tmp_path / "b").resolve()),
                    "tree_sha256": "b" * 64,
                    "file_count": 1,
                    "total_bytes": 1,
                },
                "checks": {"tree_sha256_equal": True},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(StorageRestoreVerificationError, match="not qualified"):
        load_storage_restore_verification_report(path)
