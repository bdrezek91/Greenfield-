"""Regression test for the real cross-session ordering failure found on
`/opt/greenfield-v2/data`: `iter_raw_events` for `bybit/linear/orderbook/
BTCUSDT` raised `RawStoreError: raw event order regressed or duplicated`
because two soak-session connections' raw parts had overlapping
`receive_ts_ns` ranges. This reproduces that exact shape end to end
through `AtomicRawWriter`/`iter_raw_events` (not just the generic merge
utility in `tests/unit/test_ordered_merge.py`), and proves it now
succeeds, is deterministic on a second run, loses no events, and still
fails closed on genuine intra-connection corruption.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.data.raw_event import parse_bybit_message
from src.data.raw_store import AtomicRawWriter, RawStoreError, load_raw_events


def _orderbook_event(
    *, receive_ts_ns: int, receive_sequence: int, connection_id: str, update_id: int
):
    payload = (
        '{"topic":"orderbook.50.BTCUSDT","type":"delta","ts":1700000000000,'
        f'"data":{{"s":"BTCUSDT","b":[["100","1"]],"a":[["101","1"]],'
        f'"u":{update_id},"seq":{update_id + 10}}}}}'
    )
    return parse_bybit_message(
        payload,
        receive_ts_ns=receive_ts_ns,
        connection_id=connection_id,
        receive_sequence=receive_sequence,
    )


def _write_two_overlapping_sessions(data_dir: Path) -> tuple[list, list]:
    # Same real shape as the phase1-20260825t164500z -> t164933z restart:
    # the old connection's tail flush lands slightly after the new
    # connection's first flush.
    old_session = [
        _orderbook_event(
            receive_ts_ns=1_787_676_323_000_000_000 + i * 100_000_000,
            receive_sequence=293 + i,
            connection_id="old-connection",
            update_id=1000 + i,
        )
        for i in range(5)
    ]
    new_session = [
        _orderbook_event(
            receive_ts_ns=1_787_676_323_166_283_259 + i * 80_000_000,
            receive_sequence=1 + i,
            connection_id="new-connection",
            update_id=2000 + i,
        )
        for i in range(5)
    ]
    writer = AtomicRawWriter(data_dir)
    writer.write(old_session)  # separate flush/process, its own part(s)
    writer.write(new_session)
    return old_session, new_session


def test_overlapping_session_replay_succeeds_and_is_deterministic(tmp_path: Path) -> None:
    old_session, new_session = _write_two_overlapping_sessions(tmp_path)

    first_run = load_raw_events(tmp_path, exchange="bybit", market_type="linear")
    second_run = load_raw_events(tmp_path, exchange="bybit", market_type="linear")

    assert first_run == second_run  # deterministic replay

    observed_ids = {event.event_id for event in first_run}
    expected_ids = {event.event_id for event in old_session + new_session}
    assert observed_ids == expected_ids  # no event lost
    assert len(first_run) == len(old_session) + len(new_session)  # none duplicated

    timestamps = [event.receive_ts_ns for event in first_run]
    assert timestamps == sorted(timestamps)  # globally causal order

    # No event from either connection is placed ahead of the OTHER
    # connection's genuinely earlier events - the actual bug being fixed.
    # Deliberately mismatched lengths (consecutive-pair iteration) - not a
    # candidate for strict=True.
    for earlier, later in zip(first_run, first_run[1:], strict=False):
        assert earlier.receive_ts_ns <= later.receive_ts_ns


def test_genuine_intra_connection_regression_still_fails_closed(tmp_path: Path) -> None:
    # AtomicRawWriter.write() sorts events *within* one call/part, so a
    # within-part regression cannot be constructed through the public API
    # (by design - that's what makes intra-part order trustworthy in the
    # first place, and what makes the cross-connection case above safe to
    # merge by `min_receive_ts_ns`-first processing order). A genuine
    # regression needs two parts from the SAME connection whose ranges
    # overlap out of order: a wide part (50..250) processed first because
    # its min sorts first, then a narrower part (100) from the same
    # connection whose single event falls inside the first part's already-
    # consumed range - real corruption, not a legitimate reconnect, and it
    # must still be rejected.
    writer = AtomicRawWriter(tmp_path)
    writer.write(
        [
            _orderbook_event(
                receive_ts_ns=50_000_000,
                receive_sequence=1,
                connection_id="only-connection",
                update_id=1,
            ),
            _orderbook_event(
                receive_ts_ns=250_000_000,
                receive_sequence=2,
                connection_id="only-connection",
                update_id=2,
            ),
        ]
    )
    writer.write(
        [
            _orderbook_event(
                receive_ts_ns=100_000_000,  # inside the first part's already-consumed range
                receive_sequence=3,
                connection_id="only-connection",
                update_id=3,
            )
        ]
    )

    with pytest.raises(RawStoreError, match="regressed or duplicated"):
        load_raw_events(tmp_path, exchange="bybit", market_type="linear")
