"""build_paper_trading_node/_config must construct correctly and must
refuse anything but PAPER mode.

node.build() constructs real Bybit HTTP/WS client objects (reading
credentials from the environment) but does not open a network connection
until .run() - a real connection attempt is not exercised here.
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
    assert data_config.demo is False
    assert exec_config.demo is False


def test_paper_config_demo_backend() -> None:
    config = build_paper_trading_config(backend="demo")
    data_config = config.data_clients["BYBIT"]
    exec_config = config.exec_clients["BYBIT"]
    assert data_config.demo is True
    assert exec_config.demo is True
    assert data_config.testnet is False
    assert exec_config.testnet is False
    # Demo REST only supports private endpoints - data (public) client is
    # routed to mainnet; exec (account/order) client keeps the demo default.
    assert data_config.base_url_http == "https://api.bybit.com"
    assert exec_config.base_url_http is None


def test_paper_config_testnet_backend_leaves_base_url_http_default() -> None:
    config = build_paper_trading_config()
    data_config = config.data_clients["BYBIT"]
    assert data_config.base_url_http is None


def test_paper_config_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="backend must be one of"):
        build_paper_trading_config(backend="mainnet")


def test_build_node_rejects_non_paper_mode() -> None:
    with pytest.raises(ValueError, match="only supports TradingMode.PAPER"):
        build_paper_trading_node(_strategy(), trading_mode=TradingMode.LIVE)

    with pytest.raises(ValueError, match="only supports TradingMode.PAPER"):
        build_paper_trading_node(_strategy(), trading_mode=TradingMode.BACKTEST)


def test_build_node_succeeds_for_paper_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "dummy-key")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "dummy-secret")
    node = build_paper_trading_node(_strategy(), trading_mode=TradingMode.PAPER)
    try:
        assert str(node.trader_id) == "PAPER-TRADER-001"
    finally:
        node.dispose()


def test_build_node_succeeds_for_demo_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BYBIT_DEMO_API_KEY", "dummy-key")
    monkeypatch.setenv("BYBIT_DEMO_API_SECRET", "dummy-secret")
    node = build_paper_trading_node(_strategy(), trading_mode=TradingMode.PAPER, backend="demo")
    try:
        assert str(node.trader_id) == "PAPER-TRADER-001"
    finally:
        node.dispose()
