"""Causal availability contract for shared feature/regime as-of joins."""

from __future__ import annotations

import pandas as pd
import pytest

from src.features.pipeline import build_feature_matrix
from src.features.point_in_time import PointInTimeJoinError, point_in_time_asof


def _utc(values: list[str]) -> pd.Series:
    return pd.Series(pd.to_datetime(values, utc=True))


def test_delayed_source_is_invisible_until_received() -> None:
    decisions = _utc(["2026-01-01T00:02:00Z", "2026-01-01T00:03:00Z"])
    source = pd.DataFrame(
        {
            "timestamp": _utc(["2026-01-01T00:01:00Z"]),
            "max_source_timestamp": _utc(["2026-01-01T00:03:00Z"]),
            "value": [7.0],
        }
    )

    result = point_in_time_asof(decisions, source, "value")

    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == 7.0


def test_late_old_event_never_rolls_observable_state_backward() -> None:
    decisions = _utc(["2026-01-01T00:02:00Z", "2026-01-01T00:04:00Z"])
    source = pd.DataFrame(
        {
            "timestamp": _utc(["2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z"]),
            "max_source_timestamp": _utc(
                ["2026-01-01T00:04:00Z", "2026-01-01T00:02:00Z"]
            ),
            "value": [1.0, 2.0],
        }
    )

    result = point_in_time_asof(decisions, source, "value")

    assert result.tolist() == [2.0, 2.0]


def test_appended_future_rows_do_not_change_existing_results() -> None:
    decisions = _utc(["2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z"])
    source = pd.DataFrame(
        {
            "timestamp": _utc(["2026-01-01T00:01:00Z"]),
            "max_source_timestamp": _utc(["2026-01-01T00:01:01Z"]),
            "value": [1.0],
        }
    )
    before = point_in_time_asof(decisions, source, "value")
    future = pd.concat(
        [
            source,
            pd.DataFrame(
                {
                    "timestamp": _utc(["2026-01-02T00:00:00Z"]),
                    "max_source_timestamp": _utc(["2026-01-02T00:00:01Z"]),
                    "value": [999.0],
                }
            ),
        ],
        ignore_index=True,
    )

    pd.testing.assert_series_equal(before, point_in_time_asof(decisions, future, "value"))


def test_decision_chunking_does_not_change_results() -> None:
    decisions = _utc(
        [
            "2026-01-01T00:01:00Z",
            "2026-01-01T00:02:00Z",
            "2026-01-01T00:03:00Z",
        ]
    )
    source = pd.DataFrame(
        {
            "timestamp": _utc(["2026-01-01T00:01:00Z", "2026-01-01T00:02:00Z"]),
            "max_source_timestamp": _utc(
                ["2026-01-01T00:01:01Z", "2026-01-01T00:02:01Z"]
            ),
            "value": [1.0, 2.0],
        }
    )
    whole = point_in_time_asof(decisions, source, "value")
    chunked = pd.concat(
        [
            point_in_time_asof(decisions.iloc[:1], source, "value"),
            point_in_time_asof(decisions.iloc[1:], source, "value"),
        ]
    ).sort_index()
    pd.testing.assert_series_equal(whole, chunked)


def test_feature_pipeline_honors_source_availability_not_only_event_time() -> None:
    timestamps = _utc(["2026-01-01T00:02:00Z", "2026-01-01T00:03:00Z"])
    bars = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10.0, 11.0],
        }
    )
    funding = pd.DataFrame(
        {
            "timestamp": _utc(["2026-01-01T00:01:00Z"]),
            "max_source_timestamp": _utc(["2026-01-01T00:03:00Z"]),
            "funding_rate": [0.001],
        }
    )

    features = build_feature_matrix(bars, funding=funding)

    assert pd.isna(features.loc[0, "funding_rate"])
    assert features.loc[1, "funding_rate"] == 0.001


def test_legacy_source_uses_event_timestamp_as_availability() -> None:
    decisions = _utc(["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"])
    source = pd.DataFrame(
        {"timestamp": _utc(["2026-01-01T00:01:00Z"]), "value": [3.0]}
    )
    result = point_in_time_asof(decisions, source, "value")
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == 3.0


def test_ambiguous_or_invalid_lineage_fails_closed() -> None:
    decisions = _utc(["2026-01-01T00:02:00Z"])
    duplicate = pd.DataFrame(
        {
            "timestamp": _utc(["2026-01-01T00:01:00Z", "2026-01-01T00:01:00Z"]),
            "value": [1.0, 2.0],
        }
    )
    with pytest.raises(PointInTimeJoinError, match="unique"):
        point_in_time_asof(decisions, duplicate, "value")

    invalid = pd.DataFrame(
        {
            "timestamp": _utc(["2026-01-01T00:01:00Z"]),
            "max_source_timestamp": ["not-a-timestamp"],
            "value": [1.0],
        }
    )
    with pytest.raises(PointInTimeJoinError, match="must be valid"):
        point_in_time_asof(decisions, invalid, "value")


def test_bucket_close_after_all_sources_is_available_only_at_bucket_timestamp() -> None:
    decisions = _utc(["2026-01-01T00:00:59Z", "2026-01-01T00:01:00Z"])
    source = pd.DataFrame(
        {
            "timestamp": _utc(["2026-01-01T00:01:00Z"]),
            "max_source_timestamp": _utc(["2026-01-01T00:00:58Z"]),
            "value": [5.0],
        }
    )
    result = point_in_time_asof(decisions, source, "value")
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == 5.0
