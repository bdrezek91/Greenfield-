"""Matched development screen for preregistered Triple Barrier Labels V1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.analytics.robustness import deflated_sharpe_ratio
from src.data.storage import read_klines
from src.ml.tournament import (
    BASE_COST,
    COST_SCENARIOS,
    SYMBOLS,
    TIMEFRAME,
    build_triple_barrier_setup_dataset,
    expanding_walk_forward_splits,
)
from src.ml.tournament_runner import (
    TrialSpec,
    _evaluate_prediction,
    _fit_predict,
    frozen_trial_specs,
    load_tournament_dataset,
)
from src.research.ledger import TrialLedger, TrialRecord

CONSUMED_V1_HOLDOUT_START = pd.Timestamp("2025-08-29T15:00:00Z")
PROTOCOL = "docs/TRIPLE_BARRIER_LABELS_V1.md"
HYPOTHESIS_ID = "triple-barrier-labels-v1"
SELECTED_TRIAL_IDS = (
    "logistic-c0.1",
    "random-forest-d4-l10",
    "extra-trees-d8-l20",
    "xgboost-d3-r0.03-n250-w3.0",
    "lightgbm-d3-r0.03-n150-l15",
)


def frozen_label_specs() -> tuple[TrialSpec, ...]:
    by_id = {spec.trial_id: spec for spec in frozen_trial_specs()}
    return tuple(by_id[trial_id] for trial_id in SELECTED_TRIAL_IDS)


def load_matched_label_datasets(
    data_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    fixed, metadata = load_tournament_dataset(data_dir)
    fixed = fixed[fixed["label_end_time"] < CONSUMED_V1_HOLDOUT_START].reset_index(
        drop=True
    )
    triple_frames = []
    start = pd.Timestamp(metadata["common_start"])
    end = pd.Timestamp(metadata["common_end"])
    for symbol in SYMBOLS:
        source = read_klines(data_dir, symbol, TIMEFRAME)
        source = source[(source["timestamp"] >= start) & (source["timestamp"] <= end)]
        triple_frames.append(build_triple_barrier_setup_dataset(source, symbol=symbol))
    triple_all = (
        pd.concat(triple_frames, ignore_index=True)
        .sort_values(["timestamp", "symbol"])
        .reset_index(drop=True)
    )
    keys = ["timestamp", "symbol", "side"]
    fixed_index = pd.MultiIndex.from_frame(fixed[keys])
    triple_indexed = triple_all.set_index(keys, drop=False)
    if not fixed_index.isin(triple_indexed.index).all():
        raise ValueError("fixed and triple datasets do not share identical candidates")
    triple = triple_indexed.loc[fixed_index].reset_index(drop=True)
    if not fixed[keys].equals(triple[keys]):
        raise ValueError("matched label datasets are not aligned")
    metadata = {
        **metadata,
        "development_cutoff_exclusive": str(CONSUMED_V1_HOLDOUT_START),
        "matched_rows": len(fixed),
        "fixed_positive_rate": float(fixed["label"].mean()),
        "triple_positive_rate": float(triple["label"].mean()),
        "triple_barrier_counts": {
            str(key): int(value) for key, value in triple["barrier"].value_counts().items()
        },
    }
    return fixed, triple, metadata


def run_triple_barrier_screen(
    data_dir: Path,
    *,
    trial_ledger_path: Path,
    n_splits: int = 5,
) -> dict[str, Any]:
    fixed, triple, metadata = load_matched_label_datasets(data_dir)
    ledger = TrialLedger(trial_ledger_path)
    fingerprint = _fingerprint(fixed, triple)
    if any(
        row.hypothesis_id == HYPOTHESIS_ID and row.dataset_fingerprint == fingerprint
        for row in ledger.load_all()
    ):
        raise ValueError("this Triple Barrier dataset fingerprint was already evaluated")
    folds, _unused_development_tail = expanding_walk_forward_splits(
        fixed, n_splits=n_splits
    )
    specs = frozen_label_specs()
    trial_count = ledger.global_trial_count() + len(specs) * 2
    results = []
    for label_name, dataset in (("fixed_horizon", fixed), ("triple_barrier", triple)):
        for spec in specs:
            results.append(
                _run_matched_trial(
                    dataset,
                    purge_reference=fixed,
                    folds=folds,
                    spec=spec,
                    label_name=label_name,
                    n_trials=trial_count,
                )
            )
    comparisons = _comparisons(results)
    promising = [row for row in comparisons if row["development_gate_passed"]]
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "protocol": PROTOCOL,
        "live_trading": False,
        "holdout_used": False,
        "maximum_status": "DEVELOPMENT_PROMISING_NOT_PROMOTABLE",
        "dataset": metadata,
        "dataset_fingerprint": fingerprint,
        "split": {
            "n_development_folds": len(folds),
            "unused_development_tail": True,
            "consumed_v1_holdout_excluded": True,
        },
        "trials": results,
        "comparisons": comparisons,
        "verdict": (
            "DEVELOPMENT_PROMISING_NOT_PROMOTABLE" if promising else "REJECT"
        ),
        "promising_families": [row["family"] for row in promising],
    }
    json.dumps(report, allow_nan=False)
    _record_trials(ledger, report, specs, fingerprint)
    return report


def _run_matched_trial(
    dataset: pd.DataFrame,
    *,
    purge_reference: pd.DataFrame,
    folds: list[Any],
    spec: TrialSpec,
    label_name: str,
    n_trials: int,
) -> dict[str, Any]:
    fold_rows = []
    base_daily: list[float] = []
    for split in folds:
        prediction = _fit_predict(
            dataset, split, spec, purge_dataset=purge_reference
        )
        scenarios = {}
        for scenario in COST_SCENARIOS:
            metrics = _evaluate_prediction(
                dataset,
                split.test_index,
                prediction.probability,
                prediction.payoff,
                scenario,
            )
            if scenario.name == "base":
                base_daily.extend(metrics["daily_returns"])
            metrics.pop("daily_returns", None)
            scenarios[scenario.name] = metrics
        per_symbol: dict[str, dict[str, dict[str, Any]]] = {}
        test_symbols = dataset.iloc[split.test_index]["symbol"].to_numpy()
        for symbol in SYMBOLS:
            mask = test_symbols == symbol
            symbol_index = split.test_index[mask]
            probability = prediction.probability[mask]
            per_symbol[symbol] = {}
            for scenario in (BASE_COST, COST_SCENARIOS[1]):
                metrics = _evaluate_prediction(
                    dataset,
                    symbol_index,
                    probability,
                    prediction.payoff,
                    scenario,
                )
                metrics.pop("daily_returns", None)
                per_symbol[symbol][scenario.name] = metrics
        fold_rows.append({"fold": split.name, "scenarios": scenarios, "per_symbol": per_symbol})
    returns = pd.Series(base_daily, dtype=float)
    std = returns.std(ddof=1)
    observed_sharpe = float(returns.mean() / std) if std > 0 else 0.0
    dsr = deflated_sharpe_ratio(observed_sharpe, returns, n_trials=n_trials)
    return {
        "trial_id": f"{label_name}:{spec.trial_id}",
        "label": label_name,
        "family": spec.family,
        "parameters": spec.parameters,
        "folds": fold_rows,
        "summary": _summarize_folds(fold_rows),
        "robustness": {
            "deflated_sharpe_ratio": _finite_or_none(dsr.deflated_sharpe_ratio),
            "expected_max_sharpe_under_null": _finite_or_none(
                dsr.expected_max_sharpe_under_null
            ),
            "pbo": None,
            "pbo_reason": "five expanding folds are insufficient for valid CSCV partitions",
        },
    }


def _summarize_folds(folds: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = {}
    for scenario in ("base", "adverse", "severe"):
        rows = [fold["scenarios"][scenario] for fold in folds]
        scenarios[scenario] = {
            "net_pnl_return": float(sum(row["net_pnl_return"] for row in rows)),
            "trades": int(sum(row["trades"] for row in rows)),
            "median_net_sharpe": float(np.median([row["net_sharpe"] for row in rows])),
            "positive_fold_fraction": float(
                np.mean([row["net_pnl_return"] > 0 for row in rows])
            ),
            "worst_max_drawdown": float(min(row["max_drawdown"] for row in rows)),
        }
    per_symbol: dict[str, dict[str, dict[str, Any]]] = {}
    for symbol in SYMBOLS:
        per_symbol[symbol] = {}
        for scenario in ("base", "adverse"):
            rows = [fold["per_symbol"][symbol][scenario] for fold in folds]
            per_symbol[symbol][scenario] = {
                "net_pnl_return": float(sum(row["net_pnl_return"] for row in rows)),
                "trades": int(sum(row["trades"] for row in rows)),
            }
    test_rows = sum(
        fold["scenarios"]["base"]["trades"]
        + fold["scenarios"]["base"]["waits"]
        for fold in folds
    )
    brier = sum(
        fold["scenarios"]["base"]["brier"]
        * (fold["scenarios"]["base"]["trades"] + fold["scenarios"]["base"]["waits"])
        for fold in folds
    ) / test_rows
    return {"scenarios": scenarios, "per_symbol": per_symbol, "brier": float(brier)}


def _comparisons(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    families = sorted({row["family"] for row in results})
    for family in families:
        fixed = next(
            row
            for row in results
            if row["family"] == family and row["label"] == "fixed_horizon"
        )
        triple = next(
            row
            for row in results
            if row["family"] == family and row["label"] == "triple_barrier"
        )
        base = triple["summary"]["scenarios"]["base"]
        adverse = triple["summary"]["scenarios"]["adverse"]
        fixed_adverse = fixed["summary"]["scenarios"]["adverse"]
        symbol_pnl = [
            triple["summary"]["per_symbol"][symbol]["adverse"]["net_pnl_return"]
            for symbol in SYMBOLS
        ]
        positive = [max(0.0, value) for value in symbol_pnl]
        dominance = max(positive) / sum(positive) if sum(positive) > 0 else 1.0
        sharpe_improvement = (
            adverse["median_net_sharpe"] - fixed_adverse["median_net_sharpe"]
        )
        dsr = triple["robustness"]["deflated_sharpe_ratio"]
        passed = bool(
            sharpe_improvement >= 0.25
            and base["net_pnl_return"] > 0
            and adverse["net_pnl_return"] > 0
            and base["trades"] >= 30
            and adverse["trades"] >= 30
            and sum(value > 0 for value in symbol_pnl) >= 2
            and triple["summary"]["brier"] <= fixed["summary"]["brier"] + 0.01
            and dominance <= 0.70
            and dsr is not None
            and dsr > 0.95
        )
        output.append(
            {
                "family": family,
                "adverse_median_sharpe_improvement": float(sharpe_improvement),
                "brier_change": float(
                    triple["summary"]["brier"] - fixed["summary"]["brier"]
                ),
                "positive_adverse_symbols": int(sum(value > 0 for value in symbol_pnl)),
                "positive_pnl_dominance": float(dominance),
                "development_gate_passed": passed,
            }
        )
    return output


def _record_trials(
    ledger: TrialLedger,
    report: dict[str, Any],
    specs: tuple[TrialSpec, ...],
    fingerprint: str,
) -> None:
    by_trial = {row["trial_id"]: row for row in report["trials"]}
    passed_families = set(report["promising_families"])
    for label_name in ("fixed_horizon", "triple_barrier"):
        for spec in specs:
            result = by_trial[f"{label_name}:{spec.trial_id}"]
            ledger.record(
                TrialRecord(
                    trial_id=ledger.next_trial_id(),
                    hypothesis_id=HYPOTHESIS_ID,
                    parent_hypothesis_id="ml-model-tournament-v1",
                    family="triple-barrier-labels-v1",
                    rationale="Preregistered matched fixed-vs-path-dependent label screen.",
                    symbol=",".join(SYMBOLS),
                    timeframe=TIMEFRAME,
                    cost_scenario="base+adverse+severe",
                    status=(
                        "PASSED"
                        if label_name == "triple_barrier" and spec.family in passed_families
                        else "FAILED_GATE"
                    ),
                    dataset_fingerprint=fingerprint,
                    holdout_used=False,
                    metrics_summary={
                        "model_family": spec.family,
                        "label": label_name,
                        "summary": result["summary"],
                        "robustness": result["robustness"],
                    },
                    notes="DEVELOPMENT only; consumed V1 holdout excluded; no promotion.",
                )
            )


def _fingerprint(fixed: pd.DataFrame, triple: pd.DataFrame) -> str:
    hasher = hashlib.sha256()
    hasher.update(HYPOTHESIS_ID.encode())
    hasher.update(str(CONSUMED_V1_HOLDOUT_START).encode())
    fixed_columns = [
        "timestamp",
        "symbol",
        "side",
        "label_end_time",
        "label",
        "gross_return",
    ]
    triple_columns = [*fixed_columns, "barrier"]
    for frame, columns in ((fixed, fixed_columns), (triple, triple_columns)):
        hashed = pd.util.hash_pandas_object(frame[columns], index=False).to_numpy(
            dtype=np.uint64
        )
        hasher.update(hashed.tobytes())
    return hasher.hexdigest()[:20]


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def write_triple_barrier_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
