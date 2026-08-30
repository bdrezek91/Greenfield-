from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from scripts.evaluate_selective_gate_v0 import app


def _write_report(path: Path, period: str) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "EXPLORATORY_ONLY",
                "promotion_allowed": False,
                "period": period,
                "results": [],
            }
        ),
        encoding="utf-8",
    )


def test_cli_freezes_gate_config_and_writes_idempotently(tmp_path: Path) -> None:
    june = tmp_path / "june.json"
    july = tmp_path / "july.json"
    output = tmp_path / "gate.json"
    _write_report(june, "2026-06")
    _write_report(july, "2026-07")
    arguments = [
        "--reports",
        str(june),
        "--reports",
        str(july),
        "--output",
        str(output),
        "--no-risk-veto",
    ]

    first = CliRunner().invoke(app, arguments)
    second = CliRunner().invoke(app, arguments)

    assert first.exit_code == 0
    assert second.exit_code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["config"]["execution_scenario"] == "taker_taker"
    assert report["config"]["minimum_mean_net_bps"] == 3.0
    assert report["risk_veto"] is False
    assert [item["period"] for item in report["input_reports"]] == ["2026-06", "2026-07"]
    assert all(len(item["sha256"]) == 64 for item in report["input_reports"])


def test_cli_rejects_immutable_report_collision(tmp_path: Path) -> None:
    june = tmp_path / "june.json"
    july = tmp_path / "july.json"
    output = tmp_path / "gate.json"
    _write_report(june, "2026-06")
    _write_report(july, "2026-07")
    output.write_text("{}\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "--reports",
            str(june),
            "--reports",
            str(july),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert "immutable selective-gate report collision" in str(result.exception)
