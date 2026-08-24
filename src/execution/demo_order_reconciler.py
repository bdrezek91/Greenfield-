"""Exchange-authoritative Bybit Demo execution reconciliation."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from src.execution.adapter import Fill
from src.execution.bybit_demo_gateway import (
    BybitDemoGateway,
    DemoExecution,
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


class DemoExecutionLagError(PaperReconciliationError):
    """Order history is ahead of the execution feed; retry reconciliation later."""


class DemoOrderReconciler:
    def __init__(self, *, gateway: BybitDemoGateway, store: PaperOrderStore) -> None:
        self.gateway = gateway
        self.store = store

    def reconcile(
        self, client_order_id: str
    ) -> tuple[PaperOrderRecord, DemoOrderSnapshot | None, int]:
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
            return record, None, len(executions)

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
        return record, exchange_order, len(executions)


def demo_order_link_id_for(client_order_id: str) -> str:
    if not client_order_id.strip():
        raise ValueError("paper client order id must be non-empty")
    return f"gfd-{hashlib.sha256(client_order_id.encode()).hexdigest()[:32]}"


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
        raise DemoExecutionLagError(
            "Bybit Demo cumulative fill quantity does not match durable executions"
        )
