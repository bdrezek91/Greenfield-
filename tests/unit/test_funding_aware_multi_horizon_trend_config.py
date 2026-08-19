"""FundingAwareMultiHorizonTrendConfig has no safe default for
higher_bar_type or data_dir (same pattern as CrossAssetMomentumConfig's
reference_bar_type and FundingContrarianConfig's data_dir respectively) -
validated loudly in __post_init__/__init__, never silently defaulted.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, OrderSide, PriceType
from nautilus_trader.model.identifiers import InstrumentId

from src.data.storage import write_funding
from src.strategies.funding_aware_multi_horizon_trend import (
    FundingAwareMultiHorizonTrend,
    FundingAwareMultiHorizonTrendConfig,
)

_INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
_BAR_TYPE_4H = BarType(
    _INSTRUMENT_ID,
    BarSpecification(4, BarAggregation.HOUR, PriceType.LAST),
    AggregationSource.EXTERNAL,
)
_BAR_TYPE_1D = BarType(
    _INSTRUMENT_ID,
    BarSpecification(1, BarAggregation.DAY, PriceType.LAST),
    AggregationSource.EXTERNAL,
)


def _write_funding(data_dir: Path, periods: int = 40) -> None:
    ts = pd.date_range("2025-01-01", periods=periods, freq="8h", tz="UTC")
    write_funding(
        pd.DataFrame({"timestamp": ts, "symbol": "BTCUSDT", "funding_rate": 0.0001}), data_dir
    )


def test_missing_higher_bar_type_raises() -> None:
    with pytest.raises(ValueError, match="higher_bar_type"):
        FundingAwareMultiHorizonTrendConfig(
            instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE_4H, data_dir="/tmp"
        )


def test_missing_data_dir_raises() -> None:
    with pytest.raises(ValueError, match="data_dir"):
        FundingAwareMultiHorizonTrendConfig(
            instrument_id=_INSTRUMENT_ID, bar_type=_BAR_TYPE_4H, higher_bar_type=_BAR_TYPE_1D
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lookback_bars_4h", 1),
        ("lookback_bars_1d", 1),
        ("funding_zscore_lookback", 1),
        ("funding_zscore_threshold", 0.0),
        ("funding_zscore_threshold", -1.0),
    ],
)
def test_invalid_numeric_params_raise(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        FundingAwareMultiHorizonTrendConfig(
            instrument_id=_INSTRUMENT_ID,
            bar_type=_BAR_TYPE_4H,
            higher_bar_type=_BAR_TYPE_1D,
            data_dir="/tmp",
            **{field: value},
        )


def test_missing_funding_data_on_disk_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="funding"):
        FundingAwareMultiHorizonTrend(
            FundingAwareMultiHorizonTrendConfig(
                instrument_id=_INSTRUMENT_ID,
                bar_type=_BAR_TYPE_4H,
                higher_bar_type=_BAR_TYPE_1D,
                data_dir=str(tmp_path),
            )
        )


def test_funding_veto_only_fires_on_a_genuine_outlier(tmp_path: Path) -> None:
    """Direct unit-level check of `_funding_vetoes`, isolated from engine
    timing/sizing noise: a single funding observation far outside its own
    lookback window (z-score ~3.0, see the arithmetic this value is
    derived from - spiking 1 of `funding_zscore_lookback` points to M
    while the rest sit near 0 gives z -> sqrt((n-1)) as M grows, here
    n=10) vetoes a BUY at the threshold used by the frozen prereg (2.0),
    but the identical window with no spike does not - and a SELL is never
    vetoed by a positive-direction outlier (only a BUY paying the extreme
    long-side funding is)."""
    ts = pd.date_range("2025-01-01", periods=20, freq="8h", tz="UTC")
    # Deterministic small alternation (not random noise, to keep this test
    # free of any seed-dependent flukiness): bounded variation, no z-score
    # anywhere near 2.0 on its own.
    baseline = pd.Series(
        [0.0001 if i % 2 == 0 else 0.00011 for i in range(len(ts))], index=ts
    )
    spiked = baseline.copy()
    spiked.iloc[9] = 0.05  # index 9 = the 10th (most recent) point of a 10-window ending at index 9

    def _funding_df(rates: pd.Series) -> pd.DataFrame:
        return pd.DataFrame(
            {"timestamp": ts, "symbol": "BTCUSDT", "funding_rate": rates.to_numpy()}
        )

    write_funding(_funding_df(baseline), tmp_path / "flat")
    write_funding(_funding_df(spiked), tmp_path / "spiked")

    decision_ts_ns = int(ts[9].value) + 1  # strictly after the spike observation itself

    flat_strategy = FundingAwareMultiHorizonTrend(
        FundingAwareMultiHorizonTrendConfig(
            instrument_id=_INSTRUMENT_ID,
            bar_type=_BAR_TYPE_4H,
            higher_bar_type=_BAR_TYPE_1D,
            data_dir=str(tmp_path / "flat"),
            funding_zscore_lookback=10,
            funding_zscore_threshold=2.0,
        )
    )
    assert flat_strategy._funding_vetoes(OrderSide.BUY, decision_ts_ns) is False

    spiked_strategy = FundingAwareMultiHorizonTrend(
        FundingAwareMultiHorizonTrendConfig(
            instrument_id=_INSTRUMENT_ID,
            bar_type=_BAR_TYPE_4H,
            higher_bar_type=_BAR_TYPE_1D,
            data_dir=str(tmp_path / "spiked"),
            funding_zscore_lookback=10,
            funding_zscore_threshold=2.0,
        )
    )
    assert spiked_strategy._funding_vetoes(OrderSide.BUY, decision_ts_ns) is True
    # The outlier is on the positive (long-paying) side only - a short
    # would be paid, not charged, by it, so it is never vetoed by this.
    assert spiked_strategy._funding_vetoes(OrderSide.SELL, decision_ts_ns) is False


def test_valid_config_and_data_constructs(tmp_path: Path) -> None:
    _write_funding(tmp_path)
    strategy = FundingAwareMultiHorizonTrend(
        FundingAwareMultiHorizonTrendConfig(
            instrument_id=_INSTRUMENT_ID,
            bar_type=_BAR_TYPE_4H,
            higher_bar_type=_BAR_TYPE_1D,
            data_dir=str(tmp_path),
        )
    )
    assert strategy.config.lookback_bars_4h == 60  # default preserved
    assert strategy.config.lookback_bars_1d == 10
    assert len(strategy._funding) == 40
