from datetime import UTC, datetime

import pytest

from scripts.run_scheduled_paper_execution_probe import (
    SCHEDULED_MAXIMUM_NOTIONAL_QUOTE_USD,
    scheduled_identity,
)
from src.execution.paper_execution_probe import HARD_MAXIMUM_NOTIONAL_QUOTE_USD


def test_scheduled_probe_can_accommodate_exchange_minimum_within_hard_cap() -> None:
    assert SCHEDULED_MAXIMUM_NOTIONAL_QUOTE_USD == HARD_MAXIMUM_NOTIONAL_QUOTE_USD
    assert SCHEDULED_MAXIMUM_NOTIONAL_QUOTE_USD == 100


def test_scheduled_identity_is_stable_within_two_hour_slot() -> None:
    first = scheduled_identity(datetime(2026, 8, 30, 10, 5, tzinfo=UTC))
    later = scheduled_identity(datetime(2026, 8, 30, 11, 59, tzinfo=UTC))

    assert first == later
    assert first[0] in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert first[1] == "probe-scheduled-20260830t1000z"


def test_scheduled_identity_rotates_symbol_each_slot() -> None:
    symbols = [
        scheduled_identity(datetime(2026, 8, 30, hour, 5, tzinfo=UTC))[0]
        for hour in (0, 2, 4)
    ]

    assert len(set(symbols)) == 3


def test_scheduled_identity_requires_timezone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        scheduled_identity(datetime(2026, 8, 30, 10, 0))
