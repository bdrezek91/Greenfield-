"""Write one research cycle's on-disk report bundle:

reports/research_cycles/<cycle_id>/
    manifest.json
    summary.md
    candidates.csv
    rejected.csv
    robustness.json
    data_quality.json
    logs/

Per ETAP 6 of the brief, `summary.md` is written in Polish and must answer
a fixed set of questions about the cycle - see `_render_summary_md`.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_REPORTS_ROOT = Path("reports") / "research_cycles"


@dataclass(frozen=True)
class TrialReportRow:
    hypothesis_id: str
    family: str
    strategy: str
    symbol: str
    timeframe: str
    status: str
    deflated_sharpe_ratio: float | None
    probability_of_backtest_overfitting: float | None
    oos_trades: int | None
    aggregate_return_after_adverse_costs: float | None
    aggregate_return_after_severe_costs: float | None
    monte_carlo_risk_of_ruin: float | None
    monte_carlo_risk_of_ruin_upper_bound_ci95: float | None
    reason: str


@dataclass
class CycleResult:
    cycle_id: str
    protocol_version: int
    started_at: str
    finished_at: str
    status: str  # "CANDIDATE" | "NO_CANDIDATE" | "ERROR"
    data_quality: dict = field(default_factory=dict)
    skipped_families: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    passed_trials: tuple[TrialReportRow, ...] = field(default_factory=tuple)
    rejected_trials: tuple[TrialReportRow, ...] = field(default_factory=tuple)
    selected_candidate_hypothesis_id: str | None = None
    global_trial_count: int = 0
    robustness: dict = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    """Answers to the ETAP 6 questions, keyed by question - see
    `_render_summary_md`."""
    error: str | None = None


def new_cycle_id() -> str:
    return datetime.now(UTC).strftime("CYCLE-%Y%m%dT%H%M%SZ")


def _write_csv(path: Path, rows: tuple[TrialReportRow, ...]) -> None:
    fieldnames = list(TrialReportRow.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


_QUESTIONS_PL = [
    ("hipotezy", "Jakie hipotezy sprawdzono?"),
    ("dlaczego", "Dlaczego je sprawdzono?"),
    ("liczba_prob", "Ile łącznie prób uwzględnia DSR?"),
    ("wyniki_oos", "Jakie były wyniki OOS?"),
    ("koszty", "Czy funding i wszystkie koszty zastosowano?"),
    ("pbo", "Jaki jest PBO?"),
    ("stabilnosc", "Jak stabilne są parametry?"),
    ("edge_inne", "Czy edge występuje na innych instrumentach/reżimach?"),
    ("adverse_severe", "Jak wynik zmienia się w adverse/severe costs?"),
    ("bootstrap", "Jakie są wyniki block bootstrap?"),
    ("decyzja", "Dlaczego strategia została odrzucona lub promowana?"),
    ("nowy_kandydat", "Czy istnieje nowy kandydat?"),
    ("paper_status", "Czy aktywny PAPER działa poprawnie?"),
    ("wymaga_czlowieka", "Czy potrzebna jest decyzja człowieka?"),
]


def _render_summary_md(result: CycleResult) -> str:
    lines = [
        f"# Raport cyklu badawczego {result.cycle_id}",
        "",
        f"Status: **{result.status}**  ",
        f"Protokół: wersja {result.protocol_version}  ",
        f"Start: {result.started_at}  ",
        f"Koniec: {result.finished_at}  ",
        f"Globalna liczba prób (DSR): {result.global_trial_count}",
        "",
    ]
    for key, question in _QUESTIONS_PL:
        answer = result.notes.get(key, "(brak danych dla tego cyklu)")
        lines.append(f"## {question}")
        lines.append("")
        lines.append(answer)
        lines.append("")

    if result.skipped_families:
        lines.append("## Pominięte rodziny hipotez")
        lines.append("")
        for family_id, reason in result.skipped_families:
            lines.append(f"- `{family_id}`: {reason}")
        lines.append("")

    if result.error:
        lines.append("## Błąd cyklu")
        lines.append("")
        lines.append(f"```\n{result.error}\n```")
        lines.append("")

    return "\n".join(lines)


def write_cycle_report(
    result: CycleResult, base_dir: Path = DEFAULT_REPORTS_ROOT
) -> Path:
    cycle_dir = base_dir / result.cycle_id
    (cycle_dir / "logs").mkdir(parents=True, exist_ok=True)

    manifest = asdict(result)
    (cycle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    (cycle_dir / "summary.md").write_text(_render_summary_md(result), encoding="utf-8")
    _write_csv(cycle_dir / "candidates.csv", result.passed_trials)
    _write_csv(cycle_dir / "rejected.csv", result.rejected_trials)
    (cycle_dir / "robustness.json").write_text(
        json.dumps(result.robustness, indent=2, default=str), encoding="utf-8"
    )
    (cycle_dir / "data_quality.json").write_text(
        json.dumps(result.data_quality, indent=2, default=str), encoding="utf-8"
    )

    return cycle_dir
