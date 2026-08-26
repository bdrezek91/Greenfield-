"""Deterministic Demo-only sizing and exit guards for autonomous PAPER."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

import pandas as pd

from src.engines.contracts import SetupAction
from src.execution.bybit_demo_gateway import (
    DemoAccountBalance,
    PublicLinearInstrumentSnapshot,
)


@dataclass(frozen=True, slots=True)
class AutonomousDemoRiskConfig:
    leverage: int = 100
    margin_fraction_per_trade: Decimal = Decimal("0.01")
    maximum_open_positions: int = 1
    maximum_trades_per_utc_day: int = 6
    stop_loss_bps: Decimal = Decimal("20")
    take_profit_bps: Decimal = Decimal("30")
    maximum_holding_seconds: int = 1_800
    cooldown_seconds: int = 900
    maximum_daily_loss_fraction: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        if self.leverage != 100:
            raise ValueError("operator-selected autonomous Demo leverage must be exactly 100x")
        if self.margin_fraction_per_trade != Decimal("0.01"):
            raise ValueError("operator-selected autonomous Demo margin must be exactly 1%")
        if self.maximum_open_positions != 1:
            raise ValueError("autonomous Demo permits exactly one open position")
        positive_decimals = (
            self.stop_loss_bps,
            self.take_profit_bps,
            self.maximum_daily_loss_fraction,
        )
        if any(not value.is_finite() or value <= 0 for value in positive_decimals):
            raise ValueError("autonomous Demo risk thresholds must be positive")
        if self.stop_loss_bps >= Decimal("100"):
            raise ValueError("100x Demo stop must remain below a 1% price move")
        if (
            self.maximum_trades_per_utc_day < 1
            or self.maximum_holding_seconds < 1
            or self.cooldown_seconds < 0
        ):
            raise ValueError("invalid autonomous Demo time/trade limits")


@dataclass(frozen=True, slots=True)
class AutonomousDemoSizing:
    account_equity_usd: Decimal
    sizing_capital_usd: Decimal
    target_margin_usd: Decimal
    target_notional_usd: Decimal
    quantity: Decimal
    estimated_notional_usd: Decimal
    estimated_margin_usd: Decimal

    def __post_init__(self) -> None:
        values = (
            self.account_equity_usd,
            self.sizing_capital_usd,
            self.target_margin_usd,
            self.target_notional_usd,
            self.quantity,
            self.estimated_notional_usd,
            self.estimated_margin_usd,
        )
        if any(not value.is_finite() or value <= 0 for value in values):
            raise ValueError("autonomous Demo sizing values must be positive")
        if self.estimated_margin_usd > self.target_margin_usd:
            raise ValueError("quantized Demo order exceeds the 1% margin envelope")


class DemoExitReason(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    MAX_HOLDING_TIME = "MAX_HOLDING_TIME"


def size_autonomous_demo_trade(
    balance: DemoAccountBalance,
    market: PublicLinearInstrumentSnapshot,
    config: AutonomousDemoRiskConfig | None = None,
) -> AutonomousDemoSizing:
    """Use 1% of deployable Demo capital as margin, then apply 100x.

    Bybit's total equity may include non-deployable collateral or an
    unrealized component.  Sizing from the lower of total equity and total
    available balance prevents that component from increasing order size.
    """
    config = config or AutonomousDemoRiskConfig()
    equity = balance.total_equity_usd
    capital = min(equity, balance.total_available_balance_usd)
    if capital <= 0:
        raise ValueError("autonomous Demo deployable capital must be positive")
    margin = capital * config.margin_fraction_per_trade
    notional = margin * Decimal(config.leverage)
    raw_quantity = notional / market.last_price
    quantity = (
        raw_quantity / market.quantity_step
    ).to_integral_value(rounding=ROUND_DOWN) * market.quantity_step
    if quantity < market.minimum_order_quantity:
        raise ValueError("1% Demo margin is below the venue minimum order quantity")
    actual_notional = quantity * market.last_price
    actual_margin = actual_notional / Decimal(config.leverage)
    return AutonomousDemoSizing(
        account_equity_usd=equity,
        sizing_capital_usd=capital,
        target_margin_usd=margin,
        target_notional_usd=notional,
        quantity=quantity,
        estimated_notional_usd=actual_notional,
        estimated_margin_usd=actual_margin,
    )


def autonomous_demo_exit_reason(
    *,
    action: SetupAction,
    entry_price: Decimal,
    current_price: Decimal,
    opened_at_utc: datetime,
    now_utc: datetime,
    config: AutonomousDemoRiskConfig | None = None,
    stop_loss_bps: Decimal | None = None,
    take_profit_bps: Decimal | None = None,
) -> DemoExitReason | None:
    """Evaluate stop/target/time exit.

    `stop_loss_bps`/`take_profit_bps` may override the static `config` values
    when a future qualified adapter computes and persists volatility-scaled
    exits at entry. The execution skeleton itself selects no such model.
    """
    config = config or AutonomousDemoRiskConfig()
    effective_stop = stop_loss_bps if stop_loss_bps is not None else config.stop_loss_bps
    effective_target = take_profit_bps if take_profit_bps is not None else config.take_profit_bps
    if not effective_stop.is_finite() or effective_stop <= 0:
        raise ValueError("autonomous Demo effective stop-loss must be positive")
    if not effective_target.is_finite() or effective_target <= 0:
        raise ValueError("autonomous Demo effective take-profit must be positive")
    if action not in {SetupAction.LONG, SetupAction.SHORT}:
        raise ValueError("autonomous Demo exit requires LONG or SHORT")
    if (
        not entry_price.is_finite()
        or entry_price <= 0
        or not current_price.is_finite()
        or current_price <= 0
    ):
        raise ValueError("autonomous Demo exit prices must be positive")
    opened = _utc(opened_at_utc, "autonomous Demo opened timestamp")
    now = _utc(now_utc, "autonomous Demo exit timestamp")
    if now < opened:
        raise ValueError("autonomous Demo exit cannot precede entry")
    direction = Decimal(1) if action is SetupAction.LONG else Decimal(-1)
    return_bps = direction * (current_price / entry_price - 1) * Decimal(10_000)
    if return_bps <= -effective_stop:
        return DemoExitReason.STOP_LOSS
    if return_bps >= effective_target:
        return DemoExitReason.TAKE_PROFIT
    if now - opened >= timedelta(seconds=config.maximum_holding_seconds):
        return DemoExitReason.MAX_HOLDING_TIME
    return None


@dataclass(frozen=True, slots=True)
class AtrExitConfig:
    """Optional future adapter policy for volatility-scaled exits.

    Bounds keep the venue's 100x Demo configuration from ever combining with
    an unbounded ATR reading; the neutral skeleton does not enable it itself.
    """

    window: int = 14
    stop_multiple: Decimal = Decimal("0.5")
    target_multiple: Decimal = Decimal("1.2")
    minimum_stop_bps: Decimal = Decimal("8")
    maximum_stop_bps: Decimal = Decimal("60")

    def __post_init__(self) -> None:
        if self.window < 2:
            raise ValueError("ATR window must cover at least two candles")
        positive = (self.stop_multiple, self.target_multiple, self.minimum_stop_bps)
        if any(not value.is_finite() or value <= 0 for value in positive):
            raise ValueError("ATR exit multiples/bounds must be positive")
        if not self.maximum_stop_bps.is_finite() or self.maximum_stop_bps <= self.minimum_stop_bps:
            raise ValueError("ATR maximum stop must exceed the minimum stop")
        if self.maximum_stop_bps >= Decimal("100"):
            raise ValueError("100x Demo stop must remain below a 1% price move")


def atr_stop_take_profit_bps(
    candles: pd.DataFrame, *, config: AtrExitConfig | None = None
) -> tuple[Decimal, Decimal]:
    """Compute (stop_bps, take_profit_bps) from Wilder's ATR of `candles`.

    `candles` must carry at least `config.window + 1` rows sorted ascending
    by timestamp with `high`/`low`/`close` columns (the same 5m frame the
    opportunity feed already assembles) - fails closed on anything thinner,
    matching this codebase's existing "insufficient history" guards rather
    than silently falling back to a default stop.
    """
    config = config or AtrExitConfig()
    required = {"high", "low", "close"}
    missing = sorted(required - set(candles.columns))
    if missing:
        raise ValueError(f"ATR computation missing columns: {missing}")
    if len(candles) < config.window + 1:
        raise ValueError("insufficient candle history for ATR computation")
    frame = candles.tail(config.window + 1).reset_index(drop=True)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    close = frame["close"].astype(float)
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    true_range = true_range.iloc[1:]  # first row has no previous close
    if true_range.empty or not (true_range.to_numpy() >= 0).all():
        raise ValueError("invalid ATR true-range series")
    atr = float(true_range.mean())
    last_close = float(close.iloc[-1])
    if last_close <= 0 or not math.isfinite(atr):
        raise ValueError("invalid ATR inputs")
    atr_bps = Decimal(str(atr / last_close * 10_000))
    stop_bps = min(
        max(atr_bps * config.stop_multiple, config.minimum_stop_bps), config.maximum_stop_bps
    )
    target_bps = atr_bps * config.target_multiple
    if target_bps <= stop_bps:
        target_bps = stop_bps * (config.target_multiple / config.stop_multiple)
    return stop_bps, target_bps


def daily_loss_limit_usd(
    starting_equity_usd: Decimal,
    config: AutonomousDemoRiskConfig | None = None,
) -> Decimal:
    config = config or AutonomousDemoRiskConfig()
    if not starting_equity_usd.is_finite() or starting_equity_usd <= 0:
        raise ValueError("daily starting Demo equity must be positive")
    result = starting_equity_usd * config.maximum_daily_loss_fraction
    if not math.isfinite(float(result)):
        raise ValueError("daily Demo loss limit is not finite")
    return result


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
