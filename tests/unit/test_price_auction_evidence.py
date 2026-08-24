"""src.engines.price_auction_evidence's PRICE_AUCTION ConfirmationFamily
evidence producer (Cycle 45 - fourth FamilyEvidence producer). Uses a
directly hand-shaped merged frame (timestamp/poc/vah/val/close) matching
what a real caller would build by as-of joining
rolling_volume_profile_frame's output onto its own OHLCV close series -
the same lighter-weight fixture convention as
tests/unit/test_order_flow_evidence.py (Cycle 43); rolling_volume_
profile_frame's own correctness is independently covered by
tests/unit/test_auction_features.py.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.engines.contracts import ConfirmationFamily
from src.engines.price_auction_evidence import price_auction_family_evidence

NOW = pd.Timestamp("2026-01-01T12:00:00Z")


def _row(
    *, close: float, poc: float = 100.0, vah: float = 101.0, val: float = 99.0
) -> pd.DataFrame:
    return pd.DataFrame(
        {"timestamp": [NOW], "poc": [poc], "vah": [vah], "val": [val], "close": [close]}
    )


def test_close_above_value_area_gets_positive_score() -> None:
    evidence = price_auction_family_evidence(_row(close=103.0))  # vah=101, val=99, width=2

    assert evidence is not None
    assert evidence.family == ConfirmationFamily.PRICE_AUCTION
    assert evidence.score > 0
    assert "above the value area" in evidence.rationale


def test_close_below_value_area_gets_negative_score() -> None:
    evidence = price_auction_family_evidence(_row(close=97.0))

    assert evidence is not None
    assert evidence.score < 0
    assert "below the value area" in evidence.rationale


def test_close_inside_value_area_gets_exactly_zero_score() -> None:
    evidence = price_auction_family_evidence(_row(close=100.0))

    assert evidence is not None
    assert evidence.score == 0.0
    assert "in balance" in evidence.rationale


def test_larger_breakout_produces_a_larger_magnitude_score() -> None:
    small = price_auction_family_evidence(_row(close=101.5))  # 0.25x width above vah
    large = price_auction_family_evidence(_row(close=105.0))  # 2x width above vah

    assert small is not None
    assert large is not None
    assert large.score > small.score > 0


def test_nan_inputs_return_none() -> None:
    row = _row(close=float("nan"))

    assert price_auction_family_evidence(row) is None


def test_degenerate_value_area_returns_none_not_a_division_error() -> None:
    row = _row(close=100.0, vah=99.0, val=99.0)  # vah <= val, width not positive

    assert price_auction_family_evidence(row) is None


def test_empty_frame_returns_none() -> None:
    empty = _row(close=100.0).iloc[:0]

    assert price_auction_family_evidence(empty) is None


def test_missing_required_columns_raises() -> None:
    bad = pd.DataFrame({"timestamp": [NOW]})
    with pytest.raises(ValueError, match="missing columns"):
        price_auction_family_evidence(bad)
