"""Causal L2-to-fill joins and empirical PAPER execution calibration."""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from src.execution.intent import IntentSide
from src.execution.simulated_adapter import SimulatedAdapterConfig


@dataclass(frozen=True, slots=True)
class TopOfBookQuote:
    symbol: str
    venue: str
    timestamp_utc: datetime
    source_sequence: int
    bid_price: float
    ask_price: float
    bid_quantity: float
    ask_quantity: float

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.venue.strip():
            raise ValueError("top-of-book quote requires symbol and venue")
        _utc(self.timestamp_utc, "quote timestamp")
        if self.source_sequence < 0:
            raise ValueError("top-of-book source sequence must be non-negative")
        values = (
            self.bid_price,
            self.ask_price,
            self.bid_quantity,
            self.ask_quantity,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("top-of-book prices and quantities must be positive")
        if self.bid_price >= self.ask_price:
            raise ValueError("top-of-book quote must not be locked or crossed")


@dataclass(frozen=True, slots=True)
class PaperOrderObservation:
    order_id: str
    symbol: str
    venue: str
    side: IntentSide
    requested_quantity: float
    decision_timestamp_utc: datetime
    submitted_at_utc: datetime
    resolved_at_utc: datetime
    filled_price: float
    filled_quantity: float
    rejected: bool
    fee_cost_quote: float
    funding_cost_quote: float

    def __post_init__(self) -> None:
        if not self.order_id.strip() or not self.symbol.strip() or not self.venue.strip():
            raise ValueError("paper observation requires order, symbol, and venue")
        decision = _utc(self.decision_timestamp_utc, "order decision timestamp")
        submitted = _utc(self.submitted_at_utc, "order submission timestamp")
        resolved = _utc(self.resolved_at_utc, "order resolution timestamp")
        if not decision <= submitted <= resolved:
            raise ValueError("paper order timestamps must be monotonic")
        if not math.isfinite(self.requested_quantity) or self.requested_quantity <= 0:
            raise ValueError("paper requested quantity must be positive")
        costs = (self.fee_cost_quote, self.funding_cost_quote)
        if any(not math.isfinite(value) for value in costs):
            raise ValueError("paper execution costs must be finite")
        if self.rejected:
            if self.filled_price != 0 or self.filled_quantity != 0:
                raise ValueError("rejected paper order cannot contain a fill")
        elif (
            not math.isfinite(self.filled_price)
            or self.filled_price <= 0
            or not math.isfinite(self.filled_quantity)
            or not 0 < self.filled_quantity <= self.requested_quantity
        ):
            raise ValueError("filled paper order has invalid price or quantity")


class JoinIssue(StrEnum):
    MISSING_QUOTE = "MISSING_QUOTE"
    STALE_QUOTE = "STALE_QUOTE"


@dataclass(frozen=True, slots=True)
class JoinedExecutionObservation:
    order: PaperOrderObservation
    quote: TopOfBookQuote | None
    quote_age_seconds: float | None
    issue: JoinIssue | None

    @property
    def valid_for_cost_calibration(self) -> bool:
        return not self.order.rejected and self.quote is not None and self.issue is None


def _group_and_sort_quotes(
    quotes: tuple[TopOfBookQuote, ...],
) -> tuple[
    dict[tuple[str, str], list[TopOfBookQuote]],
    dict[tuple[str, str], list[datetime]],
]:
    quote_groups: dict[tuple[str, str], list[TopOfBookQuote]] = defaultdict(list)
    for quote in quotes:
        quote_groups[(quote.symbol, quote.venue.lower())].append(quote)
    quote_times: dict[tuple[str, str], list[datetime]] = {}
    for key, group in quote_groups.items():
        identities = [(item.timestamp_utc.astimezone(UTC), item.source_sequence) for item in group]
        if len(set(identities)) != len(identities):
            raise ValueError("top-of-book timestamp and sequence must be unique per market")
        group.sort(
            key=lambda item: (
                item.timestamp_utc.astimezone(UTC),
                item.source_sequence,
            )
        )
        quote_times[key] = [item.timestamp_utc.astimezone(UTC) for item in group]
    return quote_groups, quote_times


def join_orders_to_prior_quotes(
    orders: tuple[PaperOrderObservation, ...],
    quotes: tuple[TopOfBookQuote, ...],
    *,
    maximum_quote_age_seconds: float,
) -> tuple[JoinedExecutionObservation, ...]:
    """Join each order to the latest same-market quote at or before decision."""

    if not math.isfinite(maximum_quote_age_seconds) or maximum_quote_age_seconds <= 0:
        raise ValueError("maximum quote age must be finite and positive")
    order_ids = [order.order_id for order in orders]
    if len(set(order_ids)) != len(order_ids):
        raise ValueError("paper order ids must be unique")
    quote_groups, quote_times = _group_and_sort_quotes(quotes)
    joined: list[JoinedExecutionObservation] = []
    for order in orders:
        key = (order.symbol, order.venue.lower())
        decision = order.decision_timestamp_utc.astimezone(UTC)
        times = quote_times.get(key, [])
        index = bisect.bisect_right(times, decision) - 1
        if index < 0:
            joined.append(JoinedExecutionObservation(order, None, None, JoinIssue.MISSING_QUOTE))
            continue
        quote = quote_groups[key][index]
        age = (decision - quote.timestamp_utc.astimezone(UTC)).total_seconds()
        issue = JoinIssue.STALE_QUOTE if age > maximum_quote_age_seconds else None
        joined.append(JoinedExecutionObservation(order, quote, age, issue))
    return tuple(joined)


@dataclass(frozen=True, slots=True)
class ExecutionCalibrationConfig:
    minimum_filled_samples_per_market: int = 100
    maximum_join_issue_fraction: float = 0.01
    maximum_observation_age_seconds: float = 7 * 24 * 3600

    def __post_init__(self) -> None:
        if self.minimum_filled_samples_per_market < 1:
            raise ValueError("execution calibration requires filled samples")
        if not 0 <= self.maximum_join_issue_fraction <= 1:
            raise ValueError("join issue fraction must be in [0, 1]")
        if (
            not math.isfinite(self.maximum_observation_age_seconds)
            or self.maximum_observation_age_seconds <= 0
        ):
            raise ValueError("maximum observation age must be positive")


@dataclass(frozen=True, slots=True)
class ExecutionBucketCalibration:
    symbol: str
    venue: str
    observation_count: int
    filled_count: int
    rejected_count: int
    partial_fill_count: int
    join_issue_count: int
    rejection_probability: float
    partial_fill_probability: float
    spread_bps_p50: float
    spread_bps_p95: float
    spread_bps_p99: float
    slippage_bps_p50: float
    slippage_bps_p95: float
    slippage_bps_p99: float
    latency_seconds_p50: float
    latency_seconds_p95: float
    latency_seconds_p99: float
    fill_ratio_p01: float
    fill_ratio_p05: float
    fee_bps_p50: float
    fee_bps_p95: float
    fee_bps_p99: float
    funding_bps_p50: float
    funding_bps_p95: float
    funding_bps_p99: float
    latest_observation_utc: datetime


@dataclass(frozen=True, slots=True)
class ExecutionCalibration:
    calibrated_at_utc: datetime
    dataset_fingerprint: str
    model_version: str
    buckets: tuple[ExecutionBucketCalibration, ...]

    def __post_init__(self) -> None:
        _utc(self.calibrated_at_utc, "execution calibration timestamp")
        if not self.dataset_fingerprint.strip() or not self.model_version.strip():
            raise ValueError("execution calibration requires dataset and model versions")
        keys = [(item.symbol, item.venue.lower()) for item in self.buckets]
        if not self.buckets or len(set(keys)) != len(keys):
            raise ValueError("execution calibration buckets must be non-empty and unique")

    def bucket(self, symbol: str, venue: str) -> ExecutionBucketCalibration:
        for item in self.buckets:
            if item.symbol == symbol and item.venue.lower() == venue.lower():
                return item
        raise KeyError(f"no execution calibration for {symbol} on {venue}")


class CalibrationScenario(StrEnum):
    BASE = "BASE"
    ADVERSE = "ADVERSE"
    SEVERE = "SEVERE"


def calibrate_execution(
    observations: tuple[JoinedExecutionObservation, ...],
    *,
    calibrated_at_utc: datetime,
    dataset_fingerprint: str,
    model_version: str,
    config: ExecutionCalibrationConfig | None = None,
) -> ExecutionCalibration:
    config = config or ExecutionCalibrationConfig()
    calibrated_at = _utc(calibrated_at_utc, "execution calibration timestamp")
    if not dataset_fingerprint.strip() or not model_version.strip():
        raise ValueError("execution calibration requires dataset and model versions")
    if any(
        item.order.decision_timestamp_utc.astimezone(UTC) > calibrated_at for item in observations
    ):
        raise ValueError("execution calibration cannot consume future observations")
    order_ids = [item.order.order_id for item in observations]
    if len(set(order_ids)) != len(order_ids):
        raise ValueError("execution calibration order ids must be unique")
    grouped: dict[tuple[str, str], list[JoinedExecutionObservation]] = defaultdict(list)
    for item in observations:
        grouped[(item.order.symbol, item.order.venue.lower())].append(item)
    buckets = tuple(
        _calibrate_bucket(symbol, venue, tuple(items), calibrated_at, config)
        for (symbol, venue), items in sorted(grouped.items())
    )
    return ExecutionCalibration(
        calibrated_at_utc=calibrated_at,
        dataset_fingerprint=dataset_fingerprint,
        model_version=model_version,
        buckets=buckets,
    )


def assumptions_from_calibration(
    calibration: ExecutionCalibration,
    *,
    symbol: str,
    venue: str,
    scenario: CalibrationScenario,
    seed: int | None = 42,
) -> SimulatedAdapterConfig:
    bucket = calibration.bucket(symbol, venue)
    if scenario == CalibrationScenario.BASE:
        spread = bucket.spread_bps_p50
        slippage = bucket.slippage_bps_p50
        latency = bucket.latency_seconds_p50
        fee = bucket.fee_bps_p50
        funding = bucket.funding_bps_p50
        minimum_fill = bucket.fill_ratio_p05
        jitter_slippage = max(0.0, bucket.slippage_bps_p95 - slippage)
        jitter_latency = max(0.0, bucket.latency_seconds_p95 - latency)
    elif scenario == CalibrationScenario.ADVERSE:
        spread = bucket.spread_bps_p95
        slippage = bucket.slippage_bps_p95
        latency = bucket.latency_seconds_p95
        fee = bucket.fee_bps_p95
        funding = bucket.funding_bps_p95
        minimum_fill = bucket.fill_ratio_p01
        jitter_slippage = max(0.0, bucket.slippage_bps_p99 - slippage)
        jitter_latency = max(0.0, bucket.latency_seconds_p99 - latency)
    else:
        spread = bucket.spread_bps_p99
        slippage = bucket.slippage_bps_p99
        latency = bucket.latency_seconds_p99
        fee = bucket.fee_bps_p99
        funding = bucket.funding_bps_p99
        minimum_fill = bucket.fill_ratio_p01
        jitter_slippage = 0.0
        jitter_latency = 0.0
    return SimulatedAdapterConfig(
        slippage_bps=max(0.0, slippage),
        latency_seconds=max(0.0, latency),
        reject_probability=bucket.rejection_probability,
        spread_bps=max(0.0, spread),
        taker_fee_bps=max(0.0, fee),
        funding_bps=max(0.0, funding),
        partial_fill_probability=bucket.partial_fill_probability,
        minimum_fill_fraction=min(1.0, max(1e-9, minimum_fill)),
        latency_jitter_seconds=jitter_latency,
        slippage_jitter_bps=jitter_slippage,
        seed=seed,
    )


MARKOUT_HORIZONS_SECONDS: tuple[float, ...] = (
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
    60.0,
)
"""+100/250/500ms and +1/2/5/10/30/60s - the fixed post-fill horizons this
module measures adverse selection at. Not a tunable knob per report; a
caller wanting different horizons passes its own tuple to
`compute_markout_calibration` explicitly."""


@dataclass(frozen=True, slots=True)
class MarkoutHorizonCalibration:
    horizon_seconds: float
    sample_count: int
    markout_bps_mean: float
    markout_bps_p50: float
    markout_bps_p05: float
    markout_bps_p95: float
    adverse_selection_probability: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.horizon_seconds) or self.horizon_seconds <= 0:
            raise ValueError("markout horizon must be positive")
        if self.sample_count < 1:
            raise ValueError("markout horizon calibration requires at least one sample")
        if not 0 <= self.adverse_selection_probability <= 1:
            raise ValueError("adverse selection probability must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class MarkoutCalibration:
    symbol: str
    venue: str
    horizons: tuple[MarkoutHorizonCalibration, ...]

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.venue.strip():
            raise ValueError("markout calibration requires symbol and venue")
        seconds = [item.horizon_seconds for item in self.horizons]
        if not self.horizons or len(set(seconds)) != len(seconds):
            raise ValueError("markout calibration horizons must be non-empty and unique")

    def horizon(self, horizon_seconds: float) -> MarkoutHorizonCalibration:
        for item in self.horizons:
            if item.horizon_seconds == horizon_seconds:
                return item
        raise KeyError(f"no markout calibration for horizon {horizon_seconds}s")


def compute_markout_calibration(
    observations: tuple[JoinedExecutionObservation, ...],
    quotes: tuple[TopOfBookQuote, ...],
    *,
    horizons_seconds: tuple[float, ...] = MARKOUT_HORIZONS_SECONDS,
) -> tuple[MarkoutCalibration, ...]:
    """Empirical post-fill markouts per (symbol, venue): did the market keep
    moving in our favor after the fill, or reverse against us (adverse
    selection / a toxic fill)?

    For each filled order and each horizon, the reference price is the mid
    of the first quote at or after `resolved_at_utc + horizon` - strictly
    AFTER the fill, by construction, since markout measures what the market
    did next. This is a post-hoc execution-quality measurement, never a
    trading signal: nothing here is fed back into a strategy's entry/exit
    decision, so looking forward from the fill is not look-ahead bias in
    the sense the rest of `src/research/` and `src/backtesting/` guard
    against.

    `markout_bps` is signed so positive always means favorable (price kept
    moving our way after a BUY moved up, after a SELL moved down);
    negative means the fill was adversely selected. A horizon with zero
    samples for a bucket (ran past the end of the available quote history)
    is simply omitted from that bucket's `horizons` - never fabricated.
    """
    if not horizons_seconds:
        raise ValueError("compute_markout_calibration requires at least one horizon")
    if any(not math.isfinite(value) or value <= 0 for value in horizons_seconds):
        raise ValueError("markout horizons must be positive and finite")
    horizons_seconds = tuple(sorted(set(horizons_seconds)))

    _quote_groups, quote_times = _group_and_sort_quotes(quotes)
    grouped: dict[tuple[str, str], list[JoinedExecutionObservation]] = defaultdict(list)
    for item in observations:
        if item.valid_for_cost_calibration:
            grouped[(item.order.symbol, item.order.venue.lower())].append(item)

    calibrations: list[MarkoutCalibration] = []
    for (symbol, venue), items in sorted(grouped.items()):
        times = quote_times.get((symbol, venue), [])
        quote_list = _quote_groups.get((symbol, venue), [])
        samples_by_horizon: dict[float, list[float]] = {h: [] for h in horizons_seconds}
        for item in items:
            order = item.order
            for horizon in horizons_seconds:
                target = order.resolved_at_utc.astimezone(UTC) + timedelta(seconds=horizon)
                index = bisect.bisect_left(times, target)
                if index >= len(times):
                    continue
                mid = (quote_list[index].bid_price + quote_list[index].ask_price) / 2
                move = mid - order.filled_price
                signed_move = move if order.side == IntentSide.BUY else -move
                samples_by_horizon[horizon].append(signed_move / order.filled_price * 10_000)
        horizon_calibrations = tuple(
            MarkoutHorizonCalibration(
                horizon_seconds=horizon,
                sample_count=len(values),
                markout_bps_mean=sum(values) / len(values),
                markout_bps_p50=_quantile(values, 0.50),
                markout_bps_p05=_quantile(values, 0.05),
                markout_bps_p95=_quantile(values, 0.95),
                adverse_selection_probability=sum(value < 0 for value in values) / len(values),
            )
            for horizon in horizons_seconds
            if (values := samples_by_horizon[horizon])
        )
        if horizon_calibrations:
            calibrations.append(
                MarkoutCalibration(symbol=symbol, venue=venue, horizons=horizon_calibrations)
            )
    return tuple(calibrations)


@dataclass(frozen=True, slots=True)
class PredictedVsRealizedExecution:
    """One market's predicted (calibrated on an earlier, disjoint sample)
    vs realized (fresh observations) execution quality - the same
    train/test discipline as the rest of `src/research/`: `predicted` must
    come from a calibration fit before the period `realized` covers,
    never refit on the sample it is being compared against."""

    symbol: str
    venue: str
    realized_sample_count: int
    predicted_spread_bps_p50: float
    realized_spread_bps_p50: float
    predicted_slippage_bps_p50: float
    realized_slippage_bps_p50: float
    predicted_fill_probability: float
    realized_fill_probability: float

    @property
    def spread_bps_error(self) -> float:
        return self.realized_spread_bps_p50 - self.predicted_spread_bps_p50

    @property
    def slippage_bps_error(self) -> float:
        return self.realized_slippage_bps_p50 - self.predicted_slippage_bps_p50

    @property
    def fill_probability_error(self) -> float:
        return self.realized_fill_probability - self.predicted_fill_probability


def compare_predicted_to_realized(
    predicted: ExecutionCalibration,
    realized_observations: tuple[JoinedExecutionObservation, ...],
    *,
    symbol: str,
    venue: str,
    config: ExecutionCalibrationConfig | None = None,
) -> PredictedVsRealizedExecution:
    """Compare a calibration's BASE-scenario prediction against what
    actually happened in a later, disjoint sample of paper executions."""
    config = config or ExecutionCalibrationConfig()
    predicted_bucket = predicted.bucket(symbol, venue)
    matching = tuple(
        item
        for item in realized_observations
        if item.order.symbol == symbol and item.order.venue.lower() == venue.lower()
    )
    if not matching:
        raise ValueError(f"no realized observations for {symbol} on {venue}")
    filled = [item for item in matching if item.valid_for_cost_calibration]
    if len(filled) < config.minimum_filled_samples_per_market:
        raise ValueError(f"insufficient realized execution samples for {symbol} on {venue}")
    realized_spread = [_spread_bps(item.quote) for item in filled if item.quote is not None]
    realized_slippage = [
        _slippage_bps(item.order, item.quote) for item in filled if item.quote is not None
    ]
    rejected = sum(item.order.rejected for item in matching)
    return PredictedVsRealizedExecution(
        symbol=symbol,
        venue=venue,
        realized_sample_count=len(matching),
        predicted_spread_bps_p50=predicted_bucket.spread_bps_p50,
        realized_spread_bps_p50=_quantile(realized_spread, 0.50),
        predicted_slippage_bps_p50=predicted_bucket.slippage_bps_p50,
        realized_slippage_bps_p50=_quantile(realized_slippage, 0.50),
        predicted_fill_probability=1 - predicted_bucket.rejection_probability,
        realized_fill_probability=1 - (rejected / len(matching)),
    )


def _spread_bps(quote: TopOfBookQuote) -> float:
    midpoint = (quote.bid_price + quote.ask_price) / 2
    return (quote.ask_price - quote.bid_price) / midpoint * 10_000


def _slippage_bps(order: PaperOrderObservation, quote: TopOfBookQuote) -> float:
    touch = quote.ask_price if order.side == IntentSide.BUY else quote.bid_price
    adverse = (
        order.filled_price - touch if order.side == IntentSide.BUY else touch - order.filled_price
    )
    return adverse / touch * 10_000


def _calibrate_bucket(
    symbol: str,
    venue: str,
    observations: tuple[JoinedExecutionObservation, ...],
    calibrated_at: datetime,
    config: ExecutionCalibrationConfig,
) -> ExecutionBucketCalibration:
    latest = max(item.order.decision_timestamp_utc.astimezone(UTC) for item in observations)
    if (calibrated_at - latest).total_seconds() > config.maximum_observation_age_seconds:
        raise ValueError(f"execution observations are stale for {symbol} on {venue}")
    issues = sum(item.issue is not None for item in observations)
    if issues / len(observations) > config.maximum_join_issue_fraction:
        raise ValueError(f"execution quote-join quality failed for {symbol} on {venue}")
    filled = [item for item in observations if item.valid_for_cost_calibration]
    if len(filled) < config.minimum_filled_samples_per_market:
        raise ValueError(f"insufficient execution samples for {symbol} on {venue}")
    rejected = sum(item.order.rejected for item in observations)
    partial = sum(item.order.filled_quantity < item.order.requested_quantity for item in filled)
    spread: list[float] = []
    slippage: list[float] = []
    latency: list[float] = []
    fill_ratio: list[float] = []
    fees: list[float] = []
    funding: list[float] = []
    for item in filled:
        order = item.order
        quote = item.quote
        assert quote is not None
        spread.append(_spread_bps(quote))
        slippage.append(_slippage_bps(order, quote))
        latency.append((order.resolved_at_utc - order.submitted_at_utc).total_seconds())
        fill_ratio.append(order.filled_quantity / order.requested_quantity)
        filled_notional = order.filled_price * order.filled_quantity
        fees.append(max(0.0, order.fee_cost_quote / filled_notional * 10_000))
        funding.append(max(0.0, order.funding_cost_quote / filled_notional * 10_000))
    return ExecutionBucketCalibration(
        symbol=symbol,
        venue=venue,
        observation_count=len(observations),
        filled_count=len(filled),
        rejected_count=rejected,
        partial_fill_count=partial,
        join_issue_count=issues,
        rejection_probability=rejected / len(observations),
        partial_fill_probability=partial / len(filled),
        spread_bps_p50=_quantile(spread, 0.50),
        spread_bps_p95=_quantile(spread, 0.95),
        spread_bps_p99=_quantile(spread, 0.99),
        slippage_bps_p50=_quantile(slippage, 0.50),
        slippage_bps_p95=_quantile(slippage, 0.95),
        slippage_bps_p99=_quantile(slippage, 0.99),
        latency_seconds_p50=_quantile(latency, 0.50),
        latency_seconds_p95=_quantile(latency, 0.95),
        latency_seconds_p99=_quantile(latency, 0.99),
        fill_ratio_p01=_quantile(fill_ratio, 0.01),
        fill_ratio_p05=_quantile(fill_ratio, 0.05),
        fee_bps_p50=_quantile(fees, 0.50),
        fee_bps_p95=_quantile(fees, 0.95),
        fee_bps_p99=_quantile(fees, 0.99),
        funding_bps_p50=_quantile(funding, 0.50),
        funding_bps_p95=_quantile(funding, 0.95),
        funding_bps_p99=_quantile(funding, 0.99),
        latest_observation_utc=latest,
    )


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
