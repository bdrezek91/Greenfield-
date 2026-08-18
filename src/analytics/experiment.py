"""Experiment tracking: the reproducibility contract from docs/RESEARCH_METHODOLOGY.md.

Every experiment record captures experiment_id, git_commit, dataset_version,
date_range, symbols, timeframes, strategy_version, parameters, fees/slippage/
funding assumptions, metrics, and timestamp. Records are stored as JSON Lines
under reports/experiments/ - generated output, not committed to git (see
.gitignore and docs/DATA.md's storage principle applied here too).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_STORE_PATH = Path("reports") / "experiments" / "experiments.jsonl"
CURRENT_TIMESTAMP_SEMANTICS = "bar-close-v2"
VALID_FOR_CURRENT_PROTOCOL = "valid_for_current_protocol"
LEGACY_INVALID_FOR_PROMOTION = "legacy_invalid_for_promotion"


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    git_commit: str
    dataset_version: str
    date_range: tuple[str, str]
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    strategy_version: str
    parameters: dict
    fees: dict
    slippage: dict
    funding_assumptions: dict
    metrics: dict
    timestamp_semantics_version: str = "legacy-open-time-v0"
    validity_status: str = LEGACY_INVALID_FOR_PROMOTION
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def capture_git_commit(repo_dir: Path | None = None) -> str:
    """Current commit hash, or 'unknown' outside a git checkout (never raises -
    a missing commit hash must not block recording an experiment)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return "unknown"


def fingerprint_dataset(data_dir: Path, symbol: str, timeframe: str) -> str:
    """A short, deterministic fingerprint of the Parquet partitions backing a
    symbol/timeframe, so an experiment can be tied to the exact data it ran
    against. Based on (path, size, mtime) rather than file contents - cheap,
    and sufficient to detect "the dataset changed since this run", though not
    a cryptographic guarantee of content equality.
    """
    partition_dir = Path(data_dir) / "klines" / symbol / timeframe
    if not partition_dir.exists():
        return "no-data"

    parts = []
    for path in sorted(partition_dir.glob("*.parquet")):
        stat = path.stat()
        parts.append(f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}")
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return digest[:16]


class ExperimentStore:
    """Append-only JSON Lines store with sequential EXP-NNNNNN IDs."""

    def __init__(self, path: Path = DEFAULT_STORE_PATH) -> None:
        self.path = Path(path)

    def _existing_ids(self) -> list[str]:
        if not self.path.exists():
            return []
        with self.path.open() as f:
            return [json.loads(line)["experiment_id"] for line in f if line.strip()]

    def next_id(self) -> str:
        ids = self._existing_ids()
        if not ids:
            return "EXP-000001"
        max_n = max(int(i.split("-")[1]) for i in ids)
        return f"EXP-{max_n + 1:06d}"

    def save(self, record: ExperimentRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(record.to_json() + "\n")

    def load_all(self) -> list[ExperimentRecord]:
        if not self.path.exists():
            return []
        records = []
        with self.path.open() as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                data["date_range"] = tuple(data["date_range"])
                data["symbols"] = tuple(data["symbols"])
                data["timeframes"] = tuple(data["timeframes"])
                records.append(ExperimentRecord(**data))
        return records

    def get(self, experiment_id: str) -> ExperimentRecord | None:
        for record in self.load_all():
            if record.experiment_id == experiment_id:
                return record
        return None


def mark_legacy_results(
    path: Path,
    *,
    current_semantics: str = CURRENT_TIMESTAMP_SEMANTICS,
) -> int:
    """Fail-close old JSONL results without deleting experiment history."""
    path = Path(path)
    if not path.exists():
        return 0
    rows: list[dict] = []
    changed = 0
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("timestamp_semantics_version") != current_semantics:
                if row.get("validity_status") != LEGACY_INVALID_FOR_PROMOTION:
                    changed += 1
                row["validity_status"] = LEGACY_INVALID_FOR_PROMOTION
            rows.append(row)
    if changed:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as target:
            for row in rows:
                target.write(json.dumps(row, sort_keys=True) + "\n")
        temporary.replace(path)
    return changed
