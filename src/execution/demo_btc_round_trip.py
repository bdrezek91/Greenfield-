"""Crash-safe, explicitly armed BTC buy/close infrastructure test on Bybit Demo."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from src.execution.bybit_demo_gateway import (
    BYBIT_DEMO_REST_URL,
    BYBIT_PUBLIC_REST_URL,
    BybitDemoGateway,
    BybitPublicLinearMarketData,
    DemoPositionSnapshot,
    DemoPreflightReport,
    PublicLinearInstrumentSnapshot,
)
from src.execution.demo_operator import require_demo_paper_environment
from src.execution.demo_order_reconciler import (
    DemoExecutionLagError,
    DemoOrderReconciler,
    demo_order_link_id_for,
)
from src.execution.intent import IntentSide
from src.execution.paper_reconciliation import (
    PaperOrderRecord,
    PaperOrderState,
    PaperOrderStore,
    PaperPositionRecord,
    PaperReconciliationError,
)

BTC_ROUND_TRIP_CONFIRMATION_ENV_VAR = "GREENFIELD_DEMO_BTC_ROUND_TRIP_CONFIRMATION"
BTC_ROUND_TRIP_CONFIRMATION_VALUE = "BTC_100_USDT_100X_DEMO_ONLY"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SYMBOL = "BTCUSDT"
_TARGET_NOTIONAL = Decimal("100")
_MINIMUM_NOTIONAL = Decimal("75")
_MAXIMUM_NOTIONAL = Decimal("125")
_LEVERAGE = 100
_MAX_CLOSE_ATTEMPTS = 3


class DemoBtcRoundTripPhase(StrEnum):
    ENTRY_UNRESOLVED = "ENTRY_UNRESOLVED"
    ENTRY_REJECTED = "ENTRY_REJECTED"
    CLOSE_UNRESOLVED = "CLOSE_UNRESOLVED"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class DemoBtcRoundTripRequest:
    request_id: str

    def __post_init__(self) -> None:
        if not _REQUEST_ID.fullmatch(self.request_id):
            raise ValueError("BTC Demo round-trip request_id must match [A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True, slots=True)
class DemoBtcRoundTripResult:
    phase: DemoBtcRoundTripPhase
    preflight: DemoPreflightReport
    market: PublicLinearInstrumentSnapshot
    leverage: int
    target_notional_quote: Decimal
    submitted_quantity: Decimal
    estimated_entry_notional_quote: Decimal
    entry_order: PaperOrderRecord
    close_orders: tuple[PaperOrderRecord, ...]
    exchange_position_size: Decimal
    paper_position: PaperPositionRecord | None


class DemoBtcRoundTripCoordinator:
    def __init__(
        self,
        *,
        gateway: BybitDemoGateway,
        public_market: BybitPublicLinearMarketData,
        store: PaperOrderStore,
    ) -> None:
        if gateway.endpoint != BYBIT_DEMO_REST_URL:
            raise ValueError("BTC round-trip execution gateway must be pinned to Bybit Demo")
        if public_market.endpoint != BYBIT_PUBLIC_REST_URL:
            raise ValueError(
                "BTC round-trip public data must be pinned to Bybit mainnet public API"
            )
        self.gateway = gateway
        self.public_market = public_market
        self.store = store
        self.reconciler = DemoOrderReconciler(gateway=gateway, store=store)

    def advance(
        self,
        request: DemoBtcRoundTripRequest,
        *,
        env: Mapping[str, str],
        now_utc: datetime | None = None,
    ) -> DemoBtcRoundTripResult:
        require_demo_paper_environment(env, order_submission=True)
        if (
            env.get(BTC_ROUND_TRIP_CONFIRMATION_ENV_VAR)
            != BTC_ROUND_TRIP_CONFIRMATION_VALUE
        ):
            raise ValueError(
                f"BTC Demo round-trip requires {BTC_ROUND_TRIP_CONFIRMATION_ENV_VAR}="
                f"{BTC_ROUND_TRIP_CONFIRMATION_VALUE}"
            )
        now = (now_utc or datetime.now(UTC)).astimezone(UTC)
        preflight = self.gateway.preflight()
        market = self.public_market.instrument_snapshot(symbol=_SYMBOL)
        quantity = _bounded_quantity(market)
        entry = self._entry(request, market=market, quantity=quantity, now_utc=now)
        try:
            entry, _, _ = self.reconciler.reconcile(entry.client_order_id)
        except DemoExecutionLagError:
            entry = self._durable_order(entry.client_order_id)
            return self._close_during_entry_execution_lag(
                request=request,
                preflight=preflight,
                market=market,
                entry=entry,
                now_utc=now,
            )
        quantity = Decimal(str(entry.quantity))

        if entry.state is PaperOrderState.REJECTED:
            return self._result(
                DemoBtcRoundTripPhase.ENTRY_REJECTED,
                preflight,
                market,
                quantity,
                entry,
                (),
            )
        if entry.state not in {PaperOrderState.FILLED, PaperOrderState.CANCELED}:
            return self._result(
                DemoBtcRoundTripPhase.ENTRY_UNRESOLVED,
                preflight,
                market,
                quantity,
                entry,
                (),
            )
        if entry.filled_quantity <= 0:
            raise PaperReconciliationError("terminal BTC Demo entry has no fill to close")
        if entry.average_fill_price is None:
            raise PaperReconciliationError("filled BTC Demo entry has no average fill price")

        close_orders: list[PaperOrderRecord] = []
        for attempt in range(1, _MAX_CLOSE_ATTEMPTS + 1):
            exchange_size = _long_position_size(self.gateway.fetch_positions(symbol=_SYMBOL))
            existing_close = self._existing_close(request, attempt=attempt)
            if exchange_size == 0 and existing_close is None:
                return self._complete(preflight, market, quantity, entry, close_orders)
            if exchange_size > Decimal(str(entry.filled_quantity)) + Decimal("0.000000001"):
                raise PaperReconciliationError(
                    "Bybit Demo BTC position exceeds the round-trip entry fill"
                )
            close = self._close_attempt(
                request,
                attempt=attempt,
                quantity=exchange_size,
                reference_price=Decimal(str(entry.average_fill_price)),
                now_utc=now,
            )
            try:
                close, _, _ = self.reconciler.reconcile(close.client_order_id)
            except DemoExecutionLagError:
                close = self._durable_order(close.client_order_id)
                close_orders.append(close)
                return self._result(
                    DemoBtcRoundTripPhase.CLOSE_UNRESOLVED,
                    preflight,
                    market,
                    quantity,
                    entry,
                    close_orders,
                )
            close_orders.append(close)
            if close.state not in {
                PaperOrderState.FILLED,
                PaperOrderState.CANCELED,
                PaperOrderState.REJECTED,
            }:
                return self._result(
                    DemoBtcRoundTripPhase.CLOSE_UNRESOLVED,
                    preflight,
                    market,
                    quantity,
                    entry,
                    close_orders,
                )
            remaining = _long_position_size(
                self.gateway.fetch_positions(symbol=_SYMBOL)
            )
            if remaining == 0:
                return self._complete(preflight, market, quantity, entry, close_orders)
            if close.state is PaperOrderState.FILLED:
                return self._result(
                    DemoBtcRoundTripPhase.CLOSE_UNRESOLVED,
                    preflight,
                    market,
                    quantity,
                    entry,
                    close_orders,
                )

        exchange_size = _long_position_size(self.gateway.fetch_positions(symbol=_SYMBOL))
        if exchange_size != 0:
            raise PaperReconciliationError(
                "Bybit Demo BTC position remains after maximum reduce-only close attempts"
            )
        return self._complete(preflight, market, quantity, entry, close_orders)

    def _close_during_entry_execution_lag(
        self,
        *,
        request: DemoBtcRoundTripRequest,
        preflight: DemoPreflightReport,
        market: PublicLinearInstrumentSnapshot,
        entry: PaperOrderRecord,
        now_utc: datetime,
    ) -> DemoBtcRoundTripResult:
        """Flatten authoritative exchange exposure while entry fills lag.

        The PAPER ledger remains unresolved until Bybit's executions endpoint
        catches up, but the leveraged Demo position is not left open merely
        because order history and execution history are temporarily skewed.
        """
        close_orders: list[PaperOrderRecord] = []
        for attempt in range(1, _MAX_CLOSE_ATTEMPTS + 1):
            exchange_size = _long_position_size(
                self.gateway.fetch_positions(symbol=_SYMBOL)
            )
            existing_close = self._existing_close(request, attempt=attempt)
            if exchange_size == 0 and existing_close is None:
                phase = (
                    DemoBtcRoundTripPhase.CLOSE_UNRESOLVED
                    if close_orders
                    else DemoBtcRoundTripPhase.ENTRY_UNRESOLVED
                )
                return self._result(
                    phase,
                    preflight,
                    market,
                    Decimal(str(entry.quantity)),
                    entry,
                    close_orders,
                )
            if exchange_size > Decimal(str(entry.quantity)) + Decimal("0.000000001"):
                raise PaperReconciliationError(
                    "Bybit Demo BTC position exceeds the durable entry quantity"
                )
            close = self._close_attempt(
                request,
                attempt=attempt,
                quantity=exchange_size,
                reference_price=market.last_price,
                now_utc=now_utc,
            )
            try:
                close, _, _ = self.reconciler.reconcile(close.client_order_id)
            except DemoExecutionLagError:
                close = self._durable_order(close.client_order_id)
            close_orders.append(close)
            if _long_position_size(self.gateway.fetch_positions(symbol=_SYMBOL)) == 0:
                return self._result(
                    DemoBtcRoundTripPhase.CLOSE_UNRESOLVED,
                    preflight,
                    market,
                    Decimal(str(entry.quantity)),
                    entry,
                    close_orders,
                )
            if close.state not in {PaperOrderState.CANCELED, PaperOrderState.REJECTED}:
                return self._result(
                    DemoBtcRoundTripPhase.CLOSE_UNRESOLVED,
                    preflight,
                    market,
                    Decimal(str(entry.quantity)),
                    entry,
                    close_orders,
                )
        raise PaperReconciliationError(
            "Bybit Demo BTC position remains after maximum reduce-only close attempts"
        )

    def _entry(
        self,
        request: DemoBtcRoundTripRequest,
        *,
        market: PublicLinearInstrumentSnapshot,
        quantity: Decimal,
        now_utc: datetime,
    ) -> PaperOrderRecord:
        key = f"operator-demo-btc-round-trip:{request.request_id}:entry-v1"
        existing = self.store.get_by_idempotency_key(key)
        if existing is None:
            if self.gateway.open_order_count(symbol=_SYMBOL) != 0:
                raise PaperReconciliationError("Bybit Demo BTC has pre-existing open orders")
            if _long_position_size(self.gateway.fetch_positions(symbol=_SYMBOL)) != 0:
                raise PaperReconciliationError("Bybit Demo BTC position is not flat before entry")
            self.gateway.set_leverage(symbol=_SYMBOL, leverage=_LEVERAGE)
            existing = self.store.begin_order(
                idempotency_key=key,
                symbol=_SYMBOL,
                side=IntentSide.BUY,
                quantity=float(quantity),
                reference_price=float(market.last_price),
                leg_group_id=f"operator-demo-btc-round-trip:{request.request_id}",
                now_utc=now_utc,
            )
        if existing.state is PaperOrderState.PENDING_SUBMIT:
            existing = self.store.mark_submitted(existing.client_order_id, now_utc=now_utc)
            acknowledgement = self.gateway.place_market(
                order_link_id=demo_order_link_id_for(existing.client_order_id),
                symbol=_SYMBOL,
                side=IntentSide.BUY,
                quantity=Decimal(str(existing.quantity)),
                reduce_only=False,
            )
            if acknowledgement.order_link_id != demo_order_link_id_for(
                existing.client_order_id
            ):
                raise PaperReconciliationError("Bybit Demo BTC entry identity mismatch")
        return existing

    def _close_attempt(
        self,
        request: DemoBtcRoundTripRequest,
        *,
        attempt: int,
        quantity: Decimal,
        reference_price: Decimal,
        now_utc: datetime,
    ) -> PaperOrderRecord:
        key = self._close_key(request, attempt=attempt)
        close = self.store.get_by_idempotency_key(key)
        if close is None:
            close = self.store.begin_order(
                idempotency_key=key,
                symbol=_SYMBOL,
                side=IntentSide.SELL,
                quantity=float(quantity),
                reference_price=float(reference_price),
                leg_group_id=f"operator-demo-btc-round-trip:{request.request_id}",
                now_utc=now_utc,
            )
        if close.state is PaperOrderState.PENDING_SUBMIT:
            close = self.store.mark_submitted(close.client_order_id, now_utc=now_utc)
            acknowledgement = self.gateway.place_market(
                order_link_id=demo_order_link_id_for(close.client_order_id),
                symbol=_SYMBOL,
                side=IntentSide.SELL,
                quantity=Decimal(str(close.quantity)),
                reduce_only=True,
            )
            if acknowledgement.order_link_id != demo_order_link_id_for(close.client_order_id):
                raise PaperReconciliationError("Bybit Demo BTC close identity mismatch")
        return close

    def _existing_close(
        self, request: DemoBtcRoundTripRequest, *, attempt: int
    ) -> PaperOrderRecord | None:
        return self.store.get_by_idempotency_key(
            self._close_key(request, attempt=attempt)
        )

    @staticmethod
    def _close_key(request: DemoBtcRoundTripRequest, *, attempt: int) -> str:
        return f"operator-demo-btc-round-trip:{request.request_id}:close-{attempt}-v1"

    def _durable_order(self, client_order_id: str) -> PaperOrderRecord:
        record = self.store.get(client_order_id)
        if record is None:
            raise PaperReconciliationError(
                f"BTC Demo durable order disappeared: {client_order_id}"
            )
        return record

    def _complete(
        self,
        preflight: DemoPreflightReport,
        market: PublicLinearInstrumentSnapshot,
        quantity: Decimal,
        entry: PaperOrderRecord,
        closes: list[PaperOrderRecord],
    ) -> DemoBtcRoundTripResult:
        exchange_size = _long_position_size(self.gateway.fetch_positions(symbol=_SYMBOL))
        paper_position = self.store.get_position(_SYMBOL)
        if exchange_size != 0:
            raise PaperReconciliationError("Bybit Demo BTC exchange position is not flat")
        if paper_position is None or abs(paper_position.net_quantity) > 1e-9:
            raise PaperReconciliationError("durable BTC PAPER position is not flat")
        return self._result(
            DemoBtcRoundTripPhase.COMPLETE,
            preflight,
            market,
            quantity,
            entry,
            closes,
        )

    def _result(
        self,
        phase: DemoBtcRoundTripPhase,
        preflight: DemoPreflightReport,
        market: PublicLinearInstrumentSnapshot,
        quantity: Decimal,
        entry: PaperOrderRecord,
        closes: list[PaperOrderRecord] | tuple[PaperOrderRecord, ...],
    ) -> DemoBtcRoundTripResult:
        exchange_size = _long_position_size(self.gateway.fetch_positions(symbol=_SYMBOL))
        return DemoBtcRoundTripResult(
            phase=phase,
            preflight=preflight,
            market=market,
            leverage=_LEVERAGE,
            target_notional_quote=_TARGET_NOTIONAL,
            submitted_quantity=quantity,
            estimated_entry_notional_quote=quantity * market.last_price,
            entry_order=entry,
            close_orders=tuple(closes),
            exchange_position_size=exchange_size,
            paper_position=self.store.get_position(_SYMBOL),
        )


def _bounded_quantity(market: PublicLinearInstrumentSnapshot) -> Decimal:
    raw_steps = _TARGET_NOTIONAL / market.last_price / market.quantity_step
    quantity = raw_steps.to_integral_value(rounding=ROUND_HALF_UP) * market.quantity_step
    quantity = max(quantity, market.minimum_order_quantity)
    estimated_notional = quantity * market.last_price
    if not _MINIMUM_NOTIONAL <= estimated_notional <= _MAXIMUM_NOTIONAL:
        raise ValueError(
            "BTC minimum quantity cannot produce a Demo notional within 75-125 USDT"
        )
    return quantity


def _long_position_size(positions: tuple[DemoPositionSnapshot, ...]) -> Decimal:
    if any(position.position_index != 0 for position in positions):
        raise PaperReconciliationError("BTC Demo account must use one-way position mode")
    signed = Decimal("0")
    for position in positions:
        if position.side == "Buy":
            signed += position.size
        elif position.side == "Sell":
            signed -= position.size
    if signed < 0:
        raise PaperReconciliationError("BTC Demo round-trip found an unexpected short position")
    return signed
