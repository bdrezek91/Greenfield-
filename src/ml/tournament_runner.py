"""Execution engine for the preregistered ML Model Tournament V1.

The runner is RESEARCH-only.  It compares frozen model trials on identical
setup rows and opens the final holdout once, after per-family selection on
development folds.  It has no dependency on any execution gateway.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score

from src.analytics.robustness import deflated_sharpe_ratio
from src.data.storage import read_klines
from src.features.pipeline import FEATURE_COLUMNS
from src.ml.calibration import brier_score, calibration_curve
from src.ml.explainability import permutation_importance
from src.ml.models.boosting import LightGBMModel, XGBoostModel
from src.ml.models.sklearn_models import (
    ExtraTreesModel,
    LogisticRegressionModel,
    RandomForestModel,
)
from src.ml.tournament import (
    BASE_COST,
    COST_SCENARIOS,
    SEED,
    SYMBOLS,
    TIMEFRAME,
    CostScenario,
    PayoffEstimate,
    PlattCalibrator,
    TournamentSplit,
    build_setup_dataset,
    common_universe_window,
    cost_aware_trade_mask,
    estimate_payoff,
    expanding_walk_forward_splits,
    split_fit_and_calibration,
)
from src.research.ledger import TrialLedger, TrialRecord


class TournamentModel(Protocol):
    def fit(self, X: pd.DataFrame, y: np.ndarray) -> None: ...
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray: ...


@dataclass(frozen=True, slots=True)
class TrialSpec:
    trial_id: str
    family: str
    parameters: dict[str, Any]
    factory: Callable[[], TournamentModel]


@dataclass(slots=True)
class FittedPrediction:
    probability: np.ndarray
    raw_probability: np.ndarray
    model: TournamentModel
    payoff: PayoffEstimate


def frozen_trial_specs(seed: int = SEED) -> tuple[TrialSpec, ...]:
    """The complete preregistered 14-trial budget."""
    specs: list[TrialSpec] = []
    for c in (0.1, 1.0):
        params = {"C": c}
        specs.append(
            TrialSpec(
                f"logistic-c{c}",
                "logistic_regression",
                params,
                partial(LogisticRegressionModel, seed=seed, C=c),
            )
        )
    for depth, leaf in ((4, 10), (8, 20)):
        params = {"max_depth": depth, "min_samples_leaf": leaf, "n_estimators": 200}
        specs.append(
            TrialSpec(
                f"random-forest-d{depth}-l{leaf}",
                "random_forest",
                params,
                partial(
                    RandomForestModel,
                    seed=seed,
                    n_estimators=200,
                    max_depth=depth,
                    min_samples_leaf=leaf,
                    n_jobs=1,
                ),
            )
        )
    for depth, leaf in ((4, 10), (8, 20)):
        params = {"max_depth": depth, "min_samples_leaf": leaf, "n_estimators": 200}
        specs.append(
            TrialSpec(
                f"extra-trees-d{depth}-l{leaf}",
                "extra_trees",
                params,
                partial(
                    ExtraTreesModel,
                    seed=seed,
                    n_estimators=200,
                    max_depth=depth,
                    min_samples_leaf=leaf,
                    n_jobs=1,
                ),
            )
        )
    xgb_grid = (
        (2, 0.03, 150, 3.0),
        (3, 0.03, 250, 3.0),
        (3, 0.07, 150, 5.0),
        (5, 0.03, 250, 5.0),
    )
    for depth, rate, estimators, child_weight in xgb_grid:
        params = {
            "max_depth": depth,
            "learning_rate": rate,
            "n_estimators": estimators,
            "min_child_weight": child_weight,
        }
        specs.append(
            TrialSpec(
                f"xgboost-d{depth}-r{rate}-n{estimators}-w{child_weight}",
                "xgboost",
                params,
                partial(
                    XGBoostModel,
                    seed=seed,
                    max_depth=depth,
                    learning_rate=rate,
                    n_estimators=estimators,
                    min_child_weight=child_weight,
                ),
            )
        )
    lgb_grid = (
        (3, 0.03, 150, 15),
        (4, 0.03, 250, 15),
        (4, 0.07, 150, 31),
        (6, 0.03, 250, 31),
    )
    for depth, rate, estimators, leaves in lgb_grid:
        params = {
            "max_depth": depth,
            "learning_rate": rate,
            "n_estimators": estimators,
            "num_leaves": leaves,
        }
        specs.append(
            TrialSpec(
                f"lightgbm-d{depth}-r{rate}-n{estimators}-l{leaves}",
                "lightgbm",
                params,
                partial(
                    LightGBMModel,
                    seed=seed,
                    max_depth=depth,
                    learning_rate=rate,
                    n_estimators=estimators,
                    num_leaves=leaves,
                ),
            )
        )
    assert len(specs) == 14
    return tuple(specs)


def load_tournament_dataset(data_dir: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    klines = {symbol: read_klines(data_dir, symbol, TIMEFRAME) for symbol in SYMBOLS}
    start, end = common_universe_window(klines)
    datasets = []
    inputs: dict[str, Any] = {}
    for symbol in SYMBOLS:
        source = klines[symbol]
        source = source[(source["timestamp"] >= start) & (source["timestamp"] <= end)].copy()
        datasets.append(build_setup_dataset(source, symbol=symbol))
        paths = sorted((data_dir / "klines" / symbol / TIMEFRAME).glob("*.parquet"))
        inputs[symbol] = {
            "rows": len(source),
            "first_timestamp": str(source["timestamp"].min()),
            "last_timestamp": str(source["timestamp"].max()),
            "files": [
                {"path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size}
                for path in paths
            ],
        }
    dataset = (
        pd.concat(datasets, ignore_index=True)
        .sort_values(["timestamp", "symbol"])
        .reset_index(drop=True)
    )
    if dataset.empty or set(dataset["symbol"]) != set(SYMBOLS):
        raise ValueError("INSUFFICIENT_DATA: every symbol needs labeled Breakout candidates")
    metadata = {
        "common_start": str(start),
        "common_end": str(end),
        "feature_columns": list(FEATURE_COLUMNS),
        "dataset_rows": len(dataset),
        "rows_per_symbol": {
            str(symbol): int(count) for symbol, count in dataset.groupby("symbol").size().items()
        },
        "inputs": inputs,
    }
    return dataset, metadata


def run_tournament(
    data_dir: Path,
    *,
    n_splits: int = 5,
    trial_ledger_path: Path | None = None,
) -> dict[str, Any]:
    dataset, dataset_metadata = load_tournament_dataset(data_dir)
    ledger = TrialLedger(trial_ledger_path) if trial_ledger_path is not None else TrialLedger()
    holdout_id = _holdout_id(dataset_metadata)
    ledger_family = "ml-model-tournament-v1"
    if ledger.holdout_already_used(ledger_family, holdout_id):
        raise ValueError(
            f"frozen holdout {holdout_id} was already used; create a new preregistered cycle"
        )
    folds, holdout = expanding_walk_forward_splits(dataset, n_splits=n_splits)
    trials: list[dict[str, Any]] = []
    specs = frozen_trial_specs()
    for spec in specs:
        fold_results = []
        status = "COMPLETE"
        error: str | None = None
        try:
            for split in folds:
                prediction = _fit_predict(dataset, split, spec)
                fold_result = _evaluate_prediction(
                    dataset,
                    split.test_index,
                    prediction.probability,
                    prediction.payoff,
                    BASE_COST,
                )
                fold_result.pop("daily_returns", None)
                fold_results.append(fold_result)
        except (RuntimeError, ValueError) as exc:
            status = "FAILED"
            error = str(exc)
        trials.append(
            {
                "trial_id": spec.trial_id,
                "family": spec.family,
                "parameters": spec.parameters,
                "status": status,
                "error": error,
                "folds": fold_results,
                "selection_score": _selection_score(fold_results),
            }
        )

    selected: dict[str, TrialSpec] = {}
    for family in {spec.family for spec in specs}:
        candidates = [
            trial
            for trial in trials
            if trial["family"] == family and trial["status"] == "COMPLETE"
        ]
        if not candidates:
            continue
        winner = max(
            candidates,
            key=lambda item: (
                item["selection_score"],
                -float(np.mean([fold["brier"] for fold in item["folds"]])),
            ),
        )
        selected[family] = next(spec for spec in specs if spec.trial_id == winner["trial_id"])

    holdout_results: list[dict[str, Any]] = []
    importance: dict[str, Any] = {}
    for family, spec in sorted(selected.items()):
        prediction = _fit_predict(dataset, holdout, spec)
        scenarios = {
            scenario.name: _evaluate_prediction(
                dataset,
                holdout.test_index,
                prediction.probability,
                prediction.payoff,
                scenario,
            )
            for scenario in COST_SCENARIOS
        }
        per_symbol: dict[str, dict[str, Any]] = {
            symbol: _evaluate_prediction(
                dataset,
                holdout.test_index[
                    dataset.iloc[holdout.test_index]["symbol"].to_numpy() == symbol
                ],
                prediction.probability[
                    dataset.iloc[holdout.test_index]["symbol"].to_numpy() == symbol
                ],
                prediction.payoff,
                BASE_COST,
            )
            for symbol in SYMBOLS
        }
        result: dict[str, Any] = {
            "family": family,
            "trial_id": spec.trial_id,
            "parameters": spec.parameters,
            "classification": _classification_metrics(
                dataset.iloc[holdout.test_index]["label"].to_numpy(dtype=int),
                prediction.probability,
            ),
            "scenarios": scenarios,
            "per_symbol": per_symbol,
            "development_stability": _development_stability(trials, spec.trial_id),
        }
        for symbol_result in per_symbol.values():
            symbol_result.pop("daily_returns", None)
        holdout_results.append(result)
        importance[family] = {
            "holdout": _importance(
                prediction.model,
                dataset.iloc[holdout.test_index][list(FEATURE_COLUMNS)],
                dataset.iloc[holdout.test_index]["label"].to_numpy(dtype=int),
            ),
            "development_fold_stability": _importance_stability(dataset, folds, spec),
        }

    global_trial_count = ledger.global_trial_count() + len(specs)
    _attach_robustness(holdout_results, n_trials=global_trial_count)
    for result in holdout_results:
        result["qualification_gate_passed"] = _qualification_gate_passed(result)
    ranking = sorted(
        holdout_results,
        key=lambda result: (
            result["qualification_gate_passed"],
            min(
                result["scenarios"]["base"]["net_pnl_return"],
                result["scenarios"]["adverse"]["net_pnl_return"],
            ),
            min(
                result["scenarios"]["base"]["net_sharpe"],
                result["scenarios"]["adverse"]["net_sharpe"],
            ),
            -result["classification"]["brier"],
        ),
        reverse=True,
    )
    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "protocol": "docs/ML_MODEL_TOURNAMENT_V1.md",
        "live_trading": False,
        "dataset": dataset_metadata,
        "split": {
            "n_development_folds": len(folds),
            "holdout_rows": len(holdout.test_index),
            "holdout_first_timestamp": str(dataset.iloc[holdout.test_index]["timestamp"].min()),
            "holdout_last_timestamp": str(dataset.iloc[holdout.test_index]["timestamp"].max()),
            "holdout_id": holdout_id,
        },
        "trial_ledger": trials,
        "selected_trials": {family: spec.trial_id for family, spec in selected.items()},
        "holdout_results": holdout_results,
        "feature_importance": importance,
        "ranking": [result["family"] for result in ranking],
        "winner": (
            ranking[0]["family"]
            if ranking and ranking[0]["qualification_gate_passed"]
            else None
        ),
        "verdict": _verdict(ranking),
    }
    # Validate the complete artifact before consuming the frozen holdout in the
    # append-only ledger. This prevents non-finite metrics from creating a
    # ledger entry for a report that cannot be persisted as strict JSON.
    json.dumps(report, allow_nan=False)
    _record_global_trials(
        ledger,
        report=report,
        specs=specs,
        holdout_id=holdout_id,
        dataset_fingerprint=_dataset_fingerprint(dataset_metadata),
    )
    return report


def _fit_predict(
    dataset: pd.DataFrame, split: TournamentSplit, spec: TrialSpec
) -> FittedPrediction:
    fit_index, calibration_index = split_fit_and_calibration(dataset, split.train_index)
    X = dataset[list(FEATURE_COLUMNS)]
    y = dataset["label"].to_numpy(dtype=int)
    model = spec.factory()
    model.fit(X.iloc[fit_index], y[fit_index])
    raw_calibration = model.predict_proba(X.iloc[calibration_index])
    calibrator = PlattCalibrator(seed=SEED)
    calibrator.fit(raw_calibration, y[calibration_index])
    raw_test = model.predict_proba(X.iloc[split.test_index])
    payoff = estimate_payoff(
        dataset.iloc[split.train_index]["gross_return"].to_numpy(dtype=float),
        y[split.train_index],
    )
    return FittedPrediction(calibrator.predict(raw_test), raw_test, model, payoff)


def _evaluate_prediction(
    dataset: pd.DataFrame,
    index: np.ndarray,
    probability: np.ndarray,
    payoff: PayoffEstimate,
    scenario: CostScenario,
) -> dict[str, Any]:
    frame = dataset.iloc[index].copy()
    if len(frame) != len(probability):
        raise ValueError("prediction rows are not aligned with evaluation rows")
    trade, expected_net = cost_aware_trade_mask(probability, payoff, scenario)
    net = np.where(trade, frame["gross_return"].to_numpy() - scenario.execution_cost_return, 0.0)
    daily = pd.Series(net, index=pd.DatetimeIndex(frame["timestamp"])).groupby(level=0).sum()
    daily = daily.resample("1D").sum().fillna(0.0)
    metrics = _return_metrics(daily, net[trade])
    metrics.update(
        {
            "scenario": scenario.name,
            "trades": int(trade.sum()),
            "waits": int((~trade).sum()),
            "turnover_notional_units": float(trade.sum() * 2),
            "fee_impact_return": float(trade.sum() * scenario.fee_bps / 10_000),
            "spread_impact_return": float(trade.sum() * scenario.spread_bps / 10_000),
            "slippage_impact_return": float(trade.sum() * scenario.slippage_bps / 10_000),
            "funding_impact_return": float(trade.sum() * scenario.funding_bps / 10_000),
            "mean_expected_net_edge": float(expected_net[trade].mean()) if trade.any() else None,
            "daily_returns": daily.tolist(),
        }
    )
    metrics.update(
        _classification_metrics(frame["label"].to_numpy(dtype=int), probability)
    )
    return metrics


def _return_metrics(daily: pd.Series, trade_returns: np.ndarray) -> dict[str, Any]:
    net_pnl = float(np.sum(trade_returns))
    std = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
    sharpe = float(daily.mean() / std * math.sqrt(365)) if std > 0 else 0.0
    downside = np.sqrt(np.mean(np.minimum(daily.to_numpy(), 0) ** 2)) if len(daily) else 0.0
    sortino = float(daily.mean() / downside * math.sqrt(365)) if downside > 0 else 0.0
    equity = 1 + daily.cumsum()
    drawdown = equity / equity.cummax() - 1
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    years = max(len(daily) / 365, 1 / 365)
    annual_return = net_pnl / years
    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    wins = trade_returns[trade_returns > 0]
    losses = trade_returns[trade_returns < 0]
    return {
        "net_pnl_return": net_pnl,
        "net_sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": float(calmar),
        "expectancy": float(trade_returns.mean()) if len(trade_returns) else 0.0,
        "average_trade": float(trade_returns.mean()) if len(trade_returns) else 0.0,
        "win_rate": float((trade_returns > 0).mean()) if len(trade_returns) else 0.0,
        "profit_factor": (
            float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
        ),
    }


def _classification_metrics(y: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    curve = calibration_curve(y, probability, n_bins=10)
    return {
        "accuracy": float(accuracy_score(y, probability >= 0.5)),
        "roc_auc": float(roc_auc_score(y, probability)) if len(np.unique(y)) > 1 else None,
        "brier": brier_score(y, probability),
        "calibration": {
            "bin_counts": curve.bin_counts.tolist(),
            "mean_predicted": _finite_or_none(curve.mean_predicted),
            "observed_frequency": _finite_or_none(curve.observed_frequency),
        },
    }


class _ProbaAdapter:
    def __init__(self, model: TournamentModel) -> None:
        self.model = model

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(X)


def _importance(model: TournamentModel, X: pd.DataFrame, y: np.ndarray) -> list[dict[str, Any]]:
    result = permutation_importance(
        _ProbaAdapter(model), X, y, brier_score, n_repeats=5, seed=SEED
    ).as_dataframe()
    return result.to_dict(orient="records")


def _importance_stability(
    dataset: pd.DataFrame, folds: list[TournamentSplit], spec: TrialSpec
) -> list[dict[str, Any]]:
    per_fold: list[pd.DataFrame] = []
    for split in folds:
        prediction = _fit_predict(dataset, split, spec)
        result = pd.DataFrame(
            _importance(
                prediction.model,
                dataset.iloc[split.test_index][list(FEATURE_COLUMNS)],
                dataset.iloc[split.test_index]["label"].to_numpy(dtype=int),
            )
        ).set_index("feature")
        per_fold.append(result["importance_mean"].rename(split.name))
    combined = pd.concat(per_fold, axis=1).reindex(FEATURE_COLUMNS)
    ranks = combined.rank(axis=0, ascending=False, method="average")
    return [
        {
            "feature": feature,
            "importance_mean_across_folds": float(combined.loc[feature].mean()),
            "importance_std_across_folds": float(combined.loc[feature].std(ddof=0)),
            "rank_std_across_folds": float(ranks.loc[feature].std(ddof=0)),
        }
        for feature in FEATURE_COLUMNS
    ]


def _selection_score(folds: list[dict[str, Any]]) -> float:
    if not folds:
        return float("-inf")
    values = np.array([fold["net_sharpe"] for fold in folds], dtype=float)
    return float(np.median(values) - np.std(values, ddof=0))


def _development_stability(
    trials: list[dict[str, Any]], trial_id: str
) -> dict[str, float]:
    trial = next(item for item in trials if item["trial_id"] == trial_id)
    sharpes = np.array([fold["net_sharpe"] for fold in trial["folds"]], dtype=float)
    return {
        "positive_net_pnl_fold_fraction": float(
            np.mean([fold["net_pnl_return"] > 0 for fold in trial["folds"]])
        ),
        "net_sharpe_std": float(sharpes.std(ddof=0)),
        "selection_score": float(trial["selection_score"]),
    }


def _attach_robustness(results: list[dict[str, Any]], *, n_trials: int) -> None:
    for result in results:
        base = result["scenarios"]["base"]
        returns = pd.Series(base.pop("daily_returns"), dtype=float)
        for scenario_name, scenario in result["scenarios"].items():
            if scenario_name != "base":
                scenario.pop("daily_returns", None)
        return_std = returns.std(ddof=1)
        unannualized = float(returns.mean() / return_std) if return_std > 0 else 0.0
        dsr = deflated_sharpe_ratio(unannualized, returns, n_trials=n_trials)
        result["robustness"] = {
            "deflated_sharpe_ratio": _optional_finite(dsr.deflated_sharpe_ratio),
            "expected_max_sharpe_under_null": _optional_finite(
                dsr.expected_max_sharpe_under_null
            ),
            "pbo": None,
            "pbo_reason": "five expanding folds are insufficient for valid CSCV partitions",
        }


def _verdict(ranking: list[dict[str, Any]]) -> str:
    if not ranking or not ranking[0]["qualification_gate_passed"]:
        return "REJECT"
    winner = ranking[0]
    base = winner["scenarios"]["base"]
    adverse = winner["scenarios"]["adverse"]
    per_symbol = winner["per_symbol"]
    positive_symbols = sum(result["net_pnl_return"] > 0 for result in per_symbol.values())
    positive_pnl = [max(0.0, result["net_pnl_return"]) for result in per_symbol.values()]
    dominance = max(positive_pnl) / sum(positive_pnl) if sum(positive_pnl) > 0 else 1.0
    dsr = winner["robustness"]["deflated_sharpe_ratio"]
    if (
        base["net_pnl_return"] > 0
        and adverse["net_pnl_return"] > 0
        and base["trades"] >= 30
        and positive_symbols >= 2
        and dominance <= 0.70
        and dsr is not None
        and dsr > 0.95
    ):
        return "PROMISING"
    return "REJECT" if base["net_pnl_return"] <= 0 else "INCONCLUSIVE"


def _qualification_gate_passed(result: dict[str, Any]) -> bool:
    base = result["scenarios"]["base"]
    adverse = result["scenarios"]["adverse"]
    return bool(
        base["net_pnl_return"] > 0
        and adverse["net_pnl_return"] > 0
        and base["trades"] >= 30
        and adverse["trades"] >= 30
    )


def _record_global_trials(
    ledger: TrialLedger,
    *,
    report: dict[str, Any],
    specs: tuple[TrialSpec, ...],
    holdout_id: str,
    dataset_fingerprint: str,
) -> None:
    selected_ids = set(report["selected_trials"].values())
    holdout_by_id = {
        result["trial_id"]: result for result in report["holdout_results"]
    }
    development_by_id = {trial["trial_id"]: trial for trial in report["trial_ledger"]}
    for spec in specs:
        development = development_by_id[spec.trial_id]
        holdout = holdout_by_id.get(spec.trial_id)
        metrics = {
            "model_family": spec.family,
            "parameters": spec.parameters,
            "selection_score": development["selection_score"],
        }
        if holdout is not None:
            metrics["holdout_base"] = {
                key: holdout["scenarios"]["base"][key]
                for key in ("net_pnl_return", "net_sharpe", "trades", "max_drawdown")
            }
            metrics["holdout_adverse"] = {
                key: holdout["scenarios"]["adverse"][key]
                for key in ("net_pnl_return", "net_sharpe", "trades", "max_drawdown")
            }
        ledger.record(
            TrialRecord(
                trial_id=ledger.next_trial_id(),
                hypothesis_id="ml-model-tournament-v1",
                parent_hypothesis_id="breakout-lookback-20",
                family="ml-model-tournament-v1",
                rationale="Preregistered setup-scoring challenger; all outcomes retained.",
                symbol=",".join(SYMBOLS),
                timeframe=TIMEFRAME,
                cost_scenario="base+adverse+severe",
                status="FAILED_GATE" if development["status"] == "COMPLETE" else "ERROR",
                dataset_fingerprint=dataset_fingerprint,
                holdout_used=spec.trial_id in selected_ids,
                holdout_id=holdout_id if spec.trial_id in selected_ids else None,
                metrics_summary=metrics,
                notes="RESEARCH/BACKTEST only; no PAPER/LIVE order capability.",
            )
        )


def _holdout_id(dataset_metadata: dict[str, Any]) -> str:
    payload = {
        "protocol": "ML_MODEL_TOURNAMENT_V1",
        "common_start": dataset_metadata["common_start"],
        "common_end": dataset_metadata["common_end"],
        "fingerprint": _dataset_fingerprint(dataset_metadata),
        "holdout_fraction": 0.2,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def _dataset_fingerprint(dataset_metadata: dict[str, Any]) -> str:
    checksums = [
        item["sha256"]
        for symbol in SYMBOLS
        for item in dataset_metadata["inputs"][symbol]["files"]
    ]
    return hashlib.sha256("|".join(checksums).encode()).hexdigest()[:20]


def write_tournament_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")


def _finite_or_none(values: np.ndarray) -> list[float | None]:
    return [float(value) if np.isfinite(value) else None for value in values]


def _optional_finite(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
