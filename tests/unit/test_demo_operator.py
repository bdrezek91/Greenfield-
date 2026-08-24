from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.execution.bybit_demo_gateway import (
    BYBIT_DEMO_REST_URL,
    DemoExecution,
    DemoOrderAck,
    DemoOrderSnapshot,
    DemoOrderStatus,
    DemoPreflightReport,
)
from src.execution.demo_operator import (
    DEMO_ORDER_CONFIRMATION_ENV_VAR,
    DEMO_ORDER_CONFIRMATION_VALUE,
    DemoSmokeRequest,
    require_demo_paper_environment,
    run_demo_smoke,
    sanitized_smoke,
)
from src.execution.intent import IntentSide
from src.execution.paper_reconciliation import PaperOrderState, PaperOrderStore

NOW = datetime(2026, 8, 24, 21, tzinfo=UTC)


def _env(*, armed: bool = False) -> dict[str, str]:
    values = {
        "TRADING_MODE": "PAPER",
        "BYBIT_DEMO_API_KEY": "demo-key",  # pragma: allowlist secret
        "BYBIT_DEMO_API_SECRET": "demo-secret",  # pragma: allowlist secret
    }
    if armed:
        values[DEMO_ORDER_CONFIRMATION_ENV_VAR] = DEMO_ORDER_CONFIRMATION_VALUE
    return values


class FakeGateway:
    endpoint = BYBIT_DEMO_REST_URL

    def __init__(self) -> None:
        self.place_calls = 0
        self.cancel_calls = 0
        self.order_link_id = ""

    def preflight(self) -> DemoPreflightReport:
        return DemoPreflightReport(
            endpoint=self.endpoint,
            api_key_verified=True,
            trade_permissions_verified=True,
            ip_restriction_verified=True,
            restricted_ips=("57.128.220.89",),
            wallet_rows=1,
            position_rows=0,
            open_order_rows=0,
        )

    def place_post_only(
        self,
        *,
        order_link_id: str,
        symbol: str,
        side: IntentSide,
        quantity: Decimal,
        price: Decimal,
    ) -> DemoOrderAck:
        del symbol, side, quantity, price
        self.place_calls += 1
        self.order_link_id = order_link_id
        return DemoOrderAck("exchange-1", order_link_id)

    def cancel(self, *, order_link_id: str, symbol: str) -> DemoOrderAck:
        del symbol
        self.cancel_calls += 1
        return DemoOrderAck("exchange-1", order_link_id)

    def fetch_order(
        self, *, order_link_id: str, symbol: str
    ) -> DemoOrderSnapshot | None:
        return DemoOrderSnapshot(
            order_id="exchange-1",
            order_link_id=order_link_id,
            symbol=symbol,
            status=DemoOrderStatus.CANCELLED,
            cumulative_filled_quantity=Decimal("0"),
            updated_at_utc=NOW + timedelta(seconds=1),
            reject_reason=None,
        )

    def fetch_executions(
        self, *, order_link_id: str, symbol: str
    ) -> tuple[DemoExecution, ...]:
        del order_link_id, symbol
        return ()


@pytest.mark.parametrize(
    "env",
    [
        {"TRADING_MODE": "LIVE"},
        {"TRADING_MODE": "PAPER"},
        {
            "TRADING_MODE": "PAPER",
            "BYBIT_DEMO_API_KEY": "demo",  # pragma: allowlist secret
            "BYBIT_DEMO_API_SECRET": "demo-secret",  # pragma: allowlist secret
            "BYBIT_API_KEY": "mainnet-must-not-be-here",  # pragma: allowlist secret
        },
    ],
)
def test_demo_environment_is_fail_closed(env: dict[str, str]) -> None:
    with pytest.raises((RuntimeError, ValueError)):
        require_demo_paper_environment(env, order_submission=False)


def test_order_submission_requires_separate_demo_confirmation() -> None:
    with pytest.raises(ValueError, match=DEMO_ORDER_CONFIRMATION_ENV_VAR):
        require_demo_paper_environment(_env(), order_submission=True)
    require_demo_paper_environment(_env(armed=True), order_submission=True)


def test_smoke_places_once_then_cancels_and_reconciles(tmp_path: Path) -> None:
    gateway = FakeGateway()
    store = PaperOrderStore(tmp_path / "demo.sqlite3")
    request = DemoSmokeRequest(
        request_id="operator-001",
        symbol="ETHUSDT",
        side="BUY",
        notional_quote=Decimal("30"),
        reference_price=Decimal("3000"),
        limit_price=Decimal("2990"),
    )

    first = run_demo_smoke(
        gateway,
        store,
        request,
        env=_env(armed=True),
        now_utc=NOW,
    )
    replay = run_demo_smoke(
        gateway,
        store,
        request,
        env=_env(armed=True),
        now_utc=NOW,
    )

    assert first.reconciliation.paper_order.state is PaperOrderState.CANCELED
    assert not replay.submission.submitted_now
    assert gateway.place_calls == 1
    assert gateway.cancel_calls == 1
    assert sanitized_smoke(first)["endpoint"] == BYBIT_DEMO_REST_URL
