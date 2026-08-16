"""TrialLedger: append-only, never-resetting global trial count, and the
frozen-holdout-used-once guard (docs/AUTONOMOUS_RESEARCH_AUDIT.md
"M-częściowe #3" and the data-leakage section).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.research.ledger import TrialLedger, TrialRecord, fingerprint_dataset_content


def _trial(**overrides) -> TrialRecord:
    base = dict(
        trial_id="TRIAL-000001",
        hypothesis_id="HYP-momentum_trend-000001",
        parent_hypothesis_id=None,
        family="momentum_trend",
        rationale="Trend persistence after costs.",
        symbol="BTCUSDT",
        timeframe="4h",
        cost_scenario="adverse",
        status="PASSED",
    )
    base.update(overrides)
    return TrialRecord(**base)


def test_record_and_load_roundtrip(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    ledger.record(_trial())
    loaded = ledger.load_all()
    assert len(loaded) == 1
    assert loaded[0].hypothesis_id == "HYP-momentum_trend-000001"


def test_next_trial_id_increments(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    assert ledger.next_trial_id() == "TRIAL-000001"
    ledger.record(_trial(trial_id="TRIAL-000001"))
    assert ledger.next_trial_id() == "TRIAL-000002"


def test_ledger_is_append_only_across_instances(tmp_path: Path) -> None:
    """A fresh TrialLedger instance pointed at the same path (simulating a
    new research cycle / new process) must see everything prior instances
    wrote - the count is never reset just because a new cycle started.
    """
    path = tmp_path / "ledger.jsonl"
    TrialLedger(path).record(_trial(trial_id="TRIAL-000001"))
    TrialLedger(path).record(_trial(trial_id="TRIAL-000002", status="FAILED_GATE"))
    fresh = TrialLedger(path)
    assert fresh.global_trial_count() == 2


def test_global_trial_count_includes_failed_and_rejected(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    ledger.record(_trial(trial_id="TRIAL-000001", status="PASSED"))
    ledger.record(_trial(trial_id="TRIAL-000002", status="FAILED_GATE"))
    ledger.record(_trial(trial_id="TRIAL-000003", status="REJECTED"))
    ledger.record(_trial(trial_id="TRIAL-000004", status="ERROR"))
    assert ledger.global_trial_count() == 4


def test_global_trial_count_filters_by_family(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    ledger.record(_trial(trial_id="TRIAL-000001", family="momentum_trend"))
    ledger.record(_trial(trial_id="TRIAL-000002", family="funding_oi"))
    assert ledger.global_trial_count(family="momentum_trend") == 1
    assert ledger.global_trial_count() == 2


def test_unknown_status_rejected() -> None:
    with pytest.raises(ValueError, match="unknown trial status"):
        _trial(status="MAYBE")


def test_holdout_not_used_before_any_trial(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    assert ledger.holdout_already_used("momentum_trend", "2026H1-v1") is False


def test_holdout_reuse_is_detected(tmp_path: Path) -> None:
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    ledger.record(
        _trial(trial_id="TRIAL-000001", holdout_used=True, holdout_id="2026H1-v1")
    )
    assert ledger.holdout_already_used("momentum_trend", "2026H1-v1") is True
    assert ledger.holdout_already_used("funding_oi", "2026H1-v1") is False
    assert ledger.holdout_already_used("momentum_trend", "2026H2-v1") is False


def test_content_fingerprint_no_data_dir(tmp_path: Path) -> None:
    assert fingerprint_dataset_content(tmp_path, "BTCUSDT", "4h") == "no-data"


def test_content_fingerprint_changes_with_content_not_just_mtime(tmp_path: Path) -> None:
    import os
    import time

    partition = tmp_path / "klines" / "BTCUSDT" / "4h"
    partition.mkdir(parents=True)
    f = partition / "part.parquet"
    f.write_bytes(b"aaaa")
    fp1 = fingerprint_dataset_content(tmp_path, "BTCUSDT", "4h")

    # Touch mtime without changing content - fingerprint must NOT change.
    time.sleep(0.01)
    os.utime(f, None)
    fp2 = fingerprint_dataset_content(tmp_path, "BTCUSDT", "4h")
    assert fp1 == fp2

    # Change content - fingerprint MUST change.
    f.write_bytes(b"bbbb")
    fp3 = fingerprint_dataset_content(tmp_path, "BTCUSDT", "4h")
    assert fp3 != fp1
