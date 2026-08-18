"""Pure-Python parts of the walk-forward framework: window generation and
equity-curve stitching. The engine-driving parts (run_walk_forward,
_select_params) are covered by tests/integration/test_walk_forward.py.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.backtesting.walk_forward import _stitch_equity_curves, generate_windows


def test_generate_windows_basic_boundaries() -> None:
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-01-21", tz="UTC")
    windows = generate_windows(
        start,
        end,
        train_period=pd.Timedelta(days=10),
        validation_period=pd.Timedelta(days=5),
        test_period=pd.Timedelta(days=5),
    )
    assert len(windows) == 1
    w = windows[0]
    assert w.train_start == start
    assert w.train_end == start + pd.Timedelta(days=10)
    assert w.validation_start == w.train_end
    assert w.validation_end == w.train_end + pd.Timedelta(days=5)
    assert w.test_start == w.validation_end
    assert w.test_end == end


def test_generate_windows_slides_by_test_period() -> None:
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-02-10", tz="UTC")
    windows = generate_windows(
        start,
        end,
        train_period=pd.Timedelta(days=10),
        validation_period=pd.Timedelta(days=5),
        test_period=pd.Timedelta(days=5),
    )
    assert len(windows) > 1
    for i in range(1, len(windows)):
        assert windows[i].train_start == windows[i - 1].train_start + pd.Timedelta(days=5)
    # Consecutive TEST windows must be contiguous (no gaps/overlaps).
    for i in range(1, len(windows)):
        assert windows[i].test_start == windows[i - 1].test_end


def test_generate_windows_too_short_range_returns_empty() -> None:
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-01-05", tz="UTC")
    windows = generate_windows(
        start,
        end,
        train_period=pd.Timedelta(days=10),
        validation_period=pd.Timedelta(days=5),
        test_period=pd.Timedelta(days=5),
    )
    assert windows == []


@pytest.mark.parametrize(
    "train,validation,test",
    [
        (pd.Timedelta(0), pd.Timedelta(days=1), pd.Timedelta(days=1)),
        (pd.Timedelta(days=1), pd.Timedelta(0), pd.Timedelta(days=1)),
        (pd.Timedelta(days=1), pd.Timedelta(days=1), pd.Timedelta(0)),
    ],
)
def test_generate_windows_rejects_non_positive_periods(train, validation, test) -> None:
    start = pd.Timestamp("2024-01-01", tz="UTC")
    end = pd.Timestamp("2024-02-01", tz="UTC")
    with pytest.raises(ValueError):
        generate_windows(start, end, train, validation, test)


def test_stitch_equity_curves_compounds_returns_across_windows() -> None:
    idx1 = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    seg1 = pd.Series([1000.0, 1100.0, 1210.0], index=idx1)  # +10%, +10%

    idx2 = pd.date_range("2024-01-04", periods=3, freq="D", tz="UTC")
    seg2 = pd.Series([1000.0, 900.0, 990.0], index=idx2)  # -10%, +10% fresh run

    stitched = _stitch_equity_curves([seg1, seg2], starting_balance=1000.0)

    # The first bar of every segment is retained (including any first-bar
    # costs); the second segment's fresh 1000 baseline maps to carried 1210.
    expected = [1000.0, 1100.0, 1210.0, 1210.0, 1089.0, 1197.9]
    assert stitched.tolist() == pytest.approx(expected, rel=1e-9)


def test_stitch_equity_curves_single_segment() -> None:
    idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    seg = pd.Series([1000.0, 1050.0, 1000.0], index=idx)
    stitched = _stitch_equity_curves([seg], starting_balance=1000.0)
    assert stitched.tolist() == pytest.approx([1000.0, 1050.0, 1000.0])


def test_stitch_equity_curves_empty_input_returns_empty() -> None:
    stitched = _stitch_equity_curves([], starting_balance=1000.0)
    assert stitched.empty


def test_stitch_equity_curves_skips_empty_segments() -> None:
    idx = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC")
    seg = pd.Series([1000.0, 1100.0], index=idx)
    stitched = _stitch_equity_curves([pd.Series(dtype=float), seg], starting_balance=1000.0)
    assert stitched.tolist() == pytest.approx([1000.0, 1100.0])


def test_generate_windows_applies_purge_and_embargo_without_overlap() -> None:
    start = pd.Timestamp("2024-01-01", tz="UTC")
    windows = generate_windows(
        start,
        pd.Timestamp("2024-02-01", tz="UTC"),
        pd.Timedelta(days=10),
        pd.Timedelta(days=5),
        pd.Timedelta(days=5),
        purge_bars=2,
        embargo_bars=1,
        timeframe="4h",
    )
    window = windows[0]
    expected_gap = pd.Timedelta(hours=12)
    assert window.validation_start - window.train_end == expected_gap
    assert window.test_start - window.validation_end == expected_gap
    assert window.train_end < window.validation_start < window.validation_end < window.test_start
