"""Bronze parts are immutable, atomic, checksummed, and replayable."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.data.raw_event import parse_bybit_message
from src.data.raw_store import (
    AtomicRawWriter,
    RawStoreError,
    discover_manifests,
    load_raw_events,
    verify_raw_part,
)


def _event(receive_ts_ns: int, *, symbol: str = "BTCUSDT", update_id: int = 1):
    payload = (
        f'{{"topic":"orderbook.50.{symbol}","type":"snapshot","ts":1700000000000,'
        f'"data":{{"s":"{symbol}","b":[["100","1"]],'
        f'"a":[["101","1"]],"u":{update_id},"seq":{update_id + 10}}}}}'
    )
    return parse_bybit_message(
        payload, receive_ts_ns=receive_ts_ns, connection_id="connection-1"
    )


def test_atomic_writer_round_trips_and_verifies_manifest(tmp_path: Path) -> None:
    writer = AtomicRawWriter(tmp_path)
    events = [_event(1_700_000_000_000_000_002), _event(1_700_000_000_000_000_001, update_id=2)]

    manifests = writer.write(events)

    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest.row_count == 2
    assert manifest.part_path.startswith("raw/v1/exchange=bybit/market=linear/")
    assert Path(tmp_path / manifest.part_path).is_file()
    assert Path(tmp_path / manifest.manifest_path).is_file()
    verify_raw_part(tmp_path, manifest)
    assert load_raw_events(tmp_path) == sorted(
        events,
        key=lambda event: (event.receive_ts_ns, event.receive_sequence, event.event_id),
    )


def test_writer_partitions_by_symbol_and_channel(tmp_path: Path) -> None:
    control = parse_bybit_message(
        '{"success":true,"op":"subscribe"}', receive_ts_ns=1_700_000_000_000_000_003,
        connection_id="connection-1"
    )

    manifests = AtomicRawWriter(tmp_path).write(
        [
            _event(1_700_000_000_000_000_001),
            _event(1_700_000_000_000_000_002, symbol="ETHUSDT"),
            control,
        ]
    )

    assert {(item.channel, item.symbol) for item in manifests} == {
        ("orderbook", "BTCUSDT"),
        ("orderbook", "ETHUSDT"),
        ("control", "ALL"),
    }
    assert len(discover_manifests(tmp_path, symbol="ETHUSDT")) == 1


def test_discovery_prunes_unrelated_partitions_before_parsing(tmp_path: Path) -> None:
    manifest = AtomicRawWriter(tmp_path).write(
        [_event(1_700_000_000_000_000_001)]
    )[0]
    unrelated = (
        tmp_path
        / "raw/v1/exchange=okx/market=linear/channel=trades"
        / "symbol=ETHUSDT/date=2023-11-14/corrupt.manifest.json"
    )
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("not-json", encoding="utf-8")

    discovered = discover_manifests(
        tmp_path,
        exchange="bybit",
        market_type="linear",
        channel="orderbook",
        symbol="BTCUSDT",
    )

    assert discovered == [manifest]


def test_discovery_rejects_unsafe_filter_component(tmp_path: Path) -> None:
    with pytest.raises(RawStoreError, match="unsafe raw partition"):
        discover_manifests(tmp_path, symbol="../BTCUSDT")


def test_identical_batch_write_is_idempotent(tmp_path: Path) -> None:
    writer = AtomicRawWriter(tmp_path)
    events = [_event(1_700_000_000_000_000_001)]

    first = writer.write(events)
    second = writer.write(events)

    assert first == second
    assert len(list(tmp_path.rglob("*.parquet"))) == 1


def test_tampered_part_fails_closed(tmp_path: Path) -> None:
    manifest = AtomicRawWriter(tmp_path).write([_event(1_700_000_000_000_000_001)])[0]
    part_path = tmp_path / manifest.part_path
    with part_path.open("ab") as handle:
        handle.write(b"tamper")

    with pytest.raises(RawStoreError, match="checksum mismatch"):
        verify_raw_part(tmp_path, manifest)


def test_empty_batch_is_a_noop(tmp_path: Path) -> None:
    assert AtomicRawWriter(tmp_path).write([]) == []


def test_unsafe_partition_component_is_rejected(tmp_path: Path) -> None:
    event = parse_bybit_message(
        '{"topic":"publicTrade../escape","type":"snapshot","data":[]}',
        receive_ts_ns=1_700_000_000_000_000_001,
        connection_id="connection-1",
    )

    with pytest.raises(RawStoreError, match="unsafe raw partition"):
        AtomicRawWriter(tmp_path).write([event])
