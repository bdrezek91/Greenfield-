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
    account they may hold. Both data and exec clients use testnet
    credentials (BYBIT_TESTNET_API_KEY/BYBIT_TESTNET_API_SECRET).
  - "demo": Bybit's Demo Trading feature (api-demo.bybit.com) for account/
    order actions, reachable from an existing regular bybit.com login
    (avatar menu -> "Demo Trading") with no separate site registration, so
    it is not subject to the testnet.bybit.com EU registration block.
    Isolated, virtual-funds account with its own dedicated API keys
    (BYBIT_DEMO_API_KEY/BYBIT_DEMO_API_SECRET) - no funds are at risk.
    CONFIRMED LIVE: api-demo.bybit.com's REST API only supports
    private/account endpoints - public market-data calls (e.g. GET
    /v5/market/instruments-info, needed to even discover an instrument
    exists) reject with "Demo trading are not supported.", and Bybit's
    HTTP client attaches whatever API key is configured to every request
    including nominally public ones, so a demo key sent to mainnet is
    rejected as "API key is invalid." rather than being silently ignored.
    There is no way to make the data client "demo" and have it work. So in
    "demo" mode, only the EXEC client (orders/positions/balance) is
    actually configured as demo; the DATA client (market data - public,
    read-only, carries no funds risk regardless of which account
    authenticates it) is a plain mainnet client and needs its own real
    BYBIT_API_KEY/BYBIT_API_SECRET from the user's regular bybit.com
    account - a key with "Tylko do snapshotu" (read-only/snapshot)
    permissions is sufficient and cannot place orders or move funds.

NOT VERIFIED IN THIS SESSION: this session's network egress policy blocks
api.bybit.com (confirmed via the agent proxy status, not a transient
failure - the same limitation documented in docs/DATA.md for the data
layer). The config objects here are built from NautilusTrader's actual
Bybit adapter classes and are structurally correct as far as this session
can verify (they construct without error); the "testnet" backend's live
connection has not been exercised end to end (validate on the VPS/local
dev first). The "demo" backend WAS exercised end to end on the VPS during
development (see docs/PROJECT_STATUS.md) and the fixes above reflect what
that testing found.

Bybit API credentials come from environment variables (see .env.example),
never passed as literals here: BYBIT_TESTNET_API_KEY/
BYBIT_TESTNET_API_SECRET for "testnet" (both clients); for "demo",
BYBIT_DEMO_API_KEY/BYBIT_DEMO_API_SECRET (exec client) plus a real mainnet
BYBIT_API_KEY/BYBIT_API_SECRET (data client, read-only permissions
suffice). This env-var split is enforced by NautilusTrader's own Bybit
adapter, not by this module.
"""

from __future__ import annotations

from nautilus_trader.adapters.bybit.common.constants import BYBIT_VENUE
from nautilus_trader.adapters.bybit.common.enums import BybitProductType
from nautilus_trader.adapters.bybit.config import BybitDataClientConfig, BybitExecClientConfig
from nautilus_trader.adapters.bybit.factories import (
    BybitLiveDataClientFactory,
    BybitLiveExecClientFactory,
)
from nautilus_trader.config import (
    InstrumentProviderConfig,
    LiveExecEngineConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.trading.strategy import Strategy

from src.execution.mode import TradingMode

BYBIT_CLIENT_NAME = "BYBIT"


def live_instrument_id_for(symbol: str) -> InstrumentId:
    """Bybit's REAL instrument ID convention for USDT-margined linear
    perpetuals, e.g. `BTCUSDT-LINEAR.BYBIT` - as loaded live from Bybit's
    own instruments-info endpoint (confirmed: 821 real instruments loaded).

    This is deliberately NOT `src.backtesting.instruments.instrument_id_for`
    (which returns `BTCUSDT-PERP.BYBIT`, a self-consistent synthetic ID
    used only within the backtest engine's own placeholder instrument
    definitions, e.g. no real Bybit venue data is ever consulted there).
    Using the backtest-only helper for a live/paper subscription silently
    fails: the strategy calls subscribe_bars() for an instrument_id the
    live cache doesn't have (it has the real `-LINEAR` ID instead), so
    nothing errors, but no bars ever arrive - confirmed live on the VPS.
    """
    return InstrumentId(Symbol(f"{symbol}-LINEAR"), BYBIT_VENUE)
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

    # Without this, BybitInstrumentProvider loads zero instruments (its
    # default is load_all=False, load_ids=None) and a strategy's
    # subscribe_bars() for e.g. BTCUSDT-PERP.BYBIT silently never
    # subscribes, since the client doesn't know the instrument exists.
    instrument_provider = InstrumentProviderConfig(load_all=True)

    data_config = BybitDataClientConfig(
        product_types=[BybitProductType.LINEAR],
        # Market data is never "demo" - see module docstring: Bybit's
        # api-demo.bybit.com REST only supports private/account endpoints,
        # so the data client (public market data only) is always a plain
        # testnet-or-mainnet client, authenticated with its own real
        # BYBIT_API_KEY/BYBIT_API_SECRET when backend="demo".
        testnet=backend == "testnet",
        demo=False,
        instrument_provider=instrument_provider,
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
        # CRITICAL, confirmed live: if startup execution reconciliation
        # fails, nautilus_trader's kernel.start_async() returns early and
        # NEVER calls trader.start() - so strategy.on_start() (and thus
        # subscribe_bars()) silently never runs. The node still logs
        # "RUNNING" (that happens unconditionally one level up in
        # node.run_async()), so from the outside it looks alive but does
        # nothing, forever. A stale order on the Bybit account with an
        # order-type combination nautilus_trader's enum parser doesn't
        # recognize (confirmed: (Market, StopLoss, Buy, RisesTo)) makes
        # reconciliation fail every time. Since a fresh PAPER session has
        # no in-flight state of its own to reconcile, disable it here
        # rather than depend on the account's order history being clean.
        exec_engine=LiveExecEngineConfig(reconciliation=False),
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
    node.build()
    return node
