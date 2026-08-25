from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.engines.contracts import NumericRange, SetupAction
from src.execution.demo_opportunity_scanner import (
    BybitOpportunitySnapshot,
    DemoOpportunityScanner,
    MomentumVeto,
    PromotedEdgeProfile,
    PublicTrade,
    _price_auction_evidence,
)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _candles(*, bearish: bool = False) -> pd.DataFrame:
    timestamps = pd.date_range(end=NOW - timedelta(seconds=1), periods=80, freq="1min")
    phase = np.linspace(0, 8 * np.pi, 80)
    trend = np.linspace(0, -4 if bearish else 4, 80)
    close = 100 + trend + 2.5 * np.sin(phase)
    if bearish:
        close[-8:] = np.linspace(close[-9] - 0.2, close[-9] - 2.0, 8)
    else:
        close[-8:] = np.linspace(close[-9] + 0.2, close[-9] + 2.0, 8)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "max_source_timestamp": timestamps,
            "open": close,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": 100 + 15 * np.cos(phase),
        }
    )


def _trades() -> tuple[PublicTrade, ...]:
    output = []
    for index in range(500):
        bucket = index // 20
        price = 99 + (index % 40) * 0.05
        side = "buy" if index % 2 == 0 else "sell"
        if bucket == 24:
            price = 105 + 0.01 * (index % 20)
            side = "buy"
        output.append(
            PublicTrade(
                trade_id=f"trade-{index}",
                timestamp_utc=NOW - timedelta(milliseconds=500 - index),
                side=side,
                price=float(price),
                size=1.0,
            )
        )
    return tuple(output)


def _derivatives() -> pd.DataFrame:
    timestamps = pd.date_range(end=NOW - timedelta(seconds=1), periods=25, freq="10s")
    rng = np.random.default_rng(12)
    mark = 100 + rng.normal(0, 0.03, 25)
    interest = 1_000 + rng.normal(0, 0.5, 25)
    mark[-1] = mark[-2] * 1.04
    interest[-1] = interest[-2] * 1.04
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "max_source_timestamp": timestamps,
            "mark_price": mark,
            "index_price": mark,
            "open_interest": interest,
            "funding_rate": 0.0001,
        }
    )


def _snapshot(*, bearish_momentum: bool = False) -> BybitOpportunitySnapshot:
    return BybitOpportunitySnapshot(
        symbol="BTCUSDT",
        observed_at_utc=NOW,
        candles=_candles(bearish=bearish_momentum),
        trades=_trades(),
        derivatives=_derivatives(),
        price_tick=0.1,
    )


def _edge(*, state: str = "PAPER_CHALLENGER") -> PromotedEdgeProfile:
    return PromotedEdgeProfile(
        candidate_id="microstructure-directional-v1",
        promotion_state=state,
        expected_gross_value_bps=NumericRange(18, 25, 35),
        expected_cost_bps=NumericRange(2, 4, 7),
        capacity_notional=1_000,
    )


def test_promoted_three_family_setup_can_reach_long() -> None:
    result = DemoOpportunityScanner().scan(_snapshot(), edge=_edge())

    assert result.momentum_veto is MomentumVeto.LONG
    assert result.decision.action is SetupAction.LONG
    assert len(result.evidence) == 3
    assert {item.family.value for item in result.evidence} == {
        "price_auction",
        "order_flow",
        "derivatives",
    }


def test_unpromoted_edge_scans_but_cannot_trade() -> None:
    result = DemoOpportunityScanner().scan(
        _snapshot(), edge=_edge(state="RESEARCH_CANDIDATE")
    )

    assert len(result.evidence) == 3
    assert result.decision.action is SetupAction.WAIT
    assert result.decision.reason_codes == ("PROMOTION_STATE_NOT_ELIGIBLE",)
    assert result.experimental_demo_action() is SetupAction.LONG


def test_market_cipher_like_filter_is_a_veto_not_a_confirmation() -> None:
    snapshot = replace(_snapshot(), candles=_candles(bearish=True))
    result = DemoOpportunityScanner().scan(snapshot, edge=_edge())

    assert result.momentum_veto is not MomentumVeto.LONG
    assert result.decision.action is SetupAction.WAIT
    assert result.decision.reason_codes[0].startswith("RISK_REJECTED:")
    assert result.experimental_demo_action() is SetupAction.WAIT


def test_kill_switch_dominates_an_actionable_scan() -> None:
    result = DemoOpportunityScanner().scan(
        _snapshot(), edge=_edge(), kill_switch_active=True
    )

    assert result.decision.action is SetupAction.WAIT
    assert result.decision.reason_codes == ("KILL_SWITCH_ACTIVE",)


def test_price_levels_use_decimal_half_up_tick_binning(monkeypatch) -> None:
    captured: list[pd.DataFrame] = []

    def fake_profile(frame: pd.DataFrame):
        captured.append(frame.copy())
        return SimpleNamespace(poc=100.1, vah=100.1, val=100.1)

    monkeypatch.setattr(
        "src.execution.demo_opportunity_scanner.volume_profile", fake_profile
    )
    trades = (
        PublicTrade("half-tick", NOW, "buy", 100.05, 1.0),
        PublicTrade("below", NOW + timedelta(milliseconds=1), "sell", 100.04, 1.0),
    )

    _price_auction_evidence(trades, price_tick=0.1, maximum_trades=10)
    assert sorted(captured[0]["price_level"].tolist()) == [100.0, 100.1]
