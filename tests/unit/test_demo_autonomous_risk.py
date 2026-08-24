from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.engines.contracts import SetupAction
from src.execution.bybit_demo_gateway import (
    DemoAccountBalance,
    PublicLinearInstrumentSnapshot,
)
from src.execution.demo_autonomous_risk import (
    AutonomousDemoRiskConfig,
    DemoExitReason,
    autonomous_demo_exit_reason,
    daily_loss_limit_usd,
    size_autonomous_demo_trade,
)


def _balance(equity: str = "100", available: str | None = None) -> DemoAccountBalance:
    deployable = available or equity
    return DemoAccountBalance(
        total_equity_usd=Decimal(equity),
        total_wallet_balance_usd=Decimal(deployable),
        total_available_balance_usd=Decimal(deployable),
    )


def _market(price: str = "100000") -> PublicLinearInstrumentSnapshot:
    return PublicLinearInstrumentSnapshot(
        symbol="BTCUSDT",
        last_price=Decimal(price),
        quantity_step=Decimal("0.001"),
        minimum_order_quantity=Decimal("0.001"),
    )


def test_one_percent_margin_at_100x_matches_operator_example() -> None:
    sizing = size_autonomous_demo_trade(_balance(), _market())

    assert sizing.target_margin_usd == Decimal("1.00")
    assert sizing.target_notional_usd == Decimal("100.00")
    assert sizing.quantity == Decimal("0.001")
    assert sizing.estimated_notional_usd == Decimal("100.000")
    assert sizing.estimated_margin_usd == Decimal("1.000")


def test_quantity_rounds_down_and_never_exceeds_one_percent_margin() -> None:
    sizing = size_autonomous_demo_trade(
        _balance("181139.68870661", "99752.05171861"), _market("78900")
    )

    assert sizing.account_equity_usd == Decimal("181139.68870661")
    assert sizing.sizing_capital_usd == Decimal("99752.05171861")
    assert sizing.target_margin_usd == Decimal("997.5205171861")
    assert sizing.quantity == Decimal("1.264")
    assert sizing.estimated_margin_usd <= sizing.target_margin_usd


def test_operator_selected_risk_constants_cannot_be_silently_changed() -> None:
    with pytest.raises(ValueError, match="exactly 100x"):
        AutonomousDemoRiskConfig(leverage=10)
    with pytest.raises(ValueError, match="exactly 1%"):
        AutonomousDemoRiskConfig(margin_fraction_per_trade=Decimal("0.02"))
    with pytest.raises(ValueError, match="exactly one"):
        AutonomousDemoRiskConfig(maximum_open_positions=2)


@pytest.mark.parametrize(
    ("action", "current", "expected"),
    [
        (SetupAction.LONG, "99.79", DemoExitReason.STOP_LOSS),
        (SetupAction.LONG, "100.31", DemoExitReason.TAKE_PROFIT),
        (SetupAction.SHORT, "100.21", DemoExitReason.STOP_LOSS),
        (SetupAction.SHORT, "99.69", DemoExitReason.TAKE_PROFIT),
    ],
)
def test_symmetric_reduce_only_exit_thresholds(
    action: SetupAction, current: str, expected: DemoExitReason
) -> None:
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)

    reason = autonomous_demo_exit_reason(
        action=action,
        entry_price=Decimal("100"),
        current_price=Decimal(current),
        opened_at_utc=now - timedelta(minutes=1),
        now_utc=now,
    )

    assert reason is expected


def test_time_exit_and_no_exit_inside_envelope() -> None:
    now = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    common = {
        "action": SetupAction.LONG,
        "entry_price": Decimal("100"),
        "current_price": Decimal("100.1"),
        "now_utc": now,
    }

    assert (
        autonomous_demo_exit_reason(
            **common, opened_at_utc=now - timedelta(minutes=31)
        )
        is DemoExitReason.MAX_HOLDING_TIME
    )
    assert (
        autonomous_demo_exit_reason(
            **common, opened_at_utc=now - timedelta(minutes=5)
        )
        is None
    )


def test_daily_loss_guard_is_one_percent_of_starting_equity() -> None:
    assert daily_loss_limit_usd(Decimal("100")) == Decimal("1.00")
