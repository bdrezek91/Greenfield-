from __future__ import annotations

from nautilus_trader.model.enums import OrderSide

from src.strategies.signals import momentum_signal


class TestMomentumSignal:
    def test_none_with_insufficient_history(self) -> None:
        assert momentum_signal([100.0, 101.0], lookback_bars=10, threshold=0.01) is None

    def test_buy_above_positive_threshold(self) -> None:
        closes = [100.0] * 10 + [102.0]  # 11 values, lookback=10
        assert momentum_signal(closes, lookback_bars=10, threshold=0.01) == OrderSide.BUY

    def test_sell_below_negative_threshold(self) -> None:
        closes = [100.0] * 10 + [98.0]
        assert momentum_signal(closes, lookback_bars=10, threshold=0.01) == OrderSide.SELL

    def test_none_within_dead_zone(self) -> None:
        closes = [100.0] * 10 + [100.5]  # 0.5% change, under the 1% threshold
        assert momentum_signal(closes, lookback_bars=10, threshold=0.01) is None

    def test_boundary_is_exclusive(self) -> None:
        closes = [100.0] * 10 + [101.0]  # exactly 1% change
        assert momentum_signal(closes, lookback_bars=10, threshold=0.01) is None
