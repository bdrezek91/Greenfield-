"""Historical backtest of the "druga proba scalpingu" liquidation-fade
hypothesis against this system's own Bronze/Silver data - built specifically
so the candidate is validated on thousands of historical events before
spending any more live Demo cycles on it (see docs/CLAUDE_CODE_CONTINUATION.md
for why v1 was run live-only and what that cost).

Deliberately a coarse, honest first pass, not a production-grade backtest:
- Candidate signal timestamps are the 5m kline grid (the only local candle
  resolution this system stores), not the live loop's 30s poll cadence.
  A real deployment would see cascades slightly later/earlier than this
  measures.
- Entry is simulated at that candle's close, not a live orderbook fill.
- Exit is touch-based against each subsequent candle's high/low (a stop and
  target both touched within the same candle conservatively resolves to the
  stop, since intra-candle sequencing isn't in a 5m OHLC bar).
If this coarse pass shows no edge, a finer (trade-tick-level) backtest is
not worth building; if it does, that is the natural next refinement before
any live redeployment.

Every trade pays this system's own configured Bybit maker/taker fees
(configs/instruments.yaml, loaded via load_instrument_specs) once at entry
(post-only, maker rate - matches DemoScalpExecutor.use_post_only_entry) and
once at exit (reduce-only market, taker rate) - a flat round-trip bps charge
subtracted from every trade's gross price-based return. This is an
approximation (fees are computed off entry notional for both legs rather
than each leg's own execution price), close enough given entry/exit prices
never differ by more than this candidate's stop/target distance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

import pandas as pd

from src.backtesting.instruments import load_instrument_specs
from src.data.as_of_series import AsOfSeries
from src.data.raw_store import discover_manifests, read_raw_part, verify_raw_part
from src.data.storage import read_funding, read_klines
from src.engines.contracts import SetupAction
from src.execution.demo_scalp_liquidation_signal import (
    FundingRegimeConfig,
    LiquidatedSide,
    LiquidationCascadeConfig,
    LiquidationEvent,
    detect_liquidation_cascade,
    funding_regime_allows,
)


def _default_maker_fee() -> Decimal:
    return load_instrument_specs(exchange="bybit").maker_fee


def _default_taker_fee() -> Decimal:
    return load_instrument_specs(exchange="bybit").taker_fee


class LiquidationFadeExit(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    MAX_HOLDING_TIME = "MAX_HOLDING_TIME"
    NO_MORE_DATA = "NO_MORE_DATA"


@dataclass(frozen=True, slots=True)
class LiquidationFadeBacktestConfig:
    symbol: str
    start: datetime
    end: datetime
    stop_loss_bps: Decimal = Decimal("20")
    take_profit_bps: Decimal = Decimal("30")
    maximum_holding_seconds: int = 600
    cooldown_seconds: int = 300
    cascade_config: LiquidationCascadeConfig = LiquidationCascadeConfig()
    funding_config: FundingRegimeConfig = FundingRegimeConfig()
    maker_fee: Decimal = field(default_factory=_default_maker_fee)
    taker_fee: Decimal = field(default_factory=_default_taker_fee)

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.upper():
            raise ValueError("backtest symbol must be uppercase")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("backtest start/end must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("backtest start must precede end")
        if not self.stop_loss_bps.is_finite() or self.stop_loss_bps <= 0:
            raise ValueError("backtest stop-loss must be positive")
        if not self.take_profit_bps.is_finite() or self.take_profit_bps <= 0:
            raise ValueError("backtest take-profit must be positive")
        if self.maximum_holding_seconds < 1 or self.cooldown_seconds < 0:
            raise ValueError("invalid backtest holding/cooldown seconds")
        if not self.maker_fee.is_finite() or self.maker_fee < 0:
            raise ValueError("backtest maker fee must be finite and non-negative")
        if not self.taker_fee.is_finite() or self.taker_fee < 0:
            raise ValueError("backtest taker fee must be finite and non-negative")

    @property
    def round_trip_fee_bps(self) -> Decimal:
        """Entry (post-only, maker) + exit (reduce-only market, taker)."""
        return (self.maker_fee + self.taker_fee) * Decimal(10_000)


@dataclass(frozen=True, slots=True)
class LiquidationFadeTradeOutcome:
    entry_at_utc: datetime
    direction: SetupAction
    liquidated_side: LiquidatedSide | None
    entry_price: float
    exit_at_utc: datetime
    exit_price: float
    exit_reason: LiquidationFadeExit
    return_bps: float
    """Gross, price-move-only return - before fees."""
    fee_bps: float
    """Round-trip maker (entry) + taker (exit) fee, always positive."""
    net_return_bps: float
    """return_bps - fee_bps - what actually lands in the account."""


@dataclass(frozen=True, slots=True)
class LiquidationFadeBacktestReport:
    symbol: str
    start: datetime
    end: datetime
    cascades_detected: int
    trades_taken: int
    trades_vetoed_by_funding: int
    trades: tuple[LiquidationFadeTradeOutcome, ...]

    @property
    def win_rate(self) -> float | None:
        """Net of fees - a trade that's gross-positive but fee-negative is a loss."""
        if not self.trades:
            return None
        wins = sum(1 for t in self.trades if t.net_return_bps > 0)
        return wins / len(self.trades)

    @property
    def average_return_bps(self) -> float | None:
        """Net of fees."""
        if not self.trades:
            return None
        return sum(t.net_return_bps for t in self.trades) / len(self.trades)

    @property
    def average_gross_return_bps(self) -> float | None:
        if not self.trades:
            return None
        return sum(t.return_bps for t in self.trades) / len(self.trades)

    def breakeven_win_rate(
        self,
        *,
        stop_loss_bps: Decimal,
        take_profit_bps: Decimal,
        fee_bps: Decimal = Decimal(0),
    ) -> float:
        """Win rate needed for E[net PnL] = 0: p*(target-fee) = (1-p)*(stop+fee)."""
        stop = float(stop_loss_bps)
        target = float(take_profit_bps)
        fee = float(fee_bps)
        return (stop + fee) / (stop + target)

    def summary(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "cascades_detected": self.cascades_detected,
            "trades_taken": self.trades_taken,
            "trades_vetoed_by_funding": self.trades_vetoed_by_funding,
            "win_rate": self.win_rate,
            "average_return_bps": self.average_return_bps,
            "average_gross_return_bps": self.average_gross_return_bps,
        }


