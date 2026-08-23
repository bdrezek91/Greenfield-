"""Bronze raw-lake storage report: read-only usage/age aggregation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from src.data.raw_event import parse_bybit_message
from src.data.raw_storage_report import build_raw_storage_report, write_raw_storage_report
from src.data.raw_store import AtomicRawWriter


def _event(receive_ts_ns: int, update_id: int, *, symbol: str = "BTCUSDT"):
    payload = json.dumps(
        {
            "topic": f"orderbook.50.{symbol}",
            "type": "snapshot",
            "ts": 1_700_000_000_000,
            "data": {
                "s": symbol,
                "b": [["100", "1"]],
                "a": [["101", "1"]],
                "u": update_id,
                "seq": update_id,
            },
        },
        separators=(",", ":"),
    )
    return parse_bybit_message(
        payload,
        receive_ts_ns=receive_ts_ns,
        receive_sequence=update_id,
        connection_id="connection-1",
    )


# 2023-11-14T22:13:20Z
_DAY_ONE_NS = 1_700_000_000_000_000_000
# 2023-11-16T00:53:20Z (about 30 hours later - a distinct UTC date)
_DAY_TWO_NS = 1_700_100_000_000_000_000


def test_report_aggregates_by_exchange_market_type_channel_and_symbol(tmp_path: Path) -> None:
    writer = AtomicRawWriter(tmp_path)
    writer.write([_event(_DAY_ONE_NS + 1, 1, symbol="BTCUSDT")])
    writer.write([_event(_DAY_ONE_NS + 2, 2, symbol="BTCUSDT")])
    writer.write([_event(_DAY_ONE_NS + 3, 3, symbol="ETHUSDT")])

    now = datetime.fromtimestamp(_DAY_TWO_NS / 1_000_000_000, tz=UTC)
    report = build_raw_storage_report(tmp_path, now_utc=now)

    assert report.total_part_count == 3
    assert report.total_row_count == 3
    assert report.total_bytes > 0
    groups_by_symbol = {g.symbol: g for g in report.groups}
    assert set(groups_by_symbol) == {"BTCUSDT", "ETHUSDT"}
    btc = groups_by_symbol["BTCUSDT"]
    assert btc.exchange == "bybit"
    assert btc.market_type == "linear"
    assert btc.channel == "orderbook"
    assert btc.part_count == 2
    assert btc.row_count == 2
    assert btc.total_bytes > 0


def test_report_computes_partition_age_in_days(tmp_path: Path) -> None:
    writer = AtomicRawWriter(tmp_path)
    writer.write([_event(_DAY_ONE_NS + 1, 1)])
    now = datetime.fromtimestamp(_DAY_TWO_NS / 1_000_000_000, tz=UTC)

    report = build_raw_storage_report(tmp_path, now_utc=now)

    assert len(report.groups) == 1
    assert report.groups[0].oldest_partition_age_days >= 1
    assert report.groups[0].oldest_utc_date <= report.groups[0].newest_utc_date


def test_report_exchange_filter_excludes_other_exchanges(tmp_path: Path) -> None:
    writer = AtomicRawWriter(tmp_path)
    writer.write([_event(_DAY_ONE_NS + 1, 1)])
    now = datetime.fromtimestamp(_DAY_TWO_NS / 1_000_000_000, tz=UTC)

    matching = build_raw_storage_report(tmp_path, now_utc=now, exchange="bybit")
    other = build_raw_storage_report(tmp_path, now_utc=now, exchange="okx")

    assert matching.total_part_count == 1
    assert other.total_part_count == 0
    assert other.groups == ()


def test_report_on_empty_lake_is_all_zero(tmp_path: Path) -> None:
    now = datetime.now(UTC)

    report = build_raw_storage_report(tmp_path, now_utc=now)

    assert report.total_part_count == 0
    assert report.total_row_count == 0
    assert report.total_bytes == 0
    assert report.groups == ()


def test_naive_now_is_rejected(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="timezone-aware"):
        build_raw_storage_report(tmp_path, now_utc=datetime(2026, 1, 1))


def test_write_report_is_atomic_and_overwritable(tmp_path: Path) -> None:
    writer = AtomicRawWriter(tmp_path)
    writer.write([_event(_DAY_ONE_NS + 1, 1)])
    now = datetime.fromtimestamp(_DAY_TWO_NS / 1_000_000_000, tz=UTC)
    report = build_raw_storage_report(tmp_path, now_utc=now)

    path = write_raw_storage_report(tmp_path, report)
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["total_part_count"] == 1

    # a regenerated report overwrites the same path cleanly (not immutable
    # evidence like manifests/quality reports - see module docstring)
    second_path = write_raw_storage_report(tmp_path, report)
    assert second_path == path
    assert not list(tmp_path.glob("**/*.tmp"))


def test_report_counts_a_manifest_with_a_missing_part_file_as_zero_bytes(
    tmp_path: Path,
) -> None:
    writer = AtomicRawWriter(tmp_path)
    manifest = writer.write([_event(_DAY_ONE_NS + 1, 1)])[0]
    (tmp_path / manifest.part_path).unlink()
    now = datetime.fromtimestamp(_DAY_TWO_NS / 1_000_000_000, tz=UTC)

    report = build_raw_storage_report(tmp_path, now_utc=now)

    assert report.total_part_count == 1
    assert report.groups[0].total_bytes == 0
