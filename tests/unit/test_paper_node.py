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
from src.execution.paper_node import (
    build_paper_trading_config,
    build_paper_trading_node,
    live_instrument_id_for,
)
from src.strategies.trend_following import TrendFollowing, TrendFollowingConfig


def test_live_instrument_id_uses_bybit_linear_suffix() -> None:
    # The real Bybit instrument catalog uses "-LINEAR", not the backtest
    # engine's synthetic "-PERP" (src.backtesting.instruments.instrument_id_for) -
    # confirmed live: subscribing with the wrong suffix silently never
    # receives bars, since the live cache has no instrument under that ID.
    assert str(live_instrument_id_for("BTCUSDT")) == "BTCUSDT-LINEAR.BYBIT"


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
    # Bybit's Demo Trading REST only supports private/account endpoints, so
    # only the exec (account/order) client is actually "demo" - the data
    # (public market data) client is a plain mainnet client, see module
    # docstring in src/execution/paper_node.py.
    assert data_config.demo is False
    assert data_config.testnet is False
    assert exec_config.demo is True
    assert exec_config.testnet is False


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
    # The "demo" backend's data (public market data) client is a plain
    # mainnet client - see module docstring in src/execution/paper_node.py.
    monkeypatch.setenv("BYBIT_API_KEY", "dummy-key")
    monkeypatch.setenv("BYBIT_API_SECRET", "dummy-secret")
    node = build_paper_trading_node(_strategy(), trading_mode=TradingMode.PAPER, backend="demo")
    try:
        assert str(node.trader_id) == "PAPER-TRADER-001"
    finally:
        node.dispose()
