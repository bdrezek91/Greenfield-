"""build_paper_trading_node/_config must construct correctly (no network
call happens until an actual .run()) and must refuse anything but PAPER mode.
"""

from __future__ import annotations

import pytest
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType

from src.backtesting.instruments import instrument_id_for
from src.execution.mode import TradingMode
from src.execution.paper_node import build_paper_trading_config, build_paper_trading_node
from src.strategies.trend_following import TrendFollowing, TrendFollowingConfig


def _strategy() -> TrendFollowing:
    iid = instrument_id_for("BTCUSDT")
    bar_type = BarType(
        iid, BarSpecification(1, BarAggregation.HOUR, PriceType.LAST), AggregationSource.EXTERNAL
    )
    return TrendFollowing(TrendFollowingConfig(instrument_id=iid, bar_type=bar_type))


def test_paper_config_is_testnet_only() -> None:
    config = build_paper_trading_config()
    data_config = config.data_clients["BYBIT"]
    exec_config = config.exec_clients["BYBIT"]
    assert data_config.testnet is True
    assert exec_config.testnet is True


def test_build_node_rejects_non_paper_mode() -> None:
    with pytest.raises(ValueError, match="only supports TradingMode.PAPER"):
        build_paper_trading_node(_strategy(), trading_mode=TradingMode.LIVE)

    with pytest.raises(ValueError, match="only supports TradingMode.PAPER"):
        build_paper_trading_node(_strategy(), trading_mode=TradingMode.BACKTEST)


def test_build_node_succeeds_for_paper_mode() -> None:
    node = build_paper_trading_node(_strategy(), trading_mode=TradingMode.PAPER)
    try:
        assert str(node.trader_id) == "PAPER-TRADER-001"
    finally:
        node.dispose()
