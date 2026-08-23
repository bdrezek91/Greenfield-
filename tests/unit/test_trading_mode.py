"""TRADING_MODE=LIVE must never be reachable without the explicit confirmation flag."""

from __future__ import annotations

import pytest

from src.execution.mode import (
    LIVE_CONFIRMATION_ENV_VAR,
    LIVE_CONFIRMATION_VALUE,
    LiveTradingBlockedError,
    TradingMode,
    resolve_trading_mode,
)


def test_research_backtest_shadow_paper_never_require_confirmation() -> None:
    for mode in ("RESEARCH", "BACKTEST", "SHADOW", "PAPER"):
        assert resolve_trading_mode(mode, env={}) == TradingMode(mode)


def test_live_without_confirmation_is_blocked() -> None:
    with pytest.raises(LiveTradingBlockedError):
        resolve_trading_mode("LIVE", env={})


def test_live_with_wrong_confirmation_value_is_still_blocked() -> None:
    with pytest.raises(LiveTradingBlockedError):
        resolve_trading_mode("LIVE", env={LIVE_CONFIRMATION_ENV_VAR: "yes please"})


def test_live_with_correct_confirmation_is_allowed() -> None:
    env = {LIVE_CONFIRMATION_ENV_VAR: LIVE_CONFIRMATION_VALUE}
    assert resolve_trading_mode("LIVE", env=env) == TradingMode.LIVE


def test_mode_parsing_is_case_insensitive_and_trims_whitespace() -> None:
    assert resolve_trading_mode("  paper \n", env={}) == TradingMode.PAPER


def test_unknown_mode_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown TRADING_MODE"):
        resolve_trading_mode("YOLO", env={})
