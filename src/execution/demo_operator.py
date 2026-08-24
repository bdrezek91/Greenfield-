"""Operator-only safety gates and workflows for Bybit Demo PAPER smoke tests."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import dotenv_values

from src.execution.bybit_demo_gateway import (
    BybitDemoGateway,
    DemoPreflightReport,
)
from src.execution.mode import TradingMode, resolve_trading_mode

if TYPE_CHECKING:
    from src.execution.demo_paper_coordinator import (
        DemoReconciliationResult,
        DemoSubmissionResult,
    )
    from src.execution.paper_reconciliation import PaperOrderStore

DEMO_ORDER_CONFIRMATION_ENV_VAR = "GREENFIELD_DEMO_ORDER_CONFIRMATION"
DEMO_ORDER_CONFIRMATION_VALUE = "BYBIT_DEMO_ONLY"
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True, slots=True)
class DemoSmokeRequest:
    request_id: str
    symbol: str
    side: str
    notional_quote: Decimal
    reference_price: Decimal
    limit_price: Decimal

    def __post_init__(self) -> None:
        if not _REQUEST_ID.fullmatch(self.request_id):
            raise ValueError("Demo smoke request_id must match [A-Za-z0-9_-]{1,64}")
        if self.symbol not in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
            raise ValueError("Demo smoke symbol must be BTCUSDT, ETHUSDT, or SOLUSDT")
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("Demo smoke side must be BUY or SELL")
        for name, value in (
            ("notional", self.notional_quote),
            ("reference price", self.reference_price),
            ("limit price", self.limit_price),
        ):
            if not value.is_finite() or value <= 0:
                raise ValueError(f"Demo smoke {name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class DemoSmokeResult:
    preflight: DemoPreflightReport
    submission: DemoSubmissionResult
    reconciliation: DemoReconciliationResult


def load_demo_environment(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"Bybit Demo environment file does not exist: {path}")
    if path.is_symlink():
        raise ValueError("Bybit Demo environment file must not be a symlink")
    if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ValueError("Bybit Demo environment file must have mode 600")
    parsed = dotenv_values(path)
    return {key: value for key, value in parsed.items() if value is not None}


def require_demo_paper_environment(
    env: Mapping[str, str], *, order_submission: bool
) -> None:
    mode = resolve_trading_mode(env.get("TRADING_MODE", ""), env=env)
    if mode is not TradingMode.PAPER:
        raise ValueError(f"Bybit Demo operator command requires TRADING_MODE=PAPER, got {mode}")
    if env.get("BYBIT_API_KEY") or env.get("BYBIT_API_SECRET"):
        raise ValueError("mainnet BYBIT_API_KEY/BYBIT_API_SECRET must not be present")
    if env.get("CONFIRM_LIVE_TRADING"):
        raise ValueError("CONFIRM_LIVE_TRADING must not be present in a Demo environment")
    if not env.get("BYBIT_DEMO_API_KEY") or not env.get("BYBIT_DEMO_API_SECRET"):
        raise ValueError("BYBIT_DEMO_API_KEY and BYBIT_DEMO_API_SECRET are required")
    if order_submission and (
        env.get(DEMO_ORDER_CONFIRMATION_ENV_VAR) != DEMO_ORDER_CONFIRMATION_VALUE
    ):
        raise ValueError(
            f"Demo order submission requires {DEMO_ORDER_CONFIRMATION_ENV_VAR}="
            f"{DEMO_ORDER_CONFIRMATION_VALUE}"
        )


def run_demo_preflight(
    gateway: BybitDemoGateway,
    *,
    env: Mapping[str, str],
) -> DemoPreflightReport:
    require_demo_paper_environment(env, order_submission=False)
    return gateway.preflight()


def run_demo_smoke(
    gateway: BybitDemoGateway,
    store: PaperOrderStore,
    request: DemoSmokeRequest,
    *,
    env: Mapping[str, str],
    now_utc: datetime | None = None,
) -> DemoSmokeResult:
    from src.execution.demo_paper_coordinator import DemoPaperCoordinator
    from src.risk.portfolio_engine import PortfolioEntryProposal

    require_demo_paper_environment(env, order_submission=True)
    preflight = gateway.preflight()
    now = (now_utc or datetime.now(UTC)).astimezone(UTC)
    direction = 1.0 if request.side == "BUY" else -1.0
    proposal = PortfolioEntryProposal(
        key=f"operator-demo-smoke-{request.request_id}:leg-0",
        symbol=request.symbol,
        venue="bybit",
        strategy="operator-demo-smoke",
        engine="paper-infrastructure",
        signed_notional=direction * float(request.notional_quote),
        committed_risk_fraction=0.0001,
        correlation_checked_symbols=(),
        correlated_symbols=(),
        proposed_at_utc=now,
    )
    coordinator = DemoPaperCoordinator(gateway=gateway, store=store)
    submission = coordinator.submit_proposal(
        proposal,
        demo_notional_quote=request.notional_quote,
        reference_price=request.reference_price,
        limit_price=request.limit_price,
        now_utc=now,
    )
    reconciliation = coordinator.cancel_and_reconcile(
        submission.paper_order.client_order_id
    )
    return DemoSmokeResult(
        preflight=preflight,
        submission=submission,
        reconciliation=reconciliation,
    )


def sanitized_preflight(report: DemoPreflightReport) -> dict[str, Any]:
    return asdict(report)


def sanitized_smoke(result: DemoSmokeResult) -> dict[str, Any]:
    order = result.reconciliation.paper_order
    exchange = result.reconciliation.exchange_order
    return {
        "endpoint": result.preflight.endpoint,
        "api_key_verified": result.preflight.api_key_verified,
        "trade_permissions_verified": result.preflight.trade_permissions_verified,
        "ip_restriction_verified": result.preflight.ip_restriction_verified,
        "client_order_id": order.client_order_id,
        "order_link_id": result.submission.order_link_id,
        "submitted_now": result.submission.submitted_now,
        "durable_state": order.state.value,
        "exchange_state": exchange.status.value if exchange is not None else None,
        "filled_quantity": order.filled_quantity,
        "executions_seen": result.reconciliation.executions_seen,
    }
