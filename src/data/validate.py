"""Data integrity checks required before any dataset is used for research.

See docs/DATA.md. Every check returns the offending rows/timestamps rather
than raising, so a caller can decide whether an issue is fatal or just worth
logging (e.g. a single incomplete trailing candle is expected, not an error).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.data.config import TIMEFRAME_MS

_MAX_ABS_RETURN_BY_TIMEFRAME = {"1d": 0.75}
_DEFAULT_MAX_ABS_RETURN = 0.50


@dataclass
class ValidationReport:
    timeframe: str
    missing_candle_gaps: list[tuple[pd.Timestamp, pd.Timestamp, int]] = field(
        default_factory=list
    )
    duplicate_timestamps: list[pd.Timestamp] = field(default_factory=list)
    zero_volume_timestamps: list[pd.Timestamp] = field(default_factory=list)
    anomalous_price_timestamps: list[pd.Timestamp] = field(default_factory=list)
    non_utc: bool = False
    incomplete_trailing_candle: pd.Timestamp | None = None

    @property
    def is_valid(self) -> bool:
        """Fatal-only check: duplicates, gaps, non-UTC timestamps, and price
        anomalies block use of the dataset. Zero volume and a still-forming
        trailing candle are expected/benign and are reported but not fatal.
        """
        return not (self.missing_candle_gaps or self.duplicate_timestamps or self.non_utc
                    or self.anomalous_price_timestamps)


def check_utc(df: pd.DataFrame) -> bool:
    tz = df["timestamp"].dt.tz
    return tz is not None and str(tz) == "UTC"


def check_duplicates(df: pd.DataFrame) -> list[pd.Timestamp]:
    dupes = df.loc[df["timestamp"].duplicated(keep=False), "timestamp"]
    return sorted(dupes.unique().tolist())


def check_missing_candles(
    df: pd.DataFrame, timeframe: str
) -> list[tuple[pd.Timestamp, pd.Timestamp, int]]:
    """Return (gap_start, gap_end, missing_count) for every break in the
    expected fixed-interval sequence of candle timestamps.
    """
    if len(df) < 2:
        return []
    step_ms = TIMEFRAME_MS[timeframe]
    step = pd.Timedelta(milliseconds=step_ms)
    ts = df["timestamp"].sort_values().reset_index(drop=True)
    diffs = ts.diff().dropna()
    gaps: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    for idx in diffs[diffs > step].index:
        prev_ts = ts.iloc[idx - 1]
        curr_ts = ts.iloc[idx]
        missing = int((curr_ts - prev_ts) / step) - 1
        gaps.append((prev_ts, curr_ts, missing))
    return gaps


def check_zero_volume(df: pd.DataFrame) -> list[pd.Timestamp]:
    return df.loc[df["volume"] == 0, "timestamp"].sort_values().tolist()


def check_anomalous_prices(df: pd.DataFrame, max_abs_return: float = 0.5) -> list[pd.Timestamp]:
    """Flag candles whose close-to-close return exceeds `max_abs_return`
    (default 50%) - a crude but effective guard against bad ticks/splits.
    Also flags candles where high < low or any OHLC value is <= 0.
    """
    ts_sorted = df.sort_values("timestamp")
    returns = ts_sorted["close"].pct_change().abs()
    bad_returns = ts_sorted.loc[returns > max_abs_return, "timestamp"]

    bad_range = ts_sorted.loc[ts_sorted["high"] < ts_sorted["low"], "timestamp"]
    non_positive = ts_sorted.loc[
        (ts_sorted[["open", "high", "low", "close"]] <= 0).any(axis=1), "timestamp"
    ]
    combined = pd.concat([bad_returns, bad_range, non_positive]).drop_duplicates()
    return sorted(combined.tolist())


def check_incomplete_trailing_candle(
    df: pd.DataFrame, timeframe: str, now: pd.Timestamp
) -> pd.Timestamp | None:
    """The most recent candle is still forming if its bar hasn't closed yet."""
    if df.empty:
        return None
    step = pd.Timedelta(milliseconds=TIMEFRAME_MS[timeframe])
    last_ts = df["timestamp"].max()
    if last_ts + step > now:
        return last_ts
    return None


def validate_dataset(
    df: pd.DataFrame, timeframe: str, now: pd.Timestamp | None = None
) -> ValidationReport:
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    return ValidationReport(
        timeframe=timeframe,
        missing_candle_gaps=check_missing_candles(df, timeframe),
        duplicate_timestamps=check_duplicates(df),
        zero_volume_timestamps=check_zero_volume(df),
        anomalous_price_timestamps=check_anomalous_prices(
            df,
            max_abs_return=_MAX_ABS_RETURN_BY_TIMEFRAME.get(
                timeframe, _DEFAULT_MAX_ABS_RETURN
            ),
        ),
        non_utc=not check_utc(df),
        incomplete_trailing_candle=check_incomplete_trailing_candle(df, timeframe, now),
    )
