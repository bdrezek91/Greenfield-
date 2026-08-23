from __future__ import annotations

import csv
import json
from pathlib import Path

from src.research.reporting import CycleResult, TrialReportRow, new_cycle_id, write_cycle_report


def _row(**overrides) -> TrialReportRow:
    base = dict(
        hypothesis_id="HYP-momentum_trend-000001",
        family="momentum_trend",
        strategy="momentum",
        symbol="BTCUSDT",
        timeframe="4h",
        status="PASSED",
        deflated_sharpe_ratio=1.1,
        probability_of_backtest_overfitting=0.1,
        oos_trades=40,
        aggregate_return_after_adverse_costs=0.03,
        aggregate_return_after_severe_costs=0.01,
        monte_carlo_risk_of_ruin=0.001,
        monte_carlo_risk_of_ruin_upper_bound_ci95=0.004,
        reason="cleared promotion gate",
    )
    base.update(overrides)
    return TrialReportRow(**base)


def _result(**overrides) -> CycleResult:
    base = dict(
        cycle_id="CYCLE-TEST",
        protocol_version=1,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:05:00Z",
        status="NO_CANDIDATE",
        notes={"hipotezy": "momentum na BTCUSDT 4h"},
    )
    base.update(overrides)
    return CycleResult(**base)


def test_new_cycle_id_format() -> None:
    cid = new_cycle_id()
    assert cid.startswith("CYCLE-")


def test_write_cycle_report_creates_all_files(tmp_path: Path) -> None:
    result = _result(rejected_trials=(_row(status="FAILED_GATE", reason="low DSR"),))
    cycle_dir = write_cycle_report(result, base_dir=tmp_path)
    assert (cycle_dir / "manifest.json").exists()
    assert (cycle_dir / "summary.md").exists()
    assert (cycle_dir / "candidates.csv").exists()
    assert (cycle_dir / "rejected.csv").exists()
    assert (cycle_dir / "robustness.json").exists()
    assert (cycle_dir / "data_quality.json").exists()
    assert (cycle_dir / "logs").is_dir()


def test_manifest_json_roundtrips_status(tmp_path: Path) -> None:
    result = _result(status="CANDIDATE", selected_candidate_hypothesis_id="HYP-x-000001")
    cycle_dir = write_cycle_report(result, base_dir=tmp_path)
    manifest = json.loads((cycle_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "CANDIDATE"
    assert manifest["selected_candidate_hypothesis_id"] == "HYP-x-000001"


def test_rejected_csv_contains_row(tmp_path: Path) -> None:
    result = _result(rejected_trials=(_row(status="FAILED_GATE", reason="low DSR"),))
    cycle_dir = write_cycle_report(result, base_dir=tmp_path)
    with (cycle_dir / "rejected.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["reason"] == "low DSR"


def test_summary_md_answers_every_question(tmp_path: Path) -> None:
    result = _result()
    cycle_dir = write_cycle_report(result, base_dir=tmp_path)
    text = (cycle_dir / "summary.md").read_text(encoding="utf-8")
    for question in [
        "Jakie hipotezy sprawdzono?",
        "Ile łącznie prób uwzględnia DSR?",
        "Jaki jest PBO?",
        "Czy istnieje nowy kandydat?",
        "Czy potrzebna jest decyzja człowieka?",
    ]:
        assert question in text


def test_summary_md_lists_skipped_families(tmp_path: Path) -> None:
    result = _result(skipped_families=(("funding_oi", "no runnable strategy yet"),))
    cycle_dir = write_cycle_report(result, base_dir=tmp_path)
    text = (cycle_dir / "summary.md").read_text(encoding="utf-8")
    assert "funding_oi" in text


def test_no_candidate_status_is_valid(tmp_path: Path) -> None:
    result = _result(status="NO_CANDIDATE")
    cycle_dir = write_cycle_report(result, base_dir=tmp_path)
    manifest = json.loads((cycle_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "NO_CANDIDATE"
    assert manifest["selected_candidate_hypothesis_id"] is None
