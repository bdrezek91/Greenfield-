from __future__ import annotations

from pathlib import Path

import pytest

from src.research.config import load_research_protocol
from src.research.promotion import InvalidTransition, PromotionRegistry

_PAPER_CFG = load_research_protocol().paper_promotion
_RETIREMENT_CFG = load_research_protocol().retirement


def _registry(tmp_path: Path) -> PromotionRegistry:
    return PromotionRegistry(tmp_path / "state.json")


def test_register_research_candidate(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    state = reg.register_research_candidate("CAND-1", reason="cleared promotion gate")
    assert state.status == "RESEARCH_CANDIDATE"
    assert len(state.history) == 1


def test_promote_to_challenger_requires_research_candidate_first(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    with pytest.raises(InvalidTransition):
        reg.promote_to_challenger("CAND-1", reason="skip ahead")


def test_promote_to_challenger_happy_path(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.register_research_candidate("CAND-1", reason="cleared gate")
    state = reg.promote_to_challenger("CAND-1", reason="promoted")
    assert state.status == "PAPER_CHALLENGER"
    assert state.paper_started_at is not None


def test_promote_to_champion_requires_human_approval(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.register_research_candidate("CAND-1", reason="x")
    reg.promote_to_challenger("CAND-1", reason="x")
    with pytest.raises(InvalidTransition, match="human_approved_by"):
        reg.promote_to_champion(
            "CAND-1",
            paper_weeks_elapsed=10,
            paper_trades=50,
            risk_limit_violations=0,
            human_approved_by="",
            config=_PAPER_CFG,
            reason="x",
        )


def test_promote_to_champion_requires_min_paper_weeks(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.register_research_candidate("CAND-1", reason="x")
    reg.promote_to_challenger("CAND-1", reason="x")
    with pytest.raises(InvalidTransition, match="paper weeks"):
        reg.promote_to_champion(
            "CAND-1",
            paper_weeks_elapsed=1,
            paper_trades=50,
            risk_limit_violations=0,
            human_approved_by="operator@example.com",
            config=_PAPER_CFG,
            reason="x",
        )


def test_promote_to_champion_blocked_by_risk_violation(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.register_research_candidate("CAND-1", reason="x")
    reg.promote_to_challenger("CAND-1", reason="x")
    with pytest.raises(InvalidTransition, match="risk limit violations"):
        reg.promote_to_champion(
            "CAND-1",
            paper_weeks_elapsed=10,
            paper_trades=50,
            risk_limit_violations=2,
            human_approved_by="operator@example.com",
            config=_PAPER_CFG,
            reason="x",
        )


def test_promote_to_champion_happy_path(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.register_research_candidate("CAND-1", reason="x")
    reg.promote_to_challenger("CAND-1", reason="x")
    state = reg.promote_to_champion(
        "CAND-1",
        paper_weeks_elapsed=10,
        paper_trades=50,
        risk_limit_violations=0,
        human_approved_by="operator@example.com",
        config=_PAPER_CFG,
        reason="human-reviewed",
    )
    assert state.status == "PAPER_CHAMPION"
    assert state.history[-1].human_approved_by == "operator@example.com"


def test_mark_degraded_auto_retires_after_threshold(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.register_research_candidate("CAND-1", reason="x")
    reg.promote_to_challenger("CAND-1", reason="x")
    reg.mark_degraded("CAND-1", "rolling sharpe below expected band", _RETIREMENT_CFG)
    reg.mark_degraded("CAND-1", "still degraded", _RETIREMENT_CFG)
    state = reg.mark_degraded("CAND-1", "still degraded", _RETIREMENT_CFG)
    assert state.status == "RETIRED"


def test_mark_degraded_does_not_retire_before_threshold(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.register_research_candidate("CAND-1", reason="x")
    reg.promote_to_challenger("CAND-1", reason="x")
    state = reg.mark_degraded("CAND-1", "one bad review", _RETIREMENT_CFG)
    assert state.status == "DEGRADED"


def test_kill_paper_is_immediate_from_challenger(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.register_research_candidate("CAND-1", reason="x")
    reg.promote_to_challenger("CAND-1", reason="x")
    state = reg.kill_paper("CAND-1", "risk_limit_breach")
    assert state.status == "RETIRED"
    assert "AUTO_KILL" in state.history[-1].reason


def test_kill_paper_not_allowed_from_research_candidate(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.register_research_candidate("CAND-1", reason="x")
    with pytest.raises(InvalidTransition):
        reg.kill_paper("CAND-1", "risk_limit_breach")


def test_state_persists_across_registry_instances(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    PromotionRegistry(path).register_research_candidate("CAND-1", reason="x")
    fresh = PromotionRegistry(path)
    assert fresh.get("CAND-1").status == "RESEARCH_CANDIDATE"


def test_reject_from_scratch(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    state = reg.reject("CAND-2", reason="failed promotion gate")
    assert state.status == "REJECTED"
