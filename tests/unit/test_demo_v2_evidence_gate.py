from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.execution.demo_opportunity_scanner_v2 import LIQUIDATION_FADE_CANDIDATE_ID
from src.execution.demo_v2_evidence_gate import (
    DemoV2EvidenceError,
    require_demo_v2_evidence,
)


def _write_report(
    path: Path,
    *,
    trades: int = 100,
    average: float = 0.2,
    edge: float = 0.01,
    fee_bps: float = 7.5,
) -> str:
    payload = {
        "schema_version": 1,
        "candidate_id": LIQUIDATION_FADE_CANDIDATE_ID,
        "evaluation_scope": "COARSE_IN_SAMPLE_SCREEN",
        "fees_applied": True,
        "summary": {
            "trades_taken": trades,
            "average_return_bps": average,
            "edge_over_breakeven_net_of_fees": edge,
            "round_trip_fee_bps": fee_bps,
        },
        "trades": [],
    }
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_accepts_content_addressed_positive_demo_screen(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    digest = _write_report(path)

    evidence = require_demo_v2_evidence(path, expected_sha256=digest)

    assert evidence.trades_taken == 100
    assert evidence.average_net_return_bps == 0.2


@pytest.mark.parametrize(
    ("trades", "average", "edge", "message"),
    [
        (99, 1.0, 0.1, "need at least 100"),
        (100, 0.0, 0.1, "not profitable after fees"),
        (100, 1.0, 0.0, "not above net-of-fees breakeven"),
    ],
)
def test_rejects_inadequate_demo_screen(
    tmp_path: Path, trades: int, average: float, edge: float, message: str
) -> None:
    path = tmp_path / "evidence.json"
    digest = _write_report(path, trades=trades, average=average, edge=edge)

    with pytest.raises(DemoV2EvidenceError, match=message):
        require_demo_v2_evidence(path, expected_sha256=digest)


def test_rejects_mutated_report(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    digest = _write_report(path)
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(DemoV2EvidenceError, match="SHA-256 does not match"):
        require_demo_v2_evidence(path, expected_sha256=digest)


def test_rejects_zero_or_nonconfigured_fee_assumption(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    digest = _write_report(path, fee_bps=0.0)

    with pytest.raises(DemoV2EvidenceError, match="fees do not match"):
        require_demo_v2_evidence(path, expected_sha256=digest)
