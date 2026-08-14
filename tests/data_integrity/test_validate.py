"""Data integrity checks must catch each class of problem listed in docs/DATA.md."""

import pandas as pd
import pytest

from src.data.validate import (
    check_anomalous_prices,
    check_duplicates,
    check_incomplete_trailing_candle,
    check_missing_candles,
    check_utc,
    check_zero_volume,
    validate_dataset,
)


def _clean_frame(n: int = 10, start: str = "2024-01-01", timeframe: str = "1h") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [10.0] * n,
            "turnover": [1000.0] * n,
            "symbol": "BTCUSDT",
            "timeframe": timeframe,
        }
    )


def test_clean_dataset_is_valid() -> None:
    df = _clean_frame()
    report = validate_dataset(df, "1h", now=df["timestamp"].max() + pd.Timedelta(hours=2))
    assert report.is_valid
    assert not report.missing_candle_gaps
    assert not report.duplicate_timestamps
    assert not report.anomalous_price_timestamps
    assert not report.non_utc


def test_detects_missing_candles() -> None:
    df = _clean_frame(n=10)
    df = df.drop(df.index[3:5]).reset_index(drop=True)  # remove two consecutive candles
    gaps = check_missing_candles(df, "1h")
    assert len(gaps) == 1
    _, _, missing_count = gaps[0]
    assert missing_count == 2


def test_detects_duplicates() -> None:
    df = _clean_frame(n=5)
    df = pd.concat([df, df.iloc[[2]]], ignore_index=True)
    dupes = check_duplicates(df)
    assert len(dupes) == 1
    assert dupes[0] == df["timestamp"].iloc[2]


def test_detects_zero_volume() -> None:
    df = _clean_frame(n=5)
    df.loc[1, "volume"] = 0
    zero_vol = check_zero_volume(df)
    assert len(zero_vol) == 1


def test_detects_anomalous_price_jump() -> None:
    df = _clean_frame(n=5)
    df.loc[3, "close"] = df.loc[2, "close"] * 5  # 400% jump, way above threshold
    anomalies = check_anomalous_prices(df)
    assert df["timestamp"].iloc[3] in anomalies


def test_detects_high_below_low() -> None:
    df = _clean_frame(n=3)
    df.loc[1, "high"] = df.loc[1, "low"] - 1
    anomalies = check_anomalous_prices(df)
    assert df["timestamp"].iloc[1] in anomalies


def test_detects_non_utc_timestamps() -> None:
    df = _clean_frame(n=3)
    df["timestamp"] = df["timestamp"].dt.tz_convert("Etc/GMT-5")  # fixed offset, no tzdata needed
    assert check_utc(df) is False


def test_detects_incomplete_trailing_candle() -> None:
    df = _clean_frame(n=3)
    now = df["timestamp"].max() + pd.Timedelta(minutes=30)  # bar hasn't closed yet
    incomplete = check_incomplete_trailing_candle(df, "1h", now)
    assert incomplete == df["timestamp"].max()


def test_complete_trailing_candle_not_flagged() -> None:
    df = _clean_frame(n=3)
    now = df["timestamp"].max() + pd.Timedelta(hours=2)  # bar has closed
    incomplete = check_incomplete_trailing_candle(df, "1h", now)
    assert incomplete is None


def test_gaps_and_duplicates_make_dataset_invalid() -> None:
    df = _clean_frame(n=10)
    df = df.drop(df.index[3]).reset_index(drop=True)
    report = validate_dataset(df, "1h", now=df["timestamp"].max() + pd.Timedelta(hours=2))
    assert not report.is_valid


def test_zero_volume_alone_does_not_invalidate_dataset() -> None:
    df = _clean_frame(n=5)
    df.loc[1, "volume"] = 0
    report = validate_dataset(df, "1h", now=df["timestamp"].max() + pd.Timedelta(hours=2))
    assert report.is_valid
    assert report.zero_volume_timestamps


@pytest.mark.parametrize("n", [0, 1])
def test_handles_tiny_frames_without_error(n: int) -> None:
    df = _clean_frame(n=n)
    report = validate_dataset(df, "1h")
    assert report.missing_candle_gaps == []
