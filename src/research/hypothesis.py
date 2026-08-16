"""A hypothesis: a documented, falsifiable claim about an edge, tested
before any backtest is run - never a bare parameter combination.

Per docs/RESEARCH_METHODOLOGY.md and the brief's "each hypothesis must have
a recorded rationale before backtest" rule: `Hypothesis.rationale` is a
required field, not optional metadata bolted on after the fact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    family: str
    """One of configs/research_protocol.yaml's hypothesis_families ids."""

    rationale: str
    """Why this is economically plausible - written BEFORE any backtest runs."""

    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    parameters: dict
    parent_hypothesis_id: str | None = None
    """Set when this hypothesis is a modification of a prior one - never
    resets the global trial count (see src/research/ledger.py)."""

    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    def __post_init__(self) -> None:
        if not self.rationale or not self.rationale.strip():
            raise ValueError(
                f"hypothesis {self.hypothesis_id!r} has no rationale - a hypothesis must be "
                "justified before it is tested, not after"
            )
        if not self.symbols:
            raise ValueError(f"hypothesis {self.hypothesis_id!r} has no symbols")
        if not self.timeframes:
            raise ValueError(f"hypothesis {self.hypothesis_id!r} has no timeframes")

    def content_fingerprint(self) -> str:
        """Deterministic hash of everything that defines this hypothesis
        (not its id/timestamp) - used to detect an accidental re-submission
        of the same idea under a new id.
        """
        payload = {
            "family": self.family,
            "symbols": list(self.symbols),
            "timeframes": list(self.timeframes),
            "parameters": self.parameters,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return digest[:16]


def make_hypothesis_id(family: str, sequence: int) -> str:
    return f"HYP-{family}-{sequence:06d}"