def _read_historical_liquidations(
    data_dir: Path, *, symbol: str, start: datetime, end: datetime
) -> tuple[LiquidationEvent, ...]:
    manifests = discover_manifests(
        data_dir, exchange="bybit", market_type="linear", channel="liquidations", symbol=symbol
    )
    events: dict[tuple[float, str, float, float], LiquidationEvent] = {}
    for manifest in manifests:
        verify_raw_part(data_dir, manifest)
        for raw_event in read_raw_part(data_dir, manifest):
            data = raw_event.payload().get("data")
            if not isinstance(data, list):
                continue
            for row in data:
                if not isinstance(row, dict) or str(row.get("s", "")) != symbol:
                    continue
                timestamp_ms = int(row["T"])
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
                if timestamp < start or timestamp > end:
                    continue
                forced_side = str(row["S"])
                side = LiquidatedSide.LONGS if forced_side == "Sell" else LiquidatedSide.SHORTS
                price = float(row["p"])
                size = float(row["v"])
                key = (timestamp_ms / 1000, forced_side, price, size)
                events[key] = LiquidationEvent(
                    timestamp_utc=timestamp, side=side, price=price, size=size
                )
    return tuple(sorted(events.values(), key=lambda item: item.timestamp_utc))


def run_liquidation_fade_backtest(
    data_dir: Path, config: LiquidationFadeBacktestConfig
) -> LiquidationFadeBacktestReport:
    liquidation_buffer = timedelta(seconds=config.cascade_config.reference_window_seconds)
    liquidations = _read_historical_liquidations(
        data_dir,
        symbol=config.symbol,
        start=config.start - liquidation_buffer,
        end=config.end,
    )
    holding_buffer = timedelta(seconds=config.maximum_holding_seconds)
    candles = read_klines(
        data_dir,
        config.symbol,
        "5m",
        start=pd.Timestamp(config.start),
        end=pd.Timestamp(config.end + holding_buffer),
    )
    if candles.empty:
        raise ValueError("backtest requires local 5m kline history for the requested window")
    candles = candles.sort_values("timestamp").reset_index(drop=True)
    # No `start=` bound: an as-of lookup at the window's first evaluation
    # point needs whatever funding history precedes `config.start`, however
    # far back - bounding it there would silently starve the lookup.
    funding = read_funding(data_dir, config.symbol, end=pd.Timestamp(config.end))
    funding_series = AsOfSeries(funding, "funding_rate") if not funding.empty else None

    evaluation_index = candles[candles["timestamp"] >= pd.Timestamp(config.start)].index
    trades: list[LiquidationFadeTradeOutcome] = []
    cascades_detected = 0
    vetoed_by_funding = 0
    cooldown_until: datetime | None = None
    skip_before_index = -1

    for index in evaluation_index:
        if index <= skip_before_index:
            continue
        row = candles.loc[index]
        now = row["timestamp"].to_pydatetime()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        if now > config.end:
            break
        if cooldown_until is not None and now < cooldown_until:
            continue
        window = tuple(e for e in liquidations if e.timestamp_utc <= now)
        cascade = detect_liquidation_cascade(
            window, observed_at_utc=now, config=config.cascade_config
        )
        if not cascade.detected:
            continue
        cascades_detected += 1
        funding_rate = (
            Decimal(str(float(funding_series.window_ending_at(
                int(now.timestamp() * 1_000_000_000), 1
            )[-1])))
            if funding_series is not None and len(funding_series) > 0
            else Decimal("0")
        )
        if not funding_regime_allows(cascade.direction, funding_rate, config=config.funding_config):
            vetoed_by_funding += 1
            continue

        entry_price = float(row["close"])
        exit_at_utc, exit_price, exit_reason, return_bps, exit_index = _simulate_exit(
            candles, index, cascade.direction, entry_price, now, config
        )
        fee_bps = float(config.round_trip_fee_bps)
        trades.append(
            LiquidationFadeTradeOutcome(
                entry_at_utc=now,
                direction=cascade.direction,
                liquidated_side=cascade.liquidated_side,
                entry_price=entry_price,
                exit_at_utc=exit_at_utc,
                exit_price=exit_price,
                exit_reason=exit_reason,
                return_bps=return_bps,
                fee_bps=fee_bps,
                net_return_bps=return_bps - fee_bps,
            )
        )
        skip_before_index = exit_index
        cooldown_until = exit_at_utc + timedelta(seconds=config.cooldown_seconds)

    return LiquidationFadeBacktestReport(
        symbol=config.symbol,
        start=config.start,
        end=config.end,
        cascades_detected=cascades_detected,
        trades_taken=len(trades),
        trades_vetoed_by_funding=vetoed_by_funding,
        trades=tuple(trades),
    )


