"""Regression test for the real cross-session ordering failure found while
materializing production Gold: `materialize_daily_trade_microstructure` for
`BTCUSDT/2026-08-25` raised `OrderFlowError: trade stream is not strictly
ordered`, the Silver-layer counterpart to the raw-layer bug covered by
`tests/data_integrity/test_cross_session_raw_replay.py`. Two soak-session
connections' Silver parts had overlapping `receive_ts_ns`/`event_ts_ms`
ranges once the manifest-min-timestamp sort concatenated them naively.
This reproduces that shape end to end through
`materialize_daily_trade_microstructure` and proves it now qualifies,
loses no trades, is deterministic, and still fails closed on genuine
intra-connection corruption.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.data.normalized_event import normalize_bybit_event
from src.data.normalized_store import AtomicNormalizedWriter
from src.data.raw_event import parse_bybit_message
from src.features.materialization import (
    GoldMaterializationError,
    materialize_daily_trade_microstructure,
)

_UTC_DATE = "2023-11-15"


def _write_trade(
    root: Path,
    *,
    sequence: int,
    event_ts_ms: int,
    receive_ts_ns: int,
    receive_sequence: int,
    connection_id: str,
    side: str,
    price: str,
) -> None:
    raw = parse_bybit_message(
        json.dumps(
            {
                "topic": "publicTrade.BTCUSDT",
                "type": "snapshot",
                "ts": event_ts_ms + 10,
                "data": [
                    {
                        "T": event_ts_ms,
                        "s": "BTCUSDT",
                        "S": side,
                        "v": "1",
                        "p": price,
                        "i": f"trade-{connection_id}-{sequence}",
                    }
                ],
            },
            separators=(",", ":"),
        ),
        receive_ts_ns=receive_ts_ns,
        receive_sequence=receive_sequence,
        connection_id=connection_id,
    )
    manifest = AtomicNormalizedWriter(root).write_source_part(
        list(normalize_bybit_event(raw)),
        source_events_sha256=f"{connection_id}-{sequence}".encode().hex()[:64].ljust(64, "0"),
        source_part_path=f"raw/{connection_id}-{sequence}.parquet",
        utc_date=_UTC_DATE,
    )
    assert manifest is not None


def _write_overlapping_session_day(root: Path) -> tuple[int, int]:
    day_start_ms = int(pd.Timestamp(_UTC_DATE, tz="UTC").timestamp() * 1000)
    # Same real shape as the 2026-08-25 restart: the old connection's tail
    # (parts sorted first by min_receive_ts_ns) actually extends past the
    # new connection's already-flushed head.
    old_events = [
        (day_start_ms + 100 + i * 1000, (day_start_ms + 100 + i * 1000 + 50) * 1_000_000, 40 + i)
        for i in range(4)
    ]
    new_events = [
        (day_start_ms + 2500 + i * 1000, (day_start_ms + 2500 + i * 1000 - 400) * 1_000_000, 1 + i)
        for i in range(4)
    ]
    for i, (event_ms, receive_ns, seq) in enumerate(old_events, start=1):
        _write_trade(
            root,
            sequence=i,
            event_ts_ms=event_ms,
            receive_ts_ns=receive_ns,
            receive_sequence=seq,
            connection_id="old-connection",
            side="Buy",
            price="100.0",
        )
    for i, (event_ms, receive_ns, seq) in enumerate(new_events, start=1):
        _write_trade(
            root,
            sequence=i,
            event_ts_ms=event_ms,
            receive_ts_ns=receive_ns,
            receive_sequence=seq,
            connection_id="new-connection",
            side="Sell",
            price="100.5",
        )
    return len(old_events), len(new_events)


def _build(root: Path):
    return materialize_daily_trade_microstructure(
        root,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        utc_date=_UTC_DATE,
        as_of=pd.Timestamp("2023-11-16T00:00:00Z"),
        code_version="commit-1",
        price_tick="0.1",
        bucket_ms=60_000,
    )


def test_overlapping_session_gold_materialization_qualifies_and_is_deterministic(
    tmp_path: Path,
) -> None:
    old_count, new_count = _write_overlapping_session_day(tmp_path)

    first = _build(tmp_path)
    second = _build(tmp_path)

    assert first.qualified is True
    assert first.source_row_count == old_count + new_count  # no trade lost
    assert first == second  # deterministic replay


def test_genuine_cross_part_regression_within_one_connection_still_fails_closed(
    tmp_path: Path,
) -> None:
    # Manifests are sorted by min_receive_ts_ns, but the ordering that
    # actually matters downstream is event_ts_ms-first. Two single-event
    # parts from the SAME connection where event_ts_ms and receive_ts_ns
    # disagree in direction is real corruption (a connection's own events
    # must be causally ordered on both axes) - construct it directly
    # rather than relying on manifest sort order alone.
    day_start_ms = int(pd.Timestamp(_UTC_DATE, tz="UTC").timestamp() * 1000)
    _write_trade(
        tmp_path,
        sequence=1,
        event_ts_ms=day_start_ms + 5000,  # later exchange time
        receive_ts_ns=(day_start_ms + 1000) * 1_000_000,  # but sorts first by receive time
        receive_sequence=1,
        connection_id="only-connection",
        side="Buy",
        price="100.0",
    )
    _write_trade(
        tmp_path,
        sequence=2,
        event_ts_ms=day_start_ms + 1000,  # earlier exchange time
        receive_ts_ns=(day_start_ms + 2000) * 1_000_000,  # but sorts second by receive time
        receive_sequence=2,
        connection_id="only-connection",
        side="Buy",
        price="100.0",
    )

    with pytest.raises(GoldMaterializationError, match="not strictly ordered"):
        _build(tmp_path)
