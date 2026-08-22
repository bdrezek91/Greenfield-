"""Point-in-time gates exclude open candles and reject feature leakage."""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.point_in_time import (
    FeatureRowProvenance,
    PointInTimeError,
    select_closed_klines,
)


def test_current_one_minute_candle_is_excluded() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-08-22T18:50:00Z", "2026-08-22T18:51:00Z", "2026-08-22T18:52:00Z"]
            ),
            "close": [1.0, 2.0, 3.0],
        }
    )

    eligible, report = select_closed_klines(
        frame,
        timeframe="1m",
        as_of=pd.Timestamp("2026-08-22T18:52:00Z"),
    )

    assert eligible["close"].tolist() == [1.0, 2.0]
    assert report.input_rows == 3
    assert report.eligible_rows == 2
    assert report.excluded_unclosed_rows == 1
    assert report.max_close_timestamp_utc == "2026-08-22T18:52:00+00:00"


def test_daily_candle_uses_full_close_boundary() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-08-21T00:00:00Z", "2026-08-22T00:00:00Z"]),
            "close": [1.0, 2.0],
        }
    )

    eligible, report = select_closed_klines(
        frame,
        timeframe="1d",
        as_of=pd.Timestamp("2026-08-22T18:52:00Z"),
    )

    assert eligible["close"].tolist() == [1.0]
    assert report.excluded_unclosed_rows == 1


def test_duplicate_or_naive_time_is_rejected() -> None:
    duplicated = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2026-01-01T00:00:00Z"] * 2)}
    )
    with pytest.raises(PointInTimeError, match="duplicate"):
        select_closed_klines(
            duplicated, timeframe="1m", as_of=pd.Timestamp("2026-01-02T00:00:00Z")
        )
    with pytest.raises(PointInTimeError, match="timezone-aware"):
        select_closed_klines(
            duplicated.iloc[:1], timeframe="1m", as_of=pd.Timestamp("2026-01-02")
        )


def test_feature_provenance_rejects_future_source() -> None:
    accepted = FeatureRowProvenance(
        schema_version=1,
        feature_set="microstructure-v1",
        feature_timestamp_ns=200,
        max_source_timestamp_ns=200,
        code_version="commit-sha",
        dataset_version="dataset-sha",
    )
    assert accepted.max_source_timestamp_ns == 200

    with pytest.raises(PointInTimeError, match="future source"):
        FeatureRowProvenance(
            schema_version=1,
            feature_set="microstructure-v1",
            feature_timestamp_ns=199,
            max_source_timestamp_ns=200,
            code_version="commit-sha",
            dataset_version="dataset-sha",
        )