def _simulate_exit(
    candles: pd.DataFrame,
    entry_index: int,
    direction: SetupAction,
    entry_price: float,
    entry_time: datetime,
    config: LiquidationFadeBacktestConfig,
) -> tuple[datetime, float, LiquidationFadeExit, float, int]:
    """Return (exit_at_utc, exit_price, exit_reason, return_bps, exit_index)."""
    sign = 1.0 if direction is SetupAction.LONG else -1.0
    stop_bps = float(config.stop_loss_bps)
    target_bps = float(config.take_profit_bps)
    deadline = entry_time + timedelta(seconds=config.maximum_holding_seconds)
    last_index = entry_index
    last_close = entry_price
    last_time = entry_time
    for index in range(entry_index + 1, len(candles)):
        row = candles.loc[index]
        timestamp = row["timestamp"].to_pydatetime()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        if timestamp > deadline:
            break
        high_bps = sign * (float(row["high"]) / entry_price - 1) * 10_000
        low_bps = sign * (float(row["low"]) / entry_price - 1) * 10_000
        stop_touched = min(high_bps, low_bps) <= -stop_bps
        target_touched = max(high_bps, low_bps) >= target_bps
        last_index, last_close, last_time = index, float(row["close"]), timestamp
        if stop_touched:
            # Conservative: a candle touching both stop and target resolves
            # to the stop (worst case for the trade), matching standard
            # OHLC-bar backtest convention absent intra-bar sequencing.
            exit_price = entry_price * (1 - sign * stop_bps / 10_000)
            return timestamp, exit_price, LiquidationFadeExit.STOP_LOSS, -stop_bps, index
        if target_touched:
            exit_price = entry_price * (1 + sign * target_bps / 10_000)
            return timestamp, exit_price, LiquidationFadeExit.TAKE_PROFIT, target_bps, index
    if last_index == entry_index:
        return entry_time, entry_price, LiquidationFadeExit.NO_MORE_DATA, 0.0, entry_index
    return_bps = sign * (last_close / entry_price - 1) * 10_000
    reason = (
        LiquidationFadeExit.MAX_HOLDING_TIME
        if last_time <= deadline
        else LiquidationFadeExit.NO_MORE_DATA
    )
    return last_time, last_close, reason, return_bps, last_index
