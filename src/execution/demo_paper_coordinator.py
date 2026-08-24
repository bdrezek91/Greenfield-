"""Durable Greenfield proposal-to-Bybit-Demo PAPER coordination."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal

from src.backtesting.instruments import (
    InstrumentSpecs,
    load_instrument_specs,
    validate_order_grid,
)
from src.execution.adapter import Fill
from src.execution.bybit_demo_gateway import (
    BYBIT_DEMO_REST_URL,
    BybitDemoGateway,
    BybitDemoGatewayError,
    DemoExecution,
    DemoOrderAck,
    DemoOrderSnapshot,
    DemoOrderStatus,
)
from src.execution.intent import IntentSide, OrderIntent
from src.execution.paper_reconciliation import (
    PaperOrderRecord,
    PaperOrderState,
    PaperOrderStore,
    PaperReconciliationError,
)
from src.risk.portfolio_engine import PortfolioEntryProposal


@dataclass(frozen=True, slots=True)
class DemoPaperConfig:
    allowed_symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    maximum_demo_notional_quote: Decimal = Decimal("250")
    maximum_limit_deviation_bps: Decimal = Decimal("500")
    maximum_proposal_age_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.allowed_symbols or any(
            not symbol or symbol != symbol.upper() for symbol in self.allowed_symbols
        ):
            raise ValueError("Demo PAPER requires named uppercase symbols")
        if len(set(self.allowed_symbols)) != len(self.allowed_symbols):
            raise ValueError("Demo PAPER allowed symbols must be unique")
        if (
            not self.maximum_demo_notional_quote.is_finite()
            or self.maximum_demo_notional_quote <= 0
            or not self.maximum_limit_deviation_bps.is_finite()
            or self.maximum_limit_deviation_bps <= 0
            or not math.isfinite(self.maximum_proposal_age_seconds)
            or self.maximum_proposal_age_seconds <= 0
        ):
            raise ValueError("invalid Demo PAPER safety limits")


@dataclass(frozen=True, slots=True)
class DemoSubmissionResult:
    paper_order: PaperOrderRecord
    order_link_id: str
    acknowledgement: DemoOrderAck | None
    submitted_now: bool


@dataclass(frozen=True, slots=True)
class DemoReconciliationResult:
    paper_order: PaperOrderRecord
    exchange_order: DemoOrderSnapshot | None
    executions_seen: int


class DemoPaperCoordinator:
    """Submit one risk-approved proposal to Demo with durable write-ahead.

    This class has no configurable execution endpoint and refuses a gateway
    not pinned to ``api-demo.bybit.com``. It intentionally supports only
    limit/PostOnly entry orders. Demo sizing is an explicit bounded amount,
    never an implicit reuse of the production allocation.
    """

    def __init__(
        self,
        *,
        gateway: BybitDemoGateway,
        store: PaperOrderStore,
        instrument_specs: InstrumentSpecs | None = None,
        config: DemoPaperConfig | None = None,
    ) -> None:
        if gateway.endpoint != BYBIT_DEMO_REST_URL:
            raise ValueError("Demo PAPER gateway must be pinned to the Bybit Demo endpoint")
        self.gateway = gateway
        self.store = store
        self.instrument_specs = instrument_specs or load_instrument_specs(exchange="bybit")
        self.config = config or DemoPaperConfig()

    def submit_proposal(
        self,
        proposal: PortfolioEntryProposal,
        *,
        demo_notional_quote: Decimal,
        reference_price: Decimal,
        limit_price: Decimal,
        now_utc: datetime,
    ) -> DemoSubmissionResult:
        now = _utc(now_utc, "Demo PAPER submission timestamp")
        self._validate_proposal(
            proposal,
            demo_notional_quote=demo_notional_quote,
            reference_price=reference_price,
            limit_price=limit_price,
            now_utc=now,
        )
        symbol_spec = self.instrument_specs.symbol_specs[proposal.symbol]
        raw_quantity = demo_notional_quote / reference_price
        quantity = (
            raw_quantity / symbol_spec.size_increment
        ).to_integral_value(rounding=ROUND_DOWN) * symbol_spec.size_increment
        if quantity <= 0:
            raise ValueError(
                "Demo PAPER notional is below one configured quantity increment"
            )
        validate_order_grid(
            proposal.symbol,
            self.instrument_specs,
            price=limit_price,
            quantity=quantity,
        )
        maximum_notional = max(reference_price, limit_price) * quantity
        if maximum_notional > self.config.maximum_demo_notional_quote:
            raise ValueError("Demo PAPER quantized order exceeds the notional cap")

        side = IntentSide.BUY if proposal.signed_notional > 0 else IntentSide.SELL
        paper_order = self.store.begin_order(
            idempotency_key=f"{proposal.key}:bybit-demo-v1",
            symbol=proposal.symbol,
            side=side,
            quantity=float(quantity),
            reference_price=float(reference_price),
            leg_group_id=_leg_group_id(proposal.key),
            now_utc=now,
        )
        order_link_id = demo_order_link_id_for(paper_order.client_order_id)
        if paper_order.state is not PaperOrderState.PENDING_SUBMIT:
            return DemoSubmissionResult(
                paper_order=paper_order,
                order_link_id=order_link_id,
                acknowledgement=None,
                submitted_now=False,
            )

        # Write-ahead before the network call. If the process dies or the
        # request outcome is unknown, SUBMITTED remains ambiguous and the
        # next process must query by deterministic orderLinkId, not resend.
        paper_order = self.store.mark_submitted(
            paper_order.client_order_id,
            now_utc=now,
        )
        acknowledgement = self.gateway.place_post_only(
            order_link_id=order_link_id,
            symbol=proposal.symbol,
            side=side,
            quantity=quantity,
            price=limit_price,
        )
        if acknowledgement.order_link_id != order_link_id:
            raise BybitDemoGatewayError("Demo acknowledgement identity mismatch")
        return DemoSubmissionResult(
            paper_order=paper_order,
            order_link_id=order_link_id,
            acknowledgement=acknowledgement,
            submitted_now=True,
        )

    def reconcile(self, client_order_id: str) -> DemoReconciliationResult:
        record = self.store.get(client_order_id)
        if record is None:
            raise PaperReconciliationError(f"unknown paper order: {client_order_id}")
        order_link_id = demo_order_link_id_for(client_order_id)
        executions = self.gateway.fetch_executions(
            order_link_id=order_link_id,
            symbol=record.symbol,
        )
        for execution in sorted(
            executions,
            key=lambda item: (item.executed_at_utc, item.execution_id),
        ):
            self.store.apply_fill_result(
                client_order_id,
                _fill_from_execution(record, execution),
            )
        record = self.store.get(client_order_id)
        assert record is not None
        exchange_order = self.gateway.fetch_order(
            order_link_id=order_link_id,
            symbol=record.symbol,
        )
        if exchange_order is None:
            return DemoReconciliationResult(
                paper_order=record,
                exchange_order=None,
                executions_seen=len(executions),
            )

        _require_matching_cumulative_quantity(record, exchange_order)
        if exchange_order.status is DemoOrderStatus.FILLED:
            if record.state is not PaperOrderState.FILLED:
                raise PaperReconciliationError(
                    "Bybit Demo reports FILLED but durable executions are incomplete"
                )
        elif exchange_order.status is DemoOrderStatus.CANCELLED:
            record = self.store.mark_canceled(
                client_order_id,
                now_utc=exchange_order.updated_at_utc,
            )
        elif exchange_order.status in {
            DemoOrderStatus.REJECTED,
            DemoOrderStatus.DEACTIVATED,
        }:
            if record.filled_quantity > 0:
                record = self.store.mark_canceled(
                    client_order_id,
                    now_utc=exchange_order.updated_at_utc,
                )
            elif record.state is not PaperOrderState.REJECTED:
                record = self.store.apply_fill_result(
                    client_order_id,
                    Fill(
                        intent=_intent(record),
                        filled_price=0.0,
                        filled_quantity=0.0,
                        filled_at=exchange_order.updated_at_utc,
                        rejected=True,
                        reject_reason=exchange_order.reject_reason
                        or exchange_order.status.value,
                    ),
                )
        return DemoReconciliationResult(
            paper_order=record,
            exchange_order=exchange_order,
            executions_seen=len(executions),
        )

    def cancel_and_reconcile(self, client_order_id: str) -> DemoReconciliationResult:
        record = self.store.get(client_order_id)
        if record is None:
            raise PaperReconciliationError(f"unknown paper order: {client_order_id}")
        if record.state in {
            PaperOrderState.FILLED,
            PaperOrderState.CANCELED,
            PaperOrderState.REJECTED,
        }:
            return self.reconcile(client_order_id)
        order_link_id = demo_order_link_id_for(client_order_id)
        acknowledgement = self.gateway.cancel(
            order_link_id=order_link_id,
            symbol=record.symbol,
        )
        if acknowledgement.order_link_id != order_link_id:
            raise BybitDemoGatewayError("Demo cancellation identity mismatch")
        # Cancellation acknowledgements are asynchronous. The durable state
        # changes only after fetch_order confirms the terminal exchange state.
        return self.reconcile(client_order_id)

    def _validate_proposal(
        self,
        proposal: PortfolioEntryProposal,
        *,
        demo_notional_quote: Decimal,
        reference_price: Decimal,
        limit_price: Decimal,
        now_utc: datetime,
    ) -> None:
        if proposal.venue.casefold() != "bybit":
            raise ValueError("Demo PAPER accepts only Bybit proposals")
        if proposal.symbol not in self.config.allowed_symbols:
            raise ValueError("Demo PAPER proposal symbol is not allowed")
        if proposal.symbol not in self.instrument_specs.symbol_specs:
            raise ValueError("Demo PAPER proposal has no instrument grid")
        if (
            not demo_notional_quote.is_finite()
            or demo_notional_quote <= 0
            or demo_notional_quote > self.config.maximum_demo_notional_quote
            or demo_notional_quote > Decimal(str(abs(proposal.signed_notional)))
        ):
            raise ValueError("Demo PAPER notional exceeds its bounded allocation")
        if (
            not reference_price.is_finite()
            or reference_price <= 0
            or not limit_price.is_finite()
            or limit_price <= 0
        ):
            raise ValueError("Demo PAPER prices must be finite and positive")
        deviation_bps = abs(limit_price - reference_price) / reference_price * Decimal(10_000)
        if deviation_bps > self.config.maximum_limit_deviation_bps:
            raise ValueError("Demo PAPER limit price exceeds the deviation gate")
        if proposal.signed_notional > 0 and limit_price >= reference_price:
            raise ValueError("Demo PAPER BUY smoke limit must be below its reference price")
        if proposal.signed_notional < 0 and limit_price <= reference_price:
            raise ValueError("Demo PAPER SELL smoke limit must be above its reference price")
        proposed_at = _utc(proposal.proposed_at_utc, "Demo PAPER proposal timestamp")
        age = (now_utc - proposed_at).total_seconds()
        if age < 0:
            raise ValueError("Demo PAPER proposal cannot come from the future")
        if age > self.config.maximum_proposal_age_seconds:
            raise ValueError("Demo PAPER proposal is stale")


def demo_order_link_id_for(client_order_id: str) -> str:
    if not client_order_id.strip():
        raise ValueError("paper client order id must be non-empty")
    # 4-character prefix + 32 hexadecimal characters = Bybit's 36-char max.
    return f"gfd-{hashlib.sha256(client_order_id.encode()).hexdigest()[:32]}"


def _leg_group_id(proposal_key: str) -> str | None:
    head, separator, tail = proposal_key.rpartition(":leg-")
    return head if separator and head and tail.isdigit() else None


def _fill_from_execution(record: PaperOrderRecord, execution: DemoExecution) -> Fill:
    price = float(execution.price)
    quantity = float(execution.quantity)
    adverse_per_unit = (
        max(0.0, price - record.reference_price)
        if record.side is IntentSide.BUY
        else max(0.0, record.reference_price - price)
    )
    return Fill(
        intent=_intent(record),
        filled_price=price,
        filled_quantity=quantity,
        filled_at=execution.executed_at_utc,
        slippage_cost_quote=adverse_per_unit * quantity,
        fee_cost_quote=float(execution.fee_quote),
        fill_id=execution.execution_id,
    )


def _intent(record: PaperOrderRecord) -> OrderIntent:
    return OrderIntent(
        symbol=record.symbol,
        side=record.side,
        quantity=record.quantity,
        reference_price=record.reference_price,
        created_at=record.created_at_utc,
        reason=f"Bybit Demo durable PAPER {record.idempotency_key}",
    )


def _require_matching_cumulative_quantity(
    record: PaperOrderRecord,
    exchange_order: DemoOrderSnapshot,
) -> None:
    durable = Decimal(str(record.filled_quantity))
    if abs(durable - exchange_order.cumulative_filled_quantity) > Decimal("0.000000001"):
        raise PaperReconciliationError(
            "Bybit Demo cumulative fill quantity does not match durable executions"
        )


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
