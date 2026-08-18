"""The global, append-only trial ledger.

Every hypothesis the research worker tests - whether it passes, fails, or
errors - is recorded here permanently. This is what makes a global,
never-resetting trial count for the Deflated Sharpe Ratio possible: the
existing `src.analytics.experiment.ExperimentStore` only ever sees
*successful* backtest runs invoked by hand through a CLI, and nothing
before this module counted how many hypotheses had EVER been tried across
every past cycle (see docs/AUTONOMOUS_RESEARCH_AUDIT.md, "M-częściowe #3").

This module deliberately does not replace `ExperimentStore` - that store's
contract (git commit, dataset version, fees/slippage/funding, metrics) is
unchanged and still used exactly as before by the existing CLIs. A
`TrialRecord` here optionally links to an `experiment_id` when a full
backtest was actually run for the trial.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_LEDGER_PATH = Path("reports") / "research" / "trial_ledger.jsonl"

# Every status a trial can reach. FAILED/ERROR trials are recorded exactly
# like PASSED ones - "never resets the count" means failures count too.
TRIAL_STATUSES = frozenset(
    {"PENDING", "RUNNING", "PASSED", "FAILED_GATE", "ERROR", "REJECTED"}
)


@dataclass(frozen=True)
class TrialRecord:
    trial_id: str
    hypothesis_id: str
    parent_hypothesis_id: str | None
    family: str
    rationale: str
    symbol: str
    timeframe: str
    cost_scenario: str
    status: str
    experiment_id: str | None = None
    dataset_fingerprint: str | None = None
    holdout_used: bool = False
    holdout_id: str | None = None
    metrics_summary: dict = field(default_factory=dict)
    notes: str = ""
    git_commit: str = "unknown"
    protocol_version: int | None = None
    timestamp_semantics_version: str = "legacy-open-time-v0"
    backtest_engine_version: str = "unknown"
    execution_assumptions: dict = field(default_factory=dict)
    validity_status: str = "legacy_invalid_for_promotion"
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    def __post_init__(self) -> None:
        if self.status not in TRIAL_STATUSES:
            raise ValueError(f"unknown trial status {self.status!r}, expected {TRIAL_STATUSES}")

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def fingerprint_dataset_content(data_dir: Path, symbol: str, timeframe: str) -> str:
    """Content-based dataset fingerprint (SHA-256 of the Parquet files'
    bytes), not path/size/mtime.

    `src.analytics.experiment.fingerprint_dataset` is metadata-based and is
    left untouched (existing callers/tests rely on its exact contract) -
    this is a separate, stricter fingerprint used by the research ledger,
    per the brief's requirement that a data snapshot/fingerprint be
    "content-based, not only mtime".
    """
    partition_dir = Path(data_dir) / "klines" / symbol / timeframe
    if not partition_dir.exists():
        return "no-data"

    hasher = hashlib.sha256()
    for path in sorted(partition_dir.glob("*.parquet")):
        hasher.update(path.name.encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()[:16]


class TrialLedger:
    """Append-only JSON Lines store of every trial ever run. Never rewritten,
    never truncated, never reset between research cycles.
    """

    def __init__(self, path: Path = DEFAULT_LEDGER_PATH) -> None:
        self.path = Path(path)

    def _load_lines(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open() as f:
            return [json.loads(line) for line in f if line.strip()]

    def next_trial_id(self) -> str:
        existing = self._load_lines()
        if not existing:
            return "TRIAL-000001"
        max_n = max(int(row["trial_id"].split("-")[1]) for row in existing)
        return f"TRIAL-{max_n + 1:06d}"

    def record(self, trial: TrialRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(trial.to_json() + "\n")

    def load_all(self) -> list[TrialRecord]:
        return [TrialRecord(**row) for row in self._load_lines()]

    def global_trial_count(self, family: str | None = None) -> int:
        """The total number of trials EVER recorded (optionally filtered to
        one family) - this is what DSR's n_trials should reflect, never the
        count from a single script invocation. Includes failed/rejected
        trials: a hypothesis that was tried and failed is still a trial
        that inflates the chance some *other* hypothesis looks good by luck.
        """
        rows = self._load_lines()
        if family is not None:
            rows = [r for r in rows if r["family"] == family]
        return len(rows)

    def holdout_already_used(self, family: str, holdout_id: str) -> bool:
        """True if any past trial in `family` already consumed this
        `holdout_id` - the frozen final holdout may be evaluated at most
        once per (family, holdout_id), per configs/research_protocol.yaml.
        """
        return any(
            row["family"] == family and row.get("holdout_id") == holdout_id and row["holdout_used"]
            for row in self._load_lines()
        )
