"""Point-in-time contracts for research-safe market datasets and features."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

_TIMEFRAME_DURATIONS = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}


class PointInTimeError(ValueError):
    """A dataset or feature row violates its availability-time contract."""


@dataclass(frozen=True, slots=True)
class ClosedKlineReport:
    timeframe: str
    as_of_utc: str
    input_rows: int
    eligible_rows: int
    excluded_unclosed_rows: int
    max_source_timestamp_utc: str | None
    max_close_timestamp_utc: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FeatureRowProvenance:
    """Minimum lineage carried by every future Gold feature row."""

    schema_version: int
    feature_set: str
    feature_timestamp_ns: int
    max_source_timestamp_ns: int
    code_version: str
    dataset_version: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise PointInTimeError("unsupported feature provenance schema")
        if not self.feature_set or not self.code_version or not self.dataset_version:
            raise PointInTimeError("feature, code, and dataset versions are required")
        if self.feature_timestamp_ns <= 0 or self.max_source_timestamp_ns <= 0:
            raise PointInTimeError("feature provenance timestamps must be positive")
        if self.max_source_timestamp_ns > self.feature_timestamp_ns:
            raise PointInTimeError("future source timestamp cannot enter a feature row")

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def select_closed_klines(
    frame: pd.DataFrame,
    *,
    timeframe: str,
    as_of: pd.Timestamp,
) -> tuple[pd.DataFrame, ClosedKlineReport]:
    """Return only candles whose full interval was knowable at ``as_of``."""
    if timeframe not in _TIMEFRAME_DURATIONS:
        raise PointInTimeError(f"unsupported timeframe: {timeframe!r}")
    if "timestamp" not in frame.columns:
        raise PointInTimeError("kline frame requires a timestamp column")
    as_of_utc = _utc_timestamp(as_of, "as_of")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    if timestamps.isna().any():
        raise PointInTimeError("kline timestamps cannot be null")
    if timestamps.duplicated().any():
        raise PointInTimeError("duplicate kline timestamps are not point-in-time safe")

    close_timestamps = timestamps + _TIMEFRAME_DURATIONS[timeframe]
    eligible_mask = close_timestamps <= as_of_utc
    eligible = frame.loc[eligible_mask].copy()
    eligible["timestamp"] = timestamps.loc[eligible_mask]
    eligible = eligible.sort_values("timestamp").reset_index(drop=True)
    eligible_closes = close_timestamps.loc[eligible_mask]
    report = ClosedKlineReport(
        timeframe=timeframe,
        as_of_utc=as_of_utc.isoformat(),
        input_rows=len(frame),
        eligible_rows=len(eligible),
        excluded_unclosed_rows=int((~eligible_mask).sum()),
        max_source_timestamp_utc=(
            None if eligible.empty else pd.Timestamp(eligible["timestamp"].max()).isoformat()
        ),
        max_close_timestamp_utc=(
            None if eligible_closes.empty else pd.Timestamp(eligible_closes.max()).isoformat()
        ),
    )
    return eligible, report


def _utc_timestamp(value: pd.Timestamp, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise PointInTimeError(f"{name} must be timezone-aware")
    return timestamp.tz_convert("UTC")
