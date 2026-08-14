"""LIVE readiness gate (Phase 15) - a SECOND safety layer, above and
independent of `src.execution.mode.resolve_trading_mode`'s
`CONFIRM_LIVE_TRADING` check.

`resolve_trading_mode` answers "did the operator explicitly ask for LIVE?".
This module answers a different question: "even if they did, is the
configuration actually safe to trade real capital with?" - because the
honest answer, as of this phase, is also "there is no code path in this
repository that can submit a live order at all": `src/execution/
paper_node.py:build_paper_trading_node` raises `ValueError` for anything
but `TradingMode.PAPER`, and no live Bybit exec-client wiring exists
anywhere in this codebase. This module is infrastructure for whenever that
live path IS built - a gate that must pass before it's allowed to run, not
a green light to build that path casually.

The concrete danger this catches: `src.strategies.base.
BenchmarkStrategyConfig`'s risk defaults (risk_per_trade=0.1,
max_daily_loss=0.5, max_drawdown=0.5, max_leverage=10.0) were deliberately
chosen in Phase 9 to reproduce old backtest behavior - reasonable for a
sandboxed backtest, reckless for real capital. `src.risk.engine.
RiskConfig`'s own defaults are already conservative (0.01/0.03/0.25/3.0) -
this module's `LiveRiskBounds` are a similar conservative ceiling, checked
against whatever risk parameters a caller intends to actually use live.

Non-code operational readiness (monitoring, alerting, incident response,
capital sign-off, kill-switch procedure) is NOT checkable here - see
docs/LIVE_READINESS_CHECKLIST.md for that half of the gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.execution.mode import LiveTradingBlockedError, TradingMode, resolve_trading_mode
from src.risk.engine import RiskConfig


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def failures(self) -> tuple[PreflightCheck, ...]:
        return tuple(c for c in self.checks if not c.passed)


@dataclass(frozen=True)
class LiveRiskBounds:
    """Conservative ceilings for real-capital risk parameters - a config
    equal to or more conservative than every field here passes; anything
    looser (e.g. backtest defaults) fails.
    """

    max_risk_per_trade: float = 0.02
    max_portfolio_risk: float = 0.10
    max_daily_loss: float = 0.05
    max_drawdown: float = 0.20
    max_leverage: float = 3.0


def check_trading_mode(env: Mapping[str, str]) -> PreflightCheck:
    raw_mode = env.get("TRADING_MODE", "")
    try:
        mode = resolve_trading_mode(raw_mode, env)
    except (ValueError, LiveTradingBlockedError) as exc:
        return PreflightCheck("trading_mode", False, str(exc))
    if mode is not TradingMode.LIVE:
        return PreflightCheck(
            "trading_mode", False, f"TRADING_MODE is {mode.value!r}, expected LIVE"
        )
    return PreflightCheck("trading_mode", True, "TRADING_MODE=LIVE and CONFIRM_LIVE_TRADING set")


def check_api_credentials(env: Mapping[str, str]) -> PreflightCheck:
    key = env.get("BYBIT_API_KEY", "").strip()
    secret = env.get("BYBIT_API_SECRET", "").strip()
    if not key or not secret:
        return PreflightCheck(
            "api_credentials", False, "BYBIT_API_KEY and/or BYBIT_API_SECRET is empty/unset"
        )
    return PreflightCheck("api_credentials", True, "BYBIT_API_KEY and BYBIT_API_SECRET are set")


def check_risk_config(config: RiskConfig, bounds: LiveRiskBounds | None = None) -> PreflightCheck:
    bounds = bounds or LiveRiskBounds()
    violations = []
    if config.risk_per_trade > bounds.max_risk_per_trade:
        violations.append(f"risk_per_trade={config.risk_per_trade} > {bounds.max_risk_per_trade}")
    if config.max_portfolio_risk > bounds.max_portfolio_risk:
        violations.append(
            f"max_portfolio_risk={config.max_portfolio_risk} > {bounds.max_portfolio_risk}"
        )
    if config.max_daily_loss > bounds.max_daily_loss:
        violations.append(f"max_daily_loss={config.max_daily_loss} > {bounds.max_daily_loss}")
    if config.max_drawdown > bounds.max_drawdown:
        violations.append(f"max_drawdown={config.max_drawdown} > {bounds.max_drawdown}")
    if config.max_leverage > bounds.max_leverage:
        violations.append(f"max_leverage={config.max_leverage} > {bounds.max_leverage}")

    if violations:
        detail = "risk parameters exceed live-safe bounds: " + "; ".join(violations)
        return PreflightCheck("risk_config", False, detail)
    return PreflightCheck("risk_config", True, "risk parameters within live-safe bounds")


def check_experiment_history(experiments_path: Path, min_experiments: int = 1) -> PreflightCheck:
    """Evidence that the strategy has actually been tested (backtest/
    walk-forward experiments recorded via src.analytics.experiment) before
    going live - not a claim that N backtests mean the strategy is GOOD,
    only that going live with literally zero recorded testing is refused.
    """
    if not experiments_path.exists():
        return PreflightCheck(
            "experiment_history", False, f"no experiment log found at {experiments_path}"
        )
    n_lines = sum(1 for line in experiments_path.read_text().splitlines() if line.strip())
    if n_lines < min_experiments:
        return PreflightCheck(
            "experiment_history",
            False,
            f"only {n_lines} recorded experiment(s), need at least {min_experiments}",
        )
    return PreflightCheck("experiment_history", True, f"{n_lines} recorded experiment(s)")


def run_preflight(
    env: Mapping[str, str],
    risk_config: RiskConfig,
    experiments_path: Path,
    *,
    bounds: LiveRiskBounds | None = None,
    min_experiments: int = 1,
) -> PreflightReport:
    return PreflightReport(
        checks=(
            check_trading_mode(env),
            check_api_credentials(env),
            check_risk_config(risk_config, bounds),
            check_experiment_history(experiments_path, min_experiments),
        )
    )
