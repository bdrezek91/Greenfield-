"""Build a NautilusTrader TradingNode wired to a Bybit non-mainnet backend
(TESTNET or DEMO), running one of this project's existing Strategy classes
UNCHANGED.

This realizes the Phase 0 architecture decision directly: the same
strategy code that runs in `src.backtesting.engine` also runs here, live
against a Bybit simulation backend - only the venue/execution wiring
differs, exactly what NautilusTrader was chosen for
(docs/PHASE_0_ARCHITECTURE_RESEARCH.md section 4).

Two PAPER backends are supported, both simulated (virtual funds, no real
money at risk regardless of which is used):

  - "testnet" (default): Bybit's testnet.bybit.com / api-testnet.bybit.com.
    Requires a *separate* testnet.bybit.com account registration, which is
    geo-blocked for some EU users independent of any regular bybit.com
    account they may hold.
  - "demo": Bybit's Demo Trading feature (api-demo.bybit.com). Reachable
    from an existing regular bybit.com login (avatar menu -> "Demo
    Trading") with no separate site registration, so it is not subject to
    the testnet.bybit.com EU registration block. It is still an isolated,
    virtual-funds account with its own dedicated API keys
    (BYBIT_DEMO_API_KEY/BYBIT_DEMO_API_SECRET) - real mainnet keys/funds
    are never involved. Some advanced order features available over the
    testnet WebSocket Trade API are not available in demo mode (NautilusTrader
    automatically falls back to HTTP for order operations there).

NOT VERIFIED IN THIS SESSION: this session's network egress policy blocks
api.bybit.com (confirmed via the agent proxy status, not a transient
failure - the same limitation documented in docs/DATA.md for the data
layer). The config objects here are built from NautilusTrader's actual
Bybit adapter classes and are structurally correct as far as this session
can verify (they construct without error), but the live connection has not
been exercised end to end. Validate on a machine with unrestricted network
access (the target VPS, or local dev) before relying on this for real
paper trading - see docs/PROJECT_STATUS.md and docs/VPS_DEPLOYMENT.md.

Bybit API credentials come from environment variables (see .env.example),
never passed as literals here: BYBIT_API_KEY/BYBIT_API_SECRET for
"testnet", BYBIT_DEMO_API_KEY/BYBIT_DEMO_API_SECRET for "demo" (this
env-var split, and the mutual exclusivity of testnet/demo, is enforced by
NautilusTrader's own Bybit adapter, not by this module).
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
VALID_PAPER_BACKENDS = ("testnet", "demo")


def build_paper_trading_config(
    *, trader_id: str = "PAPER-TRADER-001", backend: str = "testnet"
) -> TradingNodeConfig:
    """A TradingNodeConfig wired to a Bybit simulation backend only
    ("testnet" or "demo", see module docstring). Refuses to build a config
    for anything but PAPER by construction - there is no parameter here
    that can select a live/mainnet venue, so this function cannot
    accidentally be pointed at real money (see src/execution/mode.py for
    the separate, explicit gate that governs a future live-trading path).
    """
    if backend not in VALID_PAPER_BACKENDS:
        raise ValueError(f"backend must be one of {VALID_PAPER_BACKENDS}, got {backend!r}")
    is_demo = backend == "demo"

    data_config = BybitDataClientConfig(
        product_types=[BybitProductType.LINEAR],
        testnet=not is_demo,
        demo=is_demo,
    )
    exec_config = BybitExecClientConfig(
        product_types=[BybitProductType.LINEAR],
        testnet=not is_demo,
        demo=is_demo,
    )
    return TradingNodeConfig(
        trader_id=trader_id,
        data_clients={BYBIT_CLIENT_NAME: data_config},
        exec_clients={BYBIT_CLIENT_NAME: exec_config},
    )


def build_paper_trading_node(
    strategy: Strategy,
    *,
    trading_mode: TradingMode,
    trader_id: str = "PAPER-TRADER-001",
    backend: str = "testnet",
) -> TradingNode:
    """Construct (but do not run) a paper-trading TradingNode. Raises
    ValueError if `trading_mode` is anything but PAPER - this function is
    a Bybit-simulation-only path ("testnet" or "demo" backend), never a
    live/mainnet one.
    """
    if trading_mode is not TradingMode.PAPER:
        raise ValueError(
            f"build_paper_trading_node only supports TradingMode.PAPER, got {trading_mode!r}"
        )

    config = build_paper_trading_config(trader_id=trader_id, backend=backend)
    node = TradingNode(config=config)
    node.trader.add_strategy(strategy)
    node.add_data_client_factory(BYBIT_CLIENT_NAME, BybitLiveDataClientFactory)
    node.add_exec_client_factory(BYBIT_CLIENT_NAME, BybitLiveExecClientFactory)
    return node
