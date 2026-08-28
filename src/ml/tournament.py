"""Shared, causal protocol primitives for ML Model Tournament V1.

This module does not choose a winner and cannot submit orders.  It builds one
meta-label dataset for every challenger, defines the frozen chronological
splits, calibrates probabilities on a train-only calibration tail, and turns
probabilities into TRADE/WAIT through an explicit cost-aware expected-value
gate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from src.features.pipeline import FEATURE_COLUMNS, build_feature_matrix
from src.ml.labels import triple_barrier_outcome

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAME = "1h"
LOOKBACK_BARS = 20
HORIZON_BARS = 24
SEED = 42
DEFAULT_EMBARGO = pd.Timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class CostScenario:
    name: str
    fee_bps: float
    spread_bps: float
    slippage_bps: float
    funding_bps: float
    safety_margin_bps: float = 5.0

    @property
    def execution_cost_return(self) -> float:
        return (self.fee_bps + self.spread_bps + self.slippage_bps + self.funding_bps) / 10_000

    @property
    def safety_margin_return(self) -> float:
        return self.safety_margin_bps / 10_000


BASE_COST = CostScenario("base", fee_bps=11, spread_bps=2, slippage_bps=4, funding_bps=3)
ADVERSE_COST = CostScenario(
    "adverse", fee_bps=16.5, spread_bps=3, slippage_bps=8, funding_bps=4.5
)
SEVERE_COST = CostScenario(
    "severe", fee_bps=22, spread_bps=4, slippage_bps=16, funding_bps=6
)
COST_SCENARIOS = (BASE_COST, ADVERSE_COST, SEVERE_COST)


@dataclass(frozen=True, slots=True)
class TournamentSplit:
    name: str
    train_index: np.ndarray
    test_index: np.ndarray


@dataclass(frozen=True, slots=True)
class PayoffEstimate:
    mean_winning_gross_return: float
    mean_losing_gross_return: float


class PlattCalibrator:
    """One-dimensional sigmoid calibrator fitted only on a held-out train tail."""

    def __init__(self, *, seed: int = SEED) -> None:
        self._model = LogisticRegression(random_state=seed, solver="lbfgs")
        self._fitted = False

    def fit(self, raw_probability: np.ndarray, y: np.ndarray) -> None:
        probabilities = _valid_probabilities(raw_probability)
        labels = np.asarray(y, dtype=int)
        if len(probabilities) != len(labels) or len(probabilities) < 10:
            raise ValueError("calibration probabilities/labels must be aligned with >=10 rows")
        if not np.array_equal(np.unique(labels), np.array([0, 1])):
            raise ValueError("calibration window must contain both labels")
        self._model.fit(_logit(probabilities).reshape(-1, 1), labels)
        self._fitted = True

    def predict(self, raw_probability: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("calibrator must be fitted before prediction")
        probabilities = _valid_probabilities(raw_probability)
        return self._model.predict_proba(_logit(probabilities).reshape(-1, 1))[:, 1]


def build_setup_dataset(
    klines: pd.DataFrame,
    *,
    symbol: str,
    lookback_bars: int = LOOKBACK_BARS,
    horizon_bars: int = HORIZON_BARS,
    label_cost: CostScenario = BASE_COST,
) -> pd.DataFrame:
    """Build non-overlapping Breakout candidates with causal features/labels."""
    return _build_setup_dataset(
        klines,
        symbol=symbol,
        lookback_bars=lookback_bars,
        horizon_bars=horizon_bars,
        label_cost=label_cost,
        triple_barrier=False,
    )


def build_triple_barrier_setup_dataset(
    klines: pd.DataFrame,
    *,
    symbol: str,
    lookback_bars: int = LOOKBACK_BARS,
    horizon_bars: int = HORIZON_BARS,
    label_cost: CostScenario = BASE_COST,
    profit_take_atr: float = 2.0,
    stop_loss_atr: float = 1.0,
) -> pd.DataFrame:
    """Build the matched Breakout dataset with frozen triple-barrier labels."""
    return _build_setup_dataset(
        klines,
        symbol=symbol,
        lookback_bars=lookback_bars,
        horizon_bars=horizon_bars,
        label_cost=label_cost,
        triple_barrier=True,
        profit_take_atr=profit_take_atr,
        stop_loss_atr=stop_loss_atr,
    )


def _build_setup_dataset(
    klines: pd.DataFrame,
    *,
    symbol: str,
    lookback_bars: int,
    horizon_bars: int,
    label_cost: CostScenario,
    triple_barrier: bool,
    profit_take_atr: float = 2.0,
    stop_loss_atr: float = 1.0,
) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(klines.columns)
    if missing:
        raise ValueError(f"klines missing required columns: {sorted(missing)}")
    if symbol not in SYMBOLS:
        raise ValueError(f"symbol must be one of {SYMBOLS}")
    if lookback_bars < 2 or horizon_bars < 1:
        raise ValueError("lookback must be >=2 and horizon must be >=1")

    frame = klines.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    if frame.empty or not frame["timestamp"].is_monotonic_increasing:
        raise ValueError("klines must contain a non-empty chronological series")
    if frame["timestamp"].dt.tz is None:
        raise ValueError("kline timestamps must be timezone-aware")

    features = build_feature_matrix(frame)
    prior_high = frame["high"].shift(1).rolling(lookback_bars).max()
    prior_low = frame["low"].shift(1).rolling(lookback_bars).min()
    long_candidate = frame["close"] > prior_high
    short_candidate = frame["close"] < prior_low

    rows: list[dict[str, object]] = []
    blocked_through = -1
    last_labeled_index = len(frame) - horizon_bars - 1
    for candidate_index in np.flatnonzero((long_candidate | short_candidate).to_numpy()):
        index = int(candidate_index)
        if index <= blocked_through or index > last_labeled_index:
            continue
        feature_row = features.iloc[index]
        if feature_row[list(FEATURE_COLUMNS)].isna().any():
            continue
        values = feature_row[list(FEATURE_COLUMNS)].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            continue
        side = 1 if bool(long_candidate.iloc[index]) else -1
        entry_price = float(frame.at[index, "close"])
        if triple_barrier:
            outcome = triple_barrier_outcome(
                frame,
                index=index,
                side=side,
                atr=float(feature_row["atr"]),
                horizon_bars=horizon_bars,
                profit_take_atr=profit_take_atr,
                stop_loss_atr=stop_loss_atr,
                label_cost_return=label_cost.execution_cost_return,
            )
            exit_price = outcome.exit_price
            gross_return = outcome.gross_return
            label_end_time = outcome.label_end_time
            label = outcome.label
            barrier = outcome.barrier
        else:
            exit_price = float(frame.at[index + horizon_bars, "close"])
            gross_return = side * (exit_price / entry_price - 1.0)
            label_end_time = frame.at[index + horizon_bars, "timestamp"]
            label = int(gross_return - label_cost.execution_cost_return > 0)
        row: dict[str, object] = {
            "timestamp": frame.at[index, "timestamp"],
            "label_end_time": label_end_time,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "gross_return": gross_return,
            "label": label,
        }
        if triple_barrier:
            row["barrier"] = barrier
        row.update({column: float(feature_row[column]) for column in FEATURE_COLUMNS})
        rows.append(row)
        blocked_through = index + horizon_bars
    return pd.DataFrame(rows)


def common_universe_window(
    klines_by_symbol: dict[str, pd.DataFrame],
) -> tuple[pd.Timestamp, pd.Timestamp]:
    if set(klines_by_symbol) != set(SYMBOLS):
        raise ValueError(f"dataset must contain exactly {SYMBOLS}")
    if any(frame.empty for frame in klines_by_symbol.values()):
        raise ValueError("all symbols need non-empty klines")
    start = max(pd.Timestamp(frame["timestamp"].min()) for frame in klines_by_symbol.values())
    end = min(pd.Timestamp(frame["timestamp"].max()) for frame in klines_by_symbol.values())
    if start >= end:
        raise ValueError("symbols have no common chronological window")
    return start, end


def expanding_walk_forward_splits(
    dataset: pd.DataFrame,
    *,
    n_splits: int = 5,
    holdout_fraction: float = 0.2,
    embargo: pd.Timedelta = DEFAULT_EMBARGO,
) -> tuple[list[TournamentSplit], TournamentSplit]:
    """True past-only expanding folds plus a one-time final holdout.

    Split boundaries use unique timestamps, so simultaneous BTC/ETH/SOL
    candidates always remain in the same side of a boundary.
    """
    if n_splits < 2 or not 0.1 <= holdout_fraction <= 0.4:
        raise ValueError("invalid split count or holdout fraction")
    required = {"timestamp", "label_end_time", "symbol", "label"}
    if required - set(dataset.columns):
        raise ValueError("dataset lacks tournament split columns")
    ordered = dataset.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    if not ordered.index.equals(dataset.reset_index(drop=True).index) or not dataset[
        "timestamp"
    ].is_monotonic_increasing:
        raise ValueError("dataset must already be sorted chronologically")
    unique_times = pd.Index(ordered["timestamp"].drop_duplicates())
    if len(unique_times) < (n_splits + 2) * 10:
        raise ValueError("insufficient unique timestamps for frozen walk-forward protocol")

    holdout_position = int(len(unique_times) * (1 - holdout_fraction))
    holdout_boundary = pd.Timestamp(unique_times[holdout_position])
    holdout_test_start = holdout_boundary + embargo
    development_times = unique_times[unique_times < holdout_boundary]
    bounds = np.linspace(0, len(development_times), n_splits + 2, dtype=int)
    folds: list[TournamentSplit] = []
    for fold in range(n_splits):
        boundary = pd.Timestamp(development_times[bounds[fold + 1]])
        next_position = int(bounds[fold + 2])
        next_boundary = (
            holdout_boundary
            if next_position == len(development_times)
            else pd.Timestamp(development_times[next_position])
        )
        test_start = boundary + embargo
        train_mask = (ordered["timestamp"] < boundary) & (
            ordered["label_end_time"] < boundary
        )
        test_mask = (ordered["timestamp"] >= test_start) & (
            ordered["timestamp"] < next_boundary
        )
        train_index = np.flatnonzero(train_mask.to_numpy())
        test_index = np.flatnonzero(test_mask.to_numpy())
        _validate_split(ordered, train_index, test_index, name=f"fold-{fold}")
        folds.append(TournamentSplit(f"fold-{fold}", train_index, test_index))

    holdout_train = np.flatnonzero(
        (
            (ordered["timestamp"] < holdout_boundary)
            & (ordered["label_end_time"] < holdout_boundary)
        ).to_numpy()
    )
    holdout_test = np.flatnonzero((ordered["timestamp"] >= holdout_test_start).to_numpy())
    _validate_split(ordered, holdout_train, holdout_test, name="holdout")
    return folds, TournamentSplit("holdout", holdout_train, holdout_test)


def split_fit_and_calibration(
    dataset: pd.DataFrame, train_index: np.ndarray, *, calibration_fraction: float = 0.2
) -> tuple[np.ndarray, np.ndarray]:
    if not 0.1 <= calibration_fraction <= 0.4:
        raise ValueError("calibration_fraction must be within [0.1, 0.4]")
    subset = dataset.iloc[train_index].sort_values(["timestamp", "symbol"])
    unique_times = pd.Index(subset["timestamp"].drop_duplicates())
    cut = int(len(unique_times) * (1 - calibration_fraction))
    if cut < 10 or cut >= len(unique_times):
        raise ValueError("insufficient train history for calibration tail")
    boundary = pd.Timestamp(unique_times[cut])
    fit = subset[(subset["timestamp"] < boundary) & (subset["label_end_time"] < boundary)]
    calibration = subset[subset["timestamp"] >= boundary]
    fit_index = fit.index.to_numpy(dtype=int)
    calibration_index = calibration.index.to_numpy(dtype=int)
    _validate_split(dataset, fit_index, calibration_index, name="fit/calibration")
    return fit_index, calibration_index


def estimate_payoff(gross_returns: np.ndarray, labels: np.ndarray) -> PayoffEstimate:
    returns = np.asarray(gross_returns, dtype=float)
    outcomes = np.asarray(labels, dtype=int)
    if len(returns) != len(outcomes) or not np.array_equal(np.unique(outcomes), np.array([0, 1])):
        raise ValueError("payoff returns/labels must be aligned and contain both classes")
    positive = returns[outcomes == 1]
    negative = returns[outcomes == 0]
    if len(positive) == 0 or len(negative) == 0:
        raise ValueError("payoff estimation requires both training outcome classes")
    return PayoffEstimate(float(positive.mean()), float(negative.mean()))


def cost_aware_trade_mask(
    calibrated_probability: np.ndarray,
    payoff: PayoffEstimate,
    scenario: CostScenario,
) -> tuple[np.ndarray, np.ndarray]:
    probability = _valid_probabilities(calibrated_probability)
    expected_gross = (
        probability * payoff.mean_winning_gross_return
        + (1 - probability) * payoff.mean_losing_gross_return
    )
    expected_net = expected_gross - scenario.execution_cost_return
    return expected_net > scenario.safety_margin_return, expected_net


def _validate_split(
    dataset: pd.DataFrame, train_index: np.ndarray, test_index: np.ndarray, *, name: str
) -> None:
    if len(train_index) == 0 or len(test_index) == 0:
        raise ValueError(f"{name} contains an empty train/test side")
    if np.intersect1d(train_index, test_index).size:
        raise ValueError(f"{name} train/test overlap")
    train = dataset.iloc[train_index]
    test = dataset.iloc[test_index]
    if train["label_end_time"].max() >= test["timestamp"].min():
        raise ValueError(f"{name} violates label purging")
    if train["timestamp"].max() >= test["timestamp"].min():
        raise ValueError(f"{name} is not chronological")


def _valid_probabilities(values: np.ndarray) -> np.ndarray:
    probabilities = np.asarray(values, dtype=float).reshape(-1)
    if not np.isfinite(probabilities).all() or ((probabilities < 0) | (probabilities > 1)).any():
        raise ValueError("probabilities must be finite and in [0, 1]")
    return probabilities


def _logit(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped))
