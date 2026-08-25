"""Shared portfolio risk budget and non-overridable exposure guards."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime


@dataclass(frozen=True, slots=True)
class PortfolioRiskConfig:
    maximum_gross_exposure_multiple: float = 2.0
    maximum_net_exposure_multiple: float = 1.0
    maximum_symbol_exposure_multiple: float = 0.5
    maximum_venue_exposure_multiple: float = 1.0
    maximum_strategy_exposure_multiple: float = 0.75
    maximum_engine_exposure_multiple: float = 1.0
    maximum_correlated_exposure_multiple: float = 0.75
    maximum_committed_risk_fraction: float = 0.05
    maximum_daily_loss_fraction: float = 0.03
    maximum_drawdown_fraction: float = 0.15
    maximum_open_positions: int = 10
    minimum_order_notional: float = 10.0

    def __post_init__(self) -> None:
        positive = (
            self.maximum_gross_exposure_multiple,
            self.maximum_net_exposure_multiple,
            self.maximum_symbol_exposure_multiple,
            self.maximum_venue_exposure_multiple,
            self.maximum_strategy_exposure_multiple,
            self.maximum_engine_exposure_multiple,
            self.maximum_correlated_exposure_multiple,
            self.maximum_committed_risk_fraction,
            self.maximum_daily_loss_fraction,
            self.maximum_drawdown_fraction,
            self.minimum_order_notional,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive):
            raise ValueError("portfolio risk limits must be finite and positive")
        if self.maximum_open_positions < 1:
            raise ValueError("portfolio risk requires at least one position slot")
        fractions = (
            self.maximum_committed_risk_fraction,
            self.maximum_daily_loss_fraction,
            self.maximum_drawdown_fraction,
        )
        if any(value > 1 for value in fractions):
            raise ValueError("portfolio risk fractions cannot exceed one")


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    key: str
    symbol: str
    venue: str
    strategy: str
    engine: str
    signed_notional: float
    committed_risk_fraction: float
    opened_at_utc: datetime

    def __post_init__(self) -> None:
        identifiers = (self.key, self.symbol, self.venue, self.strategy, self.engine)
        if any(not value.strip() for value in identifiers):
            raise ValueError("portfolio position identifiers must be non-empty")
        if not math.isfinite(self.signed_notional) or self.signed_notional == 0:
            raise ValueError("portfolio position notional must be finite and non-zero")
        if (
            not math.isfinite(self.committed_risk_fraction)
            or not 0 < self.committed_risk_fraction <= 1
        ):
            raise ValueError("portfolio position committed risk must be positive")
        _utc(self.opened_at_utc, "position opened timestamp")


@dataclass(frozen=True, slots=True)
class PortfolioEntryProposal:
    key: str
    symbol: str
    venue: str
    strategy: str
    engine: str
    signed_notional: float
    committed_risk_fraction: float
    correlation_checked_symbols: tuple[str, ...]
    correlated_symbols: tuple[str, ...]
    proposed_at_utc: datetime

    def __post_init__(self) -> None:
        identifiers = (self.key, self.symbol, self.venue, self.strategy, self.engine)
        if any(not value.strip() for value in identifiers):
            raise ValueError("portfolio proposal identifiers must be non-empty")
        if not math.isfinite(self.signed_notional) or self.signed_notional == 0:
            raise ValueError("portfolio proposal notional must be finite and non-zero")
        if (
            not math.isfinite(self.committed_risk_fraction)
            or not 0 < self.committed_risk_fraction <= 1
        ):
            raise ValueError("portfolio proposal committed risk must be positive")
        checked = set(self.correlation_checked_symbols)
        correlated = set(self.correlated_symbols)
        if len(checked) != len(self.correlation_checked_symbols):
            raise ValueError("correlation checked symbols must be unique")
        if len(correlated) != len(self.correlated_symbols):
            raise ValueError("portfolio proposal correlated symbols must be unique")
        if not correlated.issubset(checked):
            raise ValueError("correlated symbols must be covered by correlation evidence")
        if self.symbol in checked or self.symbol in correlated:
            raise ValueError("proposal symbol must not appear in correlation evidence")
        _utc(self.proposed_at_utc, "proposal timestamp")


@dataclass(frozen=True, slots=True)
class PortfolioRiskDecision:
    proposal_key: str
    approved: bool
    approved_signed_notional: float
    approved_risk_fraction: float
    reason: str
    projected_gross_exposure: float
    projected_net_exposure: float
    projected_committed_risk_fraction: float

    def __post_init__(self) -> None:
        if not self.proposal_key.strip() or not self.reason.strip():
            raise ValueError("risk decision identifiers must be non-empty")
        values = (
            self.approved_signed_notional,
            self.approved_risk_fraction,
            self.projected_gross_exposure,
            self.projected_net_exposure,
            self.projected_committed_risk_fraction,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("risk decision values must be finite")
        if self.approved:
            if self.approved_signed_notional == 0 or self.approved_risk_fraction <= 0:
                raise ValueError("approved risk decision must allocate notional and risk")
        elif self.approved_signed_notional != 0 or self.approved_risk_fraction != 0:
            raise ValueError("rejected risk decision cannot allocate notional or risk")


@dataclass(frozen=True, slots=True)
class PortfolioRiskSnapshot:
    positions: tuple[PortfolioPosition, ...]
    peak_equity: float
    daily_realized_pnl: float
    current_day: date | None
    kill_switch_reason: str | None

    def __post_init__(self) -> None:
        if len({position.key for position in self.positions}) != len(self.positions):
            raise ValueError("risk snapshot position keys must be unique")
        if not math.isfinite(self.peak_equity) or self.peak_equity < 0:
            raise ValueError("risk snapshot peak equity must be finite and non-negative")
        if not math.isfinite(self.daily_realized_pnl):
            raise ValueError("risk snapshot daily PnL must be finite")
        if self.kill_switch_reason is not None and not self.kill_switch_reason.strip():
            raise ValueError("risk snapshot kill switch reason must be non-empty")


class PortfolioRiskEngine:
    """Stateful shared budget; it can reduce/reject but never create a signal."""

    def __init__(self, config: PortfolioRiskConfig | None = None) -> None:
        self.config = config or PortfolioRiskConfig()
        self._positions: dict[str, PortfolioPosition] = {}
        self._peak_equity = 0.0
        self._daily_realized_pnl = 0.0
        self._current_day: date | None = None
        self._kill_switch_reason: str | None = None
        self._pending_decisions: dict[str, PortfolioRiskDecision] = {}

    @classmethod
    def from_snapshot(
        cls,
        snapshot: PortfolioRiskSnapshot,
        config: PortfolioRiskConfig | None = None,
    ) -> PortfolioRiskEngine:
        engine = cls(config)
        if len(snapshot.positions) > engine.config.maximum_open_positions:
            raise ValueError("risk snapshot exceeds the configured position limit")
        engine._positions = {position.key: position for position in snapshot.positions}
        engine._peak_equity = snapshot.peak_equity
        engine._daily_realized_pnl = snapshot.daily_realized_pnl
        engine._current_day = snapshot.current_day
        engine._kill_switch_reason = snapshot.kill_switch_reason
        return engine

    def evaluate_entry(
        self, proposal: PortfolioEntryProposal, *, equity: float
    ) -> PortfolioRiskDecision:
        now = _utc(proposal.proposed_at_utc, "proposal timestamp")
        if not self._roll_day(now):
            return self._rejected("OUT_OF_ORDER_TIMESTAMP", proposal_key=proposal.key)
        _positive_equity(equity)
        self._peak_equity = max(self._peak_equity, equity)
        reason = self._blocking_reason(proposal, equity=equity)
        if reason is not None:
            return self._rejected(reason, proposal_key=proposal.key)

        requested = abs(proposal.signed_notional)
        direction = 1.0 if proposal.signed_notional > 0 else -1.0
        gross = self.gross_exposure
        net = self.net_exposure
        symbol_gross = sum(
            abs(position.signed_notional)
            for position in self._positions.values()
            if position.symbol == proposal.symbol
        )
        venue_gross = sum(
            abs(position.signed_notional)
            for position in self._positions.values()
            if position.venue == proposal.venue
        )
        strategy_gross = sum(
            abs(position.signed_notional)
            for position in self._positions.values()
            if position.strategy == proposal.strategy
        )
        engine_gross = sum(
            abs(position.signed_notional)
            for position in self._positions.values()
            if position.engine == proposal.engine
        )
        correlated_symbols = {proposal.symbol, *proposal.correlated_symbols}
        correlated_gross = sum(
            abs(position.signed_notional)
            for position in self._positions.values()
            if position.symbol in correlated_symbols
        )
        risk_room_fraction = max(
            0.0,
            self.config.maximum_committed_risk_fraction - self.committed_risk_fraction,
        )
        risk_scaled_notional = requested * min(
            1.0, risk_room_fraction / proposal.committed_risk_fraction
        )
        net_room = (
            self.config.maximum_net_exposure_multiple * equity - net
            if direction > 0
            else self.config.maximum_net_exposure_multiple * equity + net
        )
        approved = min(
            requested,
            max(
                0.0,
                self.config.maximum_gross_exposure_multiple * equity - gross,
            ),
            max(0.0, net_room),
            max(
                0.0,
                self.config.maximum_symbol_exposure_multiple * equity - symbol_gross,
            ),
            max(
                0.0,
                self.config.maximum_venue_exposure_multiple * equity - venue_gross,
            ),
            max(
                0.0,
                self.config.maximum_strategy_exposure_multiple * equity
                - strategy_gross,
            ),
            max(
                0.0,
                self.config.maximum_engine_exposure_multiple * equity - engine_gross,
            ),
            max(
                0.0,
                self.config.maximum_correlated_exposure_multiple * equity
                - correlated_gross,
            ),
            risk_scaled_notional,
        )
        if approved < self.config.minimum_order_notional:
            return self._rejected(
                "NO_PORTFOLIO_RISK_CAPACITY", proposal_key=proposal.key
            )
        approved_risk = proposal.committed_risk_fraction * approved / requested
        signed = direction * approved
        decision = PortfolioRiskDecision(
            proposal_key=proposal.key,
            approved=True,
            approved_signed_notional=signed,
            approved_risk_fraction=approved_risk,
            reason="APPROVED",
            projected_gross_exposure=gross + approved,
            projected_net_exposure=net + signed,
            projected_committed_risk_fraction=self.committed_risk_fraction
            + approved_risk,
        )
        self._pending_decisions[proposal.key] = decision
        return decision

    def record_open(
        self,
        proposal: PortfolioEntryProposal,
        decision: PortfolioRiskDecision,
    ) -> None:
        if not decision.approved:
            raise ValueError("cannot open a risk-rejected portfolio position")
        if decision.proposal_key != proposal.key:
            raise ValueError("risk decision does not belong to this proposal")
        if proposal.key in self._positions:
            raise ValueError("portfolio position key is already open")
        if self._pending_decisions.get(proposal.key) != decision:
            raise ValueError("risk decision was not issued by this engine")
        requested = abs(proposal.signed_notional)
        approved = abs(decision.approved_signed_notional)
        if approved > requested or approved < self.config.minimum_order_notional:
            raise ValueError("risk decision has an invalid approved notional")
        if decision.approved_signed_notional * proposal.signed_notional <= 0:
            raise ValueError("risk decision changed the proposal direction")
        maximum_risk = proposal.committed_risk_fraction * approved / requested
        if not math.isclose(
            decision.approved_risk_fraction,
            maximum_risk,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("risk decision has an invalid approved risk")
        self._positions[proposal.key] = PortfolioPosition(
            key=proposal.key,
            symbol=proposal.symbol,
            venue=proposal.venue,
            strategy=proposal.strategy,
            engine=proposal.engine,
            signed_notional=decision.approved_signed_notional,
            committed_risk_fraction=decision.approved_risk_fraction,
            opened_at_utc=proposal.proposed_at_utc,
        )
        del self._pending_decisions[proposal.key]

    def record_close(
        self, key: str, *, realized_pnl: float, closed_at_utc: datetime
    ) -> None:
        now = _utc(closed_at_utc, "position closed timestamp")
        self._roll_day(now)
        if key not in self._positions:
            raise KeyError(f"unknown portfolio position: {key}")
        if not math.isfinite(realized_pnl):
            raise ValueError("realized PnL must be finite")
        del self._positions[key]
        self._daily_realized_pnl += realized_pnl

    def activate_kill_switch(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("kill switch activation requires a reason")
        self._kill_switch_reason = reason

    def clear_kill_switch(self, *, operator_reason: str) -> None:
        if not operator_reason.strip():
            raise ValueError("kill switch reset requires an operator reason")
        self._kill_switch_reason = None

    def update_equity(self, equity: float) -> None:
        _positive_equity(equity)
        self._peak_equity = max(self._peak_equity, equity)

    def snapshot(self) -> PortfolioRiskSnapshot:
        """Return all safety state that must be durably persisted by the caller."""

        return PortfolioRiskSnapshot(
            positions=self.positions,
            peak_equity=self._peak_equity,
            daily_realized_pnl=self._daily_realized_pnl,
            current_day=self._current_day,
            kill_switch_reason=self._kill_switch_reason,
        )

    def _blocking_reason(
        self, proposal: PortfolioEntryProposal, *, equity: float
    ) -> str | None:
        if self._kill_switch_reason is not None:
            return f"KILL_SWITCH_ACTIVE:{self._kill_switch_reason}"
        if proposal.key in self._positions:
            return "POSITION_KEY_ALREADY_OPEN"
        if len(self._positions) >= self.config.maximum_open_positions:
            return "MAXIMUM_OPEN_POSITIONS"
        if self._daily_realized_pnl <= -self.config.maximum_daily_loss_fraction * equity:
            return "MAXIMUM_DAILY_LOSS"
        if self._peak_equity > 0:
            drawdown = 1.0 - equity / self._peak_equity
            if drawdown >= self.config.maximum_drawdown_fraction:
                return "MAXIMUM_DRAWDOWN"
        other_symbols = {
            position.symbol
            for position in self._positions.values()
            if position.symbol != proposal.symbol
        }
        if not other_symbols.issubset(set(proposal.correlation_checked_symbols)):
            return "MISSING_CORRELATION_EVIDENCE"
        return None

    def _rejected(
        self, reason: str, *, proposal_key: str = "REJECTED_BEFORE_PROPOSAL"
    ) -> PortfolioRiskDecision:
        return PortfolioRiskDecision(
            proposal_key=proposal_key,
            approved=False,
            approved_signed_notional=0.0,
            approved_risk_fraction=0.0,
            reason=reason,
            projected_gross_exposure=self.gross_exposure,
            projected_net_exposure=self.net_exposure,
            projected_committed_risk_fraction=self.committed_risk_fraction,
        )

    def _roll_day(self, now: datetime) -> bool:
        """Advance the UTC loss ledger monotonically; never roll it backwards."""
        event_day = now.date()
        if self._current_day is None or event_day > self._current_day:
            self._current_day = event_day
            self._daily_realized_pnl = 0.0
            return True
        return event_day == self._current_day

    @property
    def positions(self) -> tuple[PortfolioPosition, ...]:
        return tuple(sorted(self._positions.values(), key=lambda item: item.key))

    @property
    def gross_exposure(self) -> float:
        return sum(abs(position.signed_notional) for position in self._positions.values())

    @property
    def net_exposure(self) -> float:
        return sum(position.signed_notional for position in self._positions.values())

    @property
    def committed_risk_fraction(self) -> float:
        return sum(
            position.committed_risk_fraction for position in self._positions.values()
        )

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_reason is not None


def _positive_equity(equity: float) -> None:
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError("portfolio equity must be finite and positive")


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
