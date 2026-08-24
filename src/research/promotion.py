"""The PAPER champion/challenger state machine.

REJECTED -> RESEARCH_CANDIDATE -> PAPER_CHALLENGER -> PAPER_CHAMPION, with
DEGRADED/RETIRED reachable from any PAPER_* state. Every transition is a
function that validates its own preconditions and raises
`InvalidTransition` rather than silently no-op'ing or forcing a state - the
worker can RECOMMEND a transition (return what it *would* do), but nothing
in this module can flip a candidate to PAPER_CHAMPION (the state that
implies "this is what paper-session should be running") without an
explicit `human_approved_by` argument. There is deliberately no function
here that can reach anything resembling LIVE - the state machine's universe
ends at PAPER_CHAMPION/DEGRADED/RETIRED.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.engines.contracts import ConfirmationFamily
from src.research.config import PaperPromotionConfig, RetirementConfig
from src.research.confirmation_independence import (
    ConfirmationIndependenceReport,
    require_independence_for_promotion,
)

DEFAULT_STATE_PATH = Path("reports") / "research" / "promotion_state.json"

STATUSES = (
    "REJECTED",
    "RESEARCH_CANDIDATE",
    "PAPER_CHALLENGER",
    "PAPER_CHAMPION",
    "DEGRADED",
    "RETIRED",
)


class InvalidTransition(RuntimeError):
    pass


@dataclass
class TransitionEvent:
    from_status: str | None
    to_status: str
    reason: str
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    human_approved_by: str | None = None


@dataclass
class CandidateState:
    candidate_id: str
    status: str
    history: list[TransitionEvent] = field(default_factory=list)
    paper_started_at: str | None = None
    consecutive_degraded_reviews: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @staticmethod
    def from_dict(d: dict) -> CandidateState:
        history = [TransitionEvent(**e) for e in d.get("history", [])]
        return CandidateState(
            candidate_id=d["candidate_id"],
            status=d["status"],
            history=history,
            paper_started_at=d.get("paper_started_at"),
            consecutive_degraded_reviews=d.get("consecutive_degraded_reviews", 0),
        )


class PromotionRegistry:
    """JSON-file-backed registry of every candidate's current promotion
    state. Not append-only like the trial ledger (a candidate's status is
    mutable), but every transition is recorded in `history` so the full
    lineage survives.
    """

    def __init__(self, path: Path = DEFAULT_STATE_PATH) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, CandidateState]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {k: CandidateState.from_dict(v) for k, v in raw.items()}

    def _save(self, states: dict[str, CandidateState]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({k: v.to_dict() for k, v in states.items()}, indent=2),
            encoding="utf-8",
        )

    def get(self, candidate_id: str) -> CandidateState | None:
        return self._load().get(candidate_id)

    def all(self) -> dict[str, CandidateState]:
        return self._load()

    def _transition(
        self,
        candidate_id: str,
        *,
        new_status: str,
        allowed_from: tuple[str, ...] | None,
        reason: str,
        human_approved_by: str | None = None,
    ) -> CandidateState:
        states = self._load()
        current = states.get(candidate_id)
        current_status = current.status if current else None
        if allowed_from is not None and current_status not in allowed_from:
            raise InvalidTransition(
                f"cannot move {candidate_id!r} to {new_status} from {current_status!r}; "
                f"allowed from {allowed_from}"
            )
        if current is None:
            current = CandidateState(candidate_id=candidate_id, status=new_status)
        else:
            current.status = new_status
        current.history.append(
            TransitionEvent(
                from_status=current_status,
                to_status=new_status,
                reason=reason,
                human_approved_by=human_approved_by,
            )
        )
        states[candidate_id] = current
        self._save(states)
        return current

    def register_research_candidate(self, candidate_id: str, reason: str) -> CandidateState:
        return self._transition(
            candidate_id, new_status="RESEARCH_CANDIDATE", allowed_from=None, reason=reason
        )

    def reject(self, candidate_id: str, reason: str) -> CandidateState:
        return self._transition(
            candidate_id, new_status="REJECTED", allowed_from=None, reason=reason
        )

    def promote_to_challenger(self, candidate_id: str, reason: str) -> CandidateState:
        state = self._transition(
            candidate_id,
            new_status="PAPER_CHALLENGER",
            allowed_from=("RESEARCH_CANDIDATE",),
            reason=reason,
        )
        state.paper_started_at = datetime.now(UTC).isoformat(timespec="seconds")
        states = self._load()
        states[candidate_id] = state
        self._save(states)
        return state

    def promote_multi_family_to_challenger(
        self,
        candidate_id: str,
        reason: str,
        *,
        independence_report: ConfirmationIndependenceReport,
        required_families: tuple[ConfirmationFamily, ...],
    ) -> CandidateState:
        """Fail-closed promotion path for candidates combining confirmation families."""
        if len(set(required_families)) < 2:
            raise InvalidTransition("multi-family promotion requires at least two families")
        require_independence_for_promotion(
            independence_report, required_families=required_families
        )
        return self.promote_to_challenger(candidate_id, reason)

    def promote_to_champion(
        self,
        candidate_id: str,
        *,
        paper_weeks_elapsed: float,
        paper_trades: int,
        risk_limit_violations: int,
        human_approved_by: str,
        config: PaperPromotionConfig,
        reason: str,
    ) -> CandidateState:
        """The one transition in this whole module that requires a human.
        `human_approved_by` must be a non-empty identifier of the person who
        signed off - there is no default that lets this pass unattended.
        """
        if not config.requires_human_approval:
            raise InvalidTransition(
                "paper_promotion.requires_human_approval is False in the protocol - "
                "this is a misconfiguration, not a valid state; refusing to promote"
            )
        if not human_approved_by or not human_approved_by.strip():
            raise InvalidTransition(
                "promote_to_champion requires a non-empty human_approved_by identifier"
            )
        if paper_weeks_elapsed < config.min_paper_weeks:
            raise InvalidTransition(
                f"only {paper_weeks_elapsed} paper weeks elapsed, "
                f"need >= {config.min_paper_weeks}"
            )
        if paper_trades < config.min_paper_trades:
            raise InvalidTransition(
                f"only {paper_trades} paper trades, need >= {config.min_paper_trades}"
            )
        if risk_limit_violations > 0 and config.no_risk_limit_violations:
            raise InvalidTransition(
                f"{risk_limit_violations} risk limit violations during paper - refusing to promote"
            )
        return self._transition(
            candidate_id,
            new_status="PAPER_CHAMPION",
            allowed_from=("PAPER_CHALLENGER",),
            reason=reason,
            human_approved_by=human_approved_by,
        )

    def mark_degraded(
        self, candidate_id: str, reason: str, config: RetirementConfig
    ) -> CandidateState:
        state = self._transition(
            candidate_id,
            new_status="DEGRADED",
            allowed_from=("PAPER_CHALLENGER", "PAPER_CHAMPION", "DEGRADED"),
            reason=reason,
        )
        state.consecutive_degraded_reviews += 1
        states = self._load()
        states[candidate_id] = state
        self._save(states)
        threshold = config.consecutive_degraded_reviews_before_retirement
        if state.consecutive_degraded_reviews >= threshold:
            return self.retire(
                candidate_id,
                f"auto-retired after {state.consecutive_degraded_reviews} consecutive "
                "degraded reviews",
            )
        return state

    def retire(self, candidate_id: str, reason: str) -> CandidateState:
        return self._transition(
            candidate_id,
            new_status="RETIRED",
            allowed_from=("PAPER_CHALLENGER", "PAPER_CHAMPION", "DEGRADED"),
            reason=reason,
        )

    def kill_paper(self, candidate_id: str, reason: str) -> CandidateState:
        """Immediate kill for a safety violation - see
        configs/research_protocol.yaml `retirement.auto_kill_on`. Allowed
        from any PAPER_* state, unlike the reviewed `mark_degraded` path.
        """
        return self._transition(
            candidate_id,
            new_status="RETIRED",
            allowed_from=("PAPER_CHALLENGER", "PAPER_CHAMPION"),
            reason=f"AUTO_KILL: {reason}",
        )
