"""ExperimentStore must assign sequential IDs and round-trip records losslessly."""

from __future__ import annotations

from pathlib import Path

from src.analytics.experiment import (
    CURRENT_TIMESTAMP_SEMANTICS,
    LEGACY_INVALID_FOR_PROMOTION,
    ExperimentRecord,
    ExperimentStore,
    capture_git_commit,
    fingerprint_dataset,
    mark_legacy_results,
)


def _record(experiment_id: str = "EXP-000001") -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=experiment_id,
        git_commit="abc123",
        dataset_version="deadbeef",
        date_range=("2024-01-01", "2024-02-01"),
        symbols=("BTCUSDT",),
        timeframes=("1h",),
        strategy_version="none",
        parameters={"foo": 1},
        fees={"maker": 0.0002, "taker": 0.00055},
        slippage={"prob_slippage": 0.2},
        funding_assumptions={"rate_per_interval": 0.0001},
        metrics={"sharpe": 1.23},
    )


def test_next_id_starts_at_one(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    assert store.next_id() == "EXP-000001"


def test_next_id_increments_after_save(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    store.save(_record("EXP-000001"))
    assert store.next_id() == "EXP-000002"
    store.save(_record("EXP-000002"))
    assert store.next_id() == "EXP-000003"


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    original = _record()
    store.save(original)

    loaded = store.load_all()
    assert len(loaded) == 1
    assert loaded[0] == original


def test_get_returns_matching_record(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "experiments.jsonl")
    store.save(_record("EXP-000001"))
    store.save(_record("EXP-000002"))

    found = store.get("EXP-000002")
    assert found is not None
    assert found.experiment_id == "EXP-000002"
    assert store.get("EXP-999999") is None


def test_load_all_on_missing_file_returns_empty(tmp_path: Path) -> None:
    store = ExperimentStore(tmp_path / "nonexistent.jsonl")
    assert store.load_all() == []


def test_capture_git_commit_in_this_repo_returns_a_hash() -> None:
    commit = capture_git_commit(Path(__file__).resolve().parents[2])
    assert commit != "unknown"
    assert len(commit) == 40


def test_capture_git_commit_outside_repo_returns_unknown(tmp_path: Path) -> None:
    assert capture_git_commit(tmp_path) == "unknown"


def test_fingerprint_dataset_no_data_dir(tmp_path: Path) -> None:
    assert fingerprint_dataset(tmp_path, "BTCUSDT", "1h") == "no-data"


def test_fingerprint_dataset_is_deterministic(tmp_path: Path) -> None:
    partition_dir = tmp_path / "klines" / "BTCUSDT" / "1h"
    partition_dir.mkdir(parents=True)
    (partition_dir / "2024-01.parquet").write_bytes(b"fake parquet data")

    first = fingerprint_dataset(tmp_path, "BTCUSDT", "1h")
    second = fingerprint_dataset(tmp_path, "BTCUSDT", "1h")
    assert first == second
    assert first != "no-data"


def test_mark_legacy_results_preserves_history_and_invalidates_only_old_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "experiments.jsonl"
    legacy = _record("EXP-000001")
    current = ExperimentRecord(
        **{
            **legacy.__dict__,
            "experiment_id": "EXP-000002",
            "timestamp_semantics_version": CURRENT_TIMESTAMP_SEMANTICS,
            "validity_status": "valid_for_current_protocol",
        }
    )
    path.write_text(legacy.to_json() + "\n" + current.to_json() + "\n", encoding="utf-8")

    assert mark_legacy_results(path) == 0
    loaded = ExperimentStore(path).load_all()
    assert [record.experiment_id for record in loaded] == ["EXP-000001", "EXP-000002"]
    assert loaded[0].validity_status == LEGACY_INVALID_FOR_PROMOTION
    assert loaded[1].validity_status == "valid_for_current_protocol"
