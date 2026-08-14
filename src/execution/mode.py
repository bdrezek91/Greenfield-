"""Trading mode safety gate.

Per .env.example (Phase 1) and docs/VPS_DEPLOYMENT.md: LIVE mode must be
disabled by default and never reachable by simply setting
`TRADING_MODE=LIVE` in the environment. This module is the first place
that promise is actually *enforced* in code rather than only documented -
resolving LIVE requires a second, explicit, hard-to-set-by-accident
environment variable.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class TradingMode(StrEnum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


LIVE_CONFIRMATION_ENV_VAR = "CONFIRM_LIVE_TRADING"
LIVE_CONFIRMATION_VALUE = "I_UNDERSTAND_THE_RISK"


class LiveTradingBlockedError(RuntimeError):
    """Raised when TRADING_MODE=LIVE is requested without explicit confirmation."""


def resolve_trading_mode(raw_mode: str, env: Mapping[str, str]) -> TradingMode:
    """Parse `raw_mode` (typically `os.environ["TRADING_MODE"]`) and enforce
    the LIVE safety gate. Every caller that might start real order
    submission (scripts/paper_trade.py, a future scripts/live_trade.py)
    must route through this function rather than reading TRADING_MODE
    directly.
    """
    try:
        mode = TradingMode(raw_mode.strip().upper())
    except ValueError as exc:
        valid = [m.value for m in TradingMode]
        raise ValueError(f"unknown TRADING_MODE {raw_mode!r}, expected one of {valid}") from exc

    if mode is TradingMode.LIVE and env.get(LIVE_CONFIRMATION_ENV_VAR) != LIVE_CONFIRMATION_VALUE:
        raise LiveTradingBlockedError(
            "TRADING_MODE=LIVE requires the environment variable "
            f"{LIVE_CONFIRMATION_ENV_VAR}={LIVE_CONFIRMATION_VALUE} to be set explicitly. "
            "This is a deliberate safety gate, not a bug - see docs/VPS_DEPLOYMENT.md. "
            "PAPER mode (Kraken demo environment) requires no such confirmation."
        )
    return mode
