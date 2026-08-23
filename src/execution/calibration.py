"""Causal L2-to-fill joins and empirical PAPER execution calibration."""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
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
    quote_groups: dict[tuple[str, str], list[TopOfBookQuote]] = defaultdict(list)
    for quote in quotes:
        quote_groups[(quote.symbol, quote.venue.lower())].append(quote)
    quote_times: dict[tuple[str, str], list[datetime]] = {}
    for key, group in quote_groups.items():
        identities = [
            (item.timestamp_utc.astimezone(UTC), item.source_sequence) for item in group
        ]
        if len(set(identities)) != len(identities):
            raise ValueError("top-of-book timestamp and sequence must be unique per market")
        group.sort(
            key=lambda item: (
                item.timestamp_utc.astimezone(UTC),
                item.source_sequence,
            )
        )
        quote_times[key] = [item.timestamp_utc.astimezone(UTC) for item in group]
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
        item.order.decision_timestamp_utc.astimezone(UTC) > calibrated_at
        for item in observations
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


def _calibrate_bucket(
    symbol: str,
    venue: str,
    observations: tuple[JoinedExecutionObservation, ...],
    calibrated_at: datetime,
    config: ExecutionCalibrationConfig,
) -> ExecutionBucketCalibration:
    latest = max(
        item.order.decision_timestamp_utc.astimezone(UTC) for item in observations
    )
    if (calibrated_at - latest).total_seconds() > config.maximum_observation_age_seconds:
        raise ValueError(f"execution observations are stale for {symbol} on {venue}")
    issues = sum(item.issue is not None for item in observations)
    if issues / len(observations) > config.maximum_join_issue_fraction:
        raise ValueError(f"execution quote-join quality failed for {symbol} on {venue}")
    filled = [item for item in observations if item.valid_for_cost_calibration]
    if len(filled) < config.minimum_filled_samples_per_market:
        raise ValueError(f"insufficient execution samples for {symbol} on {venue}")
    rejected = sum(item.order.rejected for item in observations)
    partial = sum(
        item.order.filled_quantity < item.order.requested_quantity for item in filled
    )
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
        midpoint = (quote.bid_price + quote.ask_price) / 2
        spread.append((quote.ask_price - quote.bid_price) / midpoint * 10_000)
        touch = quote.ask_price if order.side == IntentSide.BUY else quote.bid_price
        adverse = (
            order.filled_price - touch
            if order.side == IntentSide.BUY
            else touch - order.filled_price
        )
        slippage.append(adverse / touch * 10_000)
        latency.append(
            (order.resolved_at_utc - order.submitted_at_utc).total_seconds()
        )
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
