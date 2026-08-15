"""klines_to_bars must convert canonical OHLCV frames into valid, ordered Nautilus Bars."""

import pandas as pd
import pytest

from src.backtesting.data_adapter import bar_type_for, klines_to_bars
from src.backtesting.instruments import build_crypto_perpetual, load_instrument_specs
from src.data.schema import COLUMNS


def _klines(n: int = 5, timeframe: str = "1h") -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
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
    )[list(COLUMNS)]


@pytest.fixture
def instrument():
    specs = load_instrument_specs()
    return build_crypto_perpetual("BTCUSDT", specs)


def test_bar_type_for_known_timeframes(instrument) -> None:
    bar_type = bar_type_for(instrument, "1h")
    assert "1-HOUR" in str(bar_type)


def test_bar_type_for_unknown_timeframe_raises(instrument) -> None:
    with pytest.raises(ValueError, match="2h"):
        bar_type_for(instrument, "2h")


def test_klines_to_bars_count_and_order(instrument) -> None:
    df = _klines(n=10)
    bars = klines_to_bars(df, instrument, "1h")

    assert len(bars) == 10
    timestamps = [b.ts_event for b in bars]
    assert timestamps == sorted(timestamps)


def test_klines_to_bars_prices_round_trip(instrument) -> None:
    df = _klines(n=3)
    bars = klines_to_bars(df, instrument, "1h")

    assert float(bars[0].open) == df["open"].iloc[0]
    assert float(bars[0].close) == df["close"].iloc[0]


def test_klines_to_bars_empty_frame_returns_empty_list(instrument) -> None:
    df = _klines(n=0)
    assert klines_to_bars(df, instrument, "1h") == []
