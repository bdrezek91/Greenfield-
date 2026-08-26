"""Fail-closed minimum evidence gate for the experimental Demo v2 scalper.

This is deliberately *not* a research promotion gate.  It only prevents a
known-negative or trivially small coarse backtest from being started as a
continuous Demo process.  Research/PAPER promotion still has to pass the
strict OOS, walk-forward, multiple-testing and human-approval workflow.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from src.backtesting.instruments import load_instrument_specs
from src.execution.demo_opportunity_scanner_v2 import LIQUIDATION_FADE_CANDIDATE_ID

V2_EVIDENCE_SHA256_ENV_VAR = "GREENFIELD_DEMO_V2_EVIDENCE_SHA256"
V2_EVIDENCE_SCHEMA_VERSION = 1
V2_MINIMUM_COARSE_BACKTEST_TRADES = 100


class DemoV2EvidenceError(RuntimeError):
    """The supplied v2 evidence is missing, mutable, malformed, or inadequate."""


@dataclass(frozen=True, slots=True)
class DemoV2Evidence:
    path: Path
    sha256: str
    trades_taken: int
    average_net_return_bps: float
    edge_over_breakeven_net_of_fees: float


def require_demo_v2_evidence(path: Path, *, expected_sha256: str) -> DemoV2Evidence:
    """Verify one content-addressed, net-of-costs coarse-screen report.

    Passing this function only authorizes an experimental Bybit Demo run.  It
    never changes a candidate's Research Factory or PAPER promotion status.
    """

    if not expected_sha256 or len(expected_sha256) != 64:
        raise DemoV2EvidenceError(
            f"set {V2_EVIDENCE_SHA256_ENV_VAR} to the report's 64-character SHA-256"
        )
    try:
        int(expected_sha256, 16)
    except ValueError as exc:
        raise DemoV2EvidenceError("v2 evidence SHA-256 is not hexadecimal") from exc
    if expected_sha256 != expected_sha256.lower():
        raise DemoV2EvidenceError("v2 evidence SHA-256 must be lowercase")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DemoV2EvidenceError(f"cannot read v2 evidence report: {path}") from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise DemoV2EvidenceError("v2 evidence report SHA-256 does not match")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DemoV2EvidenceError("v2 evidence report is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise DemoV2EvidenceError("v2 evidence report root must be an object")
    if payload.get("schema_version") != V2_EVIDENCE_SCHEMA_VERSION:
        raise DemoV2EvidenceError("unsupported v2 evidence schema")
    if payload.get("candidate_id") != LIQUIDATION_FADE_CANDIDATE_ID:
        raise DemoV2EvidenceError("v2 evidence belongs to another candidate")
    if payload.get("evaluation_scope") != "COARSE_IN_SAMPLE_SCREEN":
        raise DemoV2EvidenceError("v2 evidence evaluation scope is invalid")
    if payload.get("fees_applied") is not True:
        raise DemoV2EvidenceError("v2 evidence must explicitly include fees")
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise DemoV2EvidenceError("v2 evidence summary is missing")
    trades = _integer(summary, "trades_taken")
    average = _finite_float(summary, "average_return_bps")
    edge = _finite_float(summary, "edge_over_breakeven_net_of_fees")
    report_fee_bps = _finite_float(summary, "round_trip_fee_bps")
    instrument = load_instrument_specs(exchange="bybit")
    configured_fee_bps = float((instrument.maker_fee + instrument.taker_fee) * 10_000)
    if not math.isclose(report_fee_bps, configured_fee_bps, rel_tol=0, abs_tol=1e-12):
        raise DemoV2EvidenceError("v2 evidence fees do not match configured Bybit fees")
    if trades < V2_MINIMUM_COARSE_BACKTEST_TRADES:
        raise DemoV2EvidenceError(
            f"v2 coarse screen has {trades} trades; "
            f"need at least {V2_MINIMUM_COARSE_BACKTEST_TRADES}"
        )
    if average <= 0:
        raise DemoV2EvidenceError("v2 coarse screen is not profitable after fees")
    if edge <= 0:
        raise DemoV2EvidenceError("v2 win rate is not above net-of-fees breakeven")
    return DemoV2Evidence(path, actual_sha256, trades, average, edge)


def _integer(summary: dict[object, object], key: str) -> int:
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DemoV2EvidenceError(f"v2 evidence {key} must be a non-negative integer")
    return value


def _finite_float(summary: dict[object, object], key: str) -> float:
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DemoV2EvidenceError(f"v2 evidence {key} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise DemoV2EvidenceError(f"v2 evidence {key} must be finite")
    return result
