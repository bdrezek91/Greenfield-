"""Immutability, integrity, and traversal-safety tests for the ShadowWork store."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.engines.contracts import (
    DataQualityStatus,
    LegSide,
    MarketTarget,
    NumericRange,
    SetupAction,
    SetupDecision,
    SetupLeg,
)
from src.engines.meta import MetaDecision
from src.execution.shadow_loop import DurableShadowQueue, ShadowQueueStatus, ShadowWork
from src.execution.shadow_store import (
    SHADOW_WORK_SCHEMA_VERSION,
    ShadowWorkStore,
    ShadowWorkStoreError,
    build_shadow_work_uri,
    enqueue_shadow_work,
    parse_shadow_work_uri,
)
from src.risk.portfolio_engine import PortfolioEntryProposal

NOW = datetime(2026, 8, 23, 18, tzinfo=UTC)


def _store(base_dir: Path) -> ShadowWorkStore:
    return ShadowWorkStore(base_dir, now_fn=lambda: NOW)


def _wait_work(observation_id: str = "observation-1") -> ShadowWork:
    return ShadowWork(
        observation_id=observation_id,
        meta=MetaDecision(
            action=SetupAction.WAIT,
            decision_timestamp_utc=NOW,
            selected_engine_id=None,
            selected_setup=None,
            allocated_notional=0.0,
            rankings=(),
            reason_codes=("NO_EDGE",),
        ),
        proposals=(),
        equity=100_000.0,
    )


def _actionable_work(observation_id: str = "observation-2") -> ShadowWork:
    setup = SetupDecision(
        action=SetupAction.LONG,
        targets=(MarketTarget("BTCUSDT", ("bybit",)),),
        legs=(SetupLeg("BTCUSDT", "bybit", LegSide.BUY),),
        decision_timestamp_utc=NOW,
        data_cutoff_utc=NOW,
        horizon="15m",
        evidence=(),
        regimes=(("trend", "up"),),
        entry_condition="confirmed setup",
        invalidation="structure break",
        stop_or_hedge_logic="fixed risk stop",
        expected_cost_bps=NumericRange(2, 3, 5),
        expected_value_after_cost_bps=NumericRange(4, 8, 12),
        capacity_notional=20_000.0,
        data_quality_status=DataQualityStatus.PASS,
        model_version="directional-v1",
        feature_version="features-v1",
        reason_codes=("APPROVED",),
    )
    meta = MetaDecision(
        action=SetupAction.LONG,
        decision_timestamp_utc=NOW,
        selected_engine_id="directional-v1",
        selected_setup=setup,
        allocated_notional=20_000.0,
        rankings=(),
        reason_codes=("BEST_EDGE",),
    )
    proposal = PortfolioEntryProposal(
        key="btc-long",
        symbol="BTCUSDT",
        venue="bybit",
        strategy="directional-v1",
        engine="directional",
        signed_notional=20_000.0,
        committed_risk_fraction=0.01,
        correlation_checked_symbols=(),
        correlated_symbols=(),
        proposed_at_utc=NOW,
    )
    return ShadowWork(
        observation_id=observation_id,
        meta=meta,
        proposals=(proposal,),
        equity=100_000.0,
    )


def test_uri_round_trips_and_rejects_other_schemes() -> None:
    uri = build_shadow_work_uri("observation-1")
    assert uri == "shadow-work:observation-1"
    assert parse_shadow_work_uri(uri) == "observation-1"
    with pytest.raises(ShadowWorkStoreError, match="scheme"):
        parse_shadow_work_uri("file:///etc/passwd")
    with pytest.raises(ShadowWorkStoreError, match="observation id"):
        build_shadow_work_uri("../escape")
    with pytest.raises(ShadowWorkStoreError, match="observation id"):
        parse_shadow_work_uri("shadow-work:../escape")
    with pytest.raises(ShadowWorkStoreError, match="observation id"):
        parse_shadow_work_uri("shadow-work:sub/dir")


def test_write_then_load_round_trips_wait_and_actionable_work(tmp_path: Path) -> None:
    store = _store(tmp_path)

    for work in (_wait_work(), _actionable_work()):
        uri = store.write(work, written_at_utc=NOW)
        loaded = store.load(uri)
        assert loaded == work


def test_write_is_idempotent_for_identical_payload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    work = _wait_work()
    first_uri = store.write(work, written_at_utc=NOW)
    second_uri = store.write(work, written_at_utc=NOW)
    assert first_uri == second_uri
    assert store.load(first_uri) == work


def test_write_rejects_conflicting_payload_for_same_observation_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write(_wait_work("observation-1"), written_at_utc=NOW)
    conflicting = _wait_work("observation-1").__class__(
        observation_id="observation-1",
        meta=_wait_work().meta,
        proposals=(),
        equity=200_000.0,
    )
    with pytest.raises(ShadowWorkStoreError, match="different content"):
        store.write(conflicting, written_at_utc=NOW)


def test_payload_file_is_written_read_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    uri = store.write(_wait_work(), written_at_utc=NOW)
    observation_id = parse_shadow_work_uri(uri)
    path = tmp_path / f"{observation_id}.json"
    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o440


def test_load_survives_reopen_after_restart(tmp_path: Path) -> None:
    first_store = _store(tmp_path)
    uri = first_store.write(_actionable_work(), written_at_utc=NOW)

    reopened_store = _store(tmp_path)
    assert reopened_store.load(uri) == _actionable_work()


def test_load_rejects_missing_payload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ShadowWorkStoreError, match="not found"):
        store.load("shadow-work:missing-id")


def test_load_rejects_corrupted_checksum(tmp_path: Path) -> None:
    store = _store(tmp_path)
    uri = store.write(_wait_work(), written_at_utc=NOW)
    path = tmp_path / "observation-1.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["equity"] = 999_999.0
    os.chmod(path, 0o640)
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ShadowWorkStoreError, match="checksum mismatch"):
        store.load(uri)


def test_load_rejects_unknown_schema_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    uri = store.write(_wait_work(), written_at_utc=NOW)
    path = tmp_path / "observation-1.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["schema_version"] = SHADOW_WORK_SCHEMA_VERSION + 1
    os.chmod(path, 0o640)
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ShadowWorkStoreError, match="schema version"):
        store.load(uri)


def test_load_rejects_observation_id_mismatch_between_uri_and_payload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write(_wait_work("observation-1"), written_at_utc=NOW)
    path = tmp_path / "observation-1.json"
    store.write(_wait_work("observation-2"), written_at_utc=NOW)
    other_path = tmp_path / "observation-2.json"

    os.chmod(path, 0o640)
    os.chmod(other_path, 0o640)
    path.write_bytes(other_path.read_bytes())

    with pytest.raises(ShadowWorkStoreError, match="does not match its URI"):
        store.load("shadow-work:observation-1")


def test_load_rejects_future_written_at(tmp_path: Path) -> None:
    store = ShadowWorkStore(tmp_path, now_fn=lambda: NOW, clock_skew_tolerance_seconds=1.0)
    uri = store.write(_wait_work(), written_at_utc=NOW + timedelta(seconds=30))
    with pytest.raises(ShadowWorkStoreError, match="future"):
        store.load(uri)


def test_enqueue_shadow_work_is_idempotent_and_loadable_via_the_queue(tmp_path: Path) -> None:
    (tmp_path / "payloads").mkdir()
    store = _store(tmp_path / "payloads")
    queue = DurableShadowQueue(tmp_path / "shadow.sqlite3")
    work = _actionable_work()

    first = enqueue_shadow_work(
        queue=queue, store=store, work=work, written_at_utc=NOW, available_at_utc=NOW
    )
    second = enqueue_shadow_work(
        queue=queue, store=store, work=work, written_at_utc=NOW, available_at_utc=NOW
    )
    assert first is True
    assert second is False

    item = queue.claim(now_utc=NOW, lease_seconds=30)
    assert item is not None
    assert item.item_id == work.observation_id
    assert store.load(item.payload_uri) == work
    queue.acknowledge(item.item_id, completed_at_utc=NOW)
    assert queue.get(item.item_id).status == ShadowQueueStatus.DONE  # type: ignore[union-attr]


def test_load_rejects_symlinked_payload(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (real_dir / "observation-1.json").symlink_to(outside)

    store = _store(real_dir)
    with pytest.raises(ShadowWorkStoreError, match="symlink"):
        store.load("shadow-work:observation-1")


def test_base_dir_must_exist_and_not_be_a_symlink(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ShadowWorkStore(tmp_path / "missing")

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real_dir)
    with pytest.raises(ShadowWorkStoreError, match="symlink"):
        ShadowWorkStore(link)


def test_from_json_safe_rejects_malformed_payload_shapes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    uri = store.write(_wait_work(), written_at_utc=NOW)
    path = tmp_path / "observation-1.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["extra_unexpected_field"] = "surprise"
    del envelope["payload"]["equity"]
    payload_json = json.dumps(envelope["payload"], sort_keys=True, separators=(",", ":"))
    import hashlib

    envelope["payload_sha256"] = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    os.chmod(path, 0o640)
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ShadowWorkStoreError, match="do not match"):
        store.load(uri)
