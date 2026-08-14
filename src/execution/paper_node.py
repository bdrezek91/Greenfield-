"""Build a NautilusTrader TradingNode wired to Bybit's TESTNET, running one
of this project's existing Strategy classes UNCHANGED.

This realizes the Phase 0 architecture decision directly: the same
strategy code that runs in `src.backtesting.engine` also runs here, live
against Bybit's testnet - only the venue/execution wiring differs, exactly
what NautilusTrader was chosen for (docs/PHASE_0_ARCHITECTURE_RESEARCH.md
section 4).

NOT VERIFIED IN THIS SESSION: this session's network egress policy blocks
api.bybit.com (confirmed via the agent proxy status, not a transient
failure - the same limitation documented in docs/DATA.md for the data
layer). The config objects here are built from NautilusTrader's actual
Bybit adapter classes and are structurally correct as far as this session
can verify (they construct without error), but the live connection has not
been exercised end to end. Validate on a machine with unrestricted network
access (the target VPS, or local dev) before relying on this for real
paper trading - see docs/PROJECT_STATUS.md and docs/VPS_DEPLOYMENT.md.

Bybit API credentials (read-only is enough for PAPER/testnet market data;
trading requires testnet trading keys) come from the BYBIT_API_KEY/
BYBIT_API_SECRET environment variables (see .env.example) - never passed
as literals here.
"""

from __future__ import annotations

from nautilus_trader.adapters.bybit.common.enums import BybitProductType
from nautilus_trader.adapters.bybit.config import BybitDataClientConfig, BybitExecClientConfig
from nautilus_trader.adapters.bybit.factories import (
    BybitLiveDataClientFactory,
    BybitLiveExecClientFactory,
)
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.trading.strategy import Strategy

from src.execution.mode import TradingMode

BYBIT_CLIENT_NAME = "BYBIT"


def build_paper_trading_config(*, trader_id: str = "PAPER-TRADER-001") -> TradingNodeConfig:
    """A TradingNodeConfig wired to Bybit's testnet only. Refuses to build a
    config for anything but PAPER by construction - there is no parameter
    here that can select a live/mainnet venue, so this function cannot
    accidentally be pointed at real money (see src/execution/mode.py for
    the separate, explicit gate that governs a future live-trading path).
    """
    data_config = BybitDataClientConfig(
        product_types=[BybitProductType.LINEAR],
        testnet=True,
    )
    exec_config = BybitExecClientConfig(
        product_types=[BybitProductType.LINEAR],
        testnet=True,
    )
    return TradingNodeConfig(
        trader_id=trader_id,
        data_clients={BYBIT_CLIENT_NAME: data_config},
        exec_clients={BYBIT_CLIENT_NAME: exec_config},
    )


def build_paper_trading_node(
    strategy: Strategy, *, trading_mode: TradingMode, trader_id: str = "PAPER-TRADER-001"
) -> TradingNode:
    """Construct (but do not run) a paper-trading TradingNode. Raises
    ValueError if `trading_mode` is anything but PAPER - this function is
    the Bybit-testnet path only, never a live/mainnet one.
    """
    if trading_mode is not TradingMode.PAPER:
        raise ValueError(
            f"build_paper_trading_node only supports TradingMode.PAPER, got {trading_mode!r}"
        )

    config = build_paper_trading_config(trader_id=trader_id)
    node = TradingNode(config=config)
    node.trader.add_strategy(strategy)
    node.add_data_client_factory(BYBIT_CLIENT_NAME, BybitLiveDataClientFactory)
    node.add_exec_client_factory(BYBIT_CLIENT_NAME, BybitLiveExecClientFactory)
    return node
