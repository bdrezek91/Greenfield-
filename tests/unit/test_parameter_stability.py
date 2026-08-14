"""flag_isolated_spikes must catch the section-20 overfitting pattern
(a lone great parameter surrounded by mediocre neighbors) and leave a
smooth, stable region unflagged.
"""

from __future__ import annotations

import pytest

from src.analytics.robustness import flag_isolated_spikes


def test_smooth_ridge_is_never_flagged() -> None:
    params = [48.0, 49.0, 50.0, 51.0, 52.0]
    metrics = [1.0, 1.2, 1.4, 1.3, 1.1]  # smooth hill, no isolated spike
    assert flag_isolated_spikes(params, metrics) == [False] * 5


def test_isolated_spike_is_flagged() -> None:
    # The RSI=51.382-but-not-50-or-52 pattern from section 20.
    params = [50.0, 51.0, 51.382, 52.0, 53.0]
    metrics = [0.3, 0.4, 3.0, 0.35, 0.32]
    flags = flag_isolated_spikes(params, metrics)
    assert flags == [False, False, True, False, False]


def test_endpoints_are_never_flagged() -> None:
    params = [1.0, 2.0, 3.0]
    metrics = [10.0, 0.1, 0.1]  # endpoint "spike" has only one neighbor
    assert flag_isolated_spikes(params, metrics) == [False, False, False]


def test_flat_metrics_never_flagged() -> None:
    params = [1.0, 2.0, 3.0, 4.0]
    metrics = [1.0, 1.0, 1.0, 1.0]
    assert flag_isolated_spikes(params, metrics) == [False] * 4


def test_non_positive_neighbor_average_is_skipped_not_flagged() -> None:
    params = [1.0, 2.0, 3.0]
    metrics = [-1.0, 5.0, -1.0]  # neighbor_avg = -1, meaningless ratio
    assert flag_isolated_spikes(params, metrics) == [False, False, False]


def test_spike_ratio_threshold_is_configurable() -> None:
    params = [1.0, 2.0, 3.0]
    metrics = [1.0, 1.8, 1.0]  # 1.8 vs neighbor avg 1.0 -> ratio 1.8
    assert flag_isolated_spikes(params, metrics, spike_ratio=2.0) == [False, False, False]
    assert flag_isolated_spikes(params, metrics, spike_ratio=1.5) == [False, True, False]


def test_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError):
        flag_isolated_spikes([1.0, 2.0], [1.0])
