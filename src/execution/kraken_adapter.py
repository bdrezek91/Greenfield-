"""ccxt-backed ExecutionAdapter for Kraken Futures.

No NautilusTrader live adapter exists for Kraken (verified directly: the
installed `nautilus_trader==1.221.0` wheel, the latest released on PyPI,
contains zero Kraken-related files - see docs/PROJECT_STATUS.md's exchange
migration entry). This implements `src.execution.adapter.ExecutionAdapter`
directly via `ccxt`'s `krakenfutures` exchange class instead, which does
have full public + authenticated support for Kraken Futures, including a
self-service demo/sandbox environment (`demo-futures.kraken.com`,
confirmed via `ccxt.krakenfutures().urls["test"]`) - the PAPER-mode
counterpart to Bybit's testnet.

NOT VERIFIED IN THIS SESSION: this session's network egress policy blocks
kraken.com (see docs/DATA.md), so no order has actually been submitted
through this adapter here. Structurally correct as far as this session can
verify (ccxt's krakenfutures class exists, exposes create_order and
sandbox mode); validate on a machine with unrestricted network access
before relying on this for real paper/live trading.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from src.data.kraken_client import to_kraken_symbol
from src.execution.adapter import Fill
from src.execution.intent import IntentSide, OrderIntent
from src.execution.mode import TradingMode


class KrakenTransport(Protocol):
    def create_order(
        self, symbol: str, type: str, side: str, amount: float
    ) -> dict[str, Any]: ...


def _default_transport(trading_mode: TradingMode, api_key: str, api_secret: str) -> KrakenTransport:
    import ccxt

    exchange = ccxt.krakenfutures({"apiKey": api_key, "secret": api_secret})
    if trading_mode is TradingMode.PAPER:
        exchange.set_sandbox_mode(True)  # demo-futures.kraken.com
    return exchange


class KrakenExecutionAdapter:
    """Only PAPER (Kraken's demo environment) or LIVE (production) modes
    make sense here - RESEARCH/BACKTEST never submit real orders.
    """

    def __init__(
        self,
        trading_mode: TradingMode,
        api_key: str,
        api_secret: str,
        transport: KrakenTransport | None = None,
    ) -> None:
        if trading_mode not in (TradingMode.PAPER, TradingMode.LIVE):
            raise ValueError(
                f"KrakenExecutionAdapter only supports PAPER or LIVE, got {trading_mode!r}"
            )
        self._trading_mode = trading_mode
        self._transport = transport or _default_transport(trading_mode, api_key, api_secret)

    @property
    def transport(self) -> KrakenTransport:
        """The underlying ccxt exchange (or injected test double) - exposed
        for callers that need authenticated calls beyond `submit()`'s
        scope (e.g. fetching account balance for `equity_fn` in
        scripts/paper_trade.py), so they reuse this adapter's connection
        instead of constructing a second one.
        """
        return self._transport

    def submit(self, intent: OrderIntent) -> Fill:
        side = "buy" if intent.side == IntentSide.BUY else "sell"
        kraken_symbol = to_kraken_symbol(intent.symbol)

        try:
            order = self._transport.create_order(kraken_symbol, "market", side, intent.quantity)
        except Exception as exc:  # noqa: BLE001 - any transport failure is a rejection, not a crash
            return Fill(
                intent=intent,
                filled_price=0.0,
                filled_quantity=0.0,
                filled_at=datetime.now(UTC),
                rejected=True,
                reject_reason=repr(exc),
            )

        filled_price = float(order.get("average") or order.get("price") or intent.reference_price)
        filled_quantity = float(order.get("filled") or 0.0)
        ts_ms = order.get("timestamp")
        filled_at = datetime.fromtimestamp(ts_ms / 1000, tz=UTC) if ts_ms else datetime.now(UTC)

        if filled_quantity <= 0:
            return Fill(
                intent=intent,
                filled_price=0.0,
                filled_quantity=0.0,
                filled_at=filled_at,
                rejected=True,
                reject_reason=f"order accepted but reports zero filled quantity: {order!r}",
            )

        return Fill(
            intent=intent,
            filled_price=filled_price,
            filled_quantity=filled_quantity,
            filled_at=filled_at,
        )
