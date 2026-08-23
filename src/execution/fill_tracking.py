"""Compare expected vs. actual fills, per project brief section 32: after
research, paper trading compares expected fills against actual simulated/
live-market fills, checking latency, slippage, rejected signals, and data
issues.

Offline PAPER fills can carry an explicit spread, slippage, fee, and funding
decomposition from the calibrated simulator. Exchange PAPER fills still need
an as-of order-book join before their realized spread component is known.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.execution.adapter import Fill
from src.execution.intent import IntentSide, OrderIntent


@dataclass(frozen=True)
class FillComparison:
    intent: OrderIntent
    fill: Fill
    rejected: bool
    latency_seconds: float | None
    slippage: float | None
    """Adverse-positive: filled_price - reference_price for a BUY,
    reference_price - filled_price for a SELL. Positive always means the
    fill was worse than expected, regardless of side."""
    slippage_pct: float | None
    data_issue: str | None
    partial_fill: bool
    fill_ratio: float
    total_cost_quote: float
    total_cost_bps: float | None


def compare_fill(intent: OrderIntent, fill: Fill) -> FillComparison:
    if fill.rejected:
        return FillComparison(
            intent=intent,
            fill=fill,
            rejected=True,
            latency_seconds=None,
            slippage=None,
            slippage_pct=None,
            data_issue=None,
            partial_fill=False,
            fill_ratio=0.0,
            total_cost_quote=0.0,
            total_cost_bps=None,
        )

    latency = (fill.filled_at - intent.created_at).total_seconds()

    data_issue = None
    if latency < 0:
        data_issue = "filled_at is before created_at"
    elif fill.filled_quantity <= 0:
        data_issue = "zero or negative filled quantity"
    partial_fill = (
        fill.filled_quantity > 0
        and abs(fill.filled_quantity - intent.quantity) > 1e-9
    )
    if data_issue is None and partial_fill:
        data_issue = "partial fill (filled_quantity != requested quantity)"

    raw_diff = fill.filled_price - intent.reference_price
    slippage = raw_diff if intent.side == IntentSide.BUY else -raw_diff
    slippage_pct = slippage / intent.reference_price if intent.reference_price > 0 else None
    fill_ratio = fill.filled_quantity / intent.quantity if intent.quantity > 0 else 0.0
    filled_reference_notional = intent.reference_price * fill.filled_quantity
    total_cost_bps = (
        fill.total_cost_quote / filled_reference_notional * 10_000
        if filled_reference_notional > 0
        else None
    )

    return FillComparison(
        intent=intent,
        fill=fill,
        rejected=False,
        latency_seconds=latency,
        slippage=slippage,
        slippage_pct=slippage_pct,
        data_issue=data_issue,
        partial_fill=partial_fill,
        fill_ratio=fill_ratio,
        total_cost_quote=fill.total_cost_quote,
        total_cost_bps=total_cost_bps,
    )


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 == 1 else (s[mid - 1] + s[mid]) / 2


@dataclass
class FillTrackerSummary:
    n_intents: int
    n_rejected: int
    rejection_rate: float
    mean_latency_seconds: float | None
    median_latency_seconds: float | None
    mean_slippage: float | None
    median_slippage: float | None
    mean_slippage_pct: float | None
    data_issue_count: int
    data_issues: list[str] = field(default_factory=list)
    n_partial_fills: int = 0
    mean_fill_ratio: float | None = None
    mean_total_cost_bps: float | None = None


class FillTracker:
    """Accumulates FillComparisons across a paper-trading session and
    summarizes them into the section-32 checklist.
    """

    def __init__(self) -> None:
        self._comparisons: list[FillComparison] = []

    def record(self, intent: OrderIntent, fill: Fill) -> FillComparison:
        comparison = compare_fill(intent, fill)
        self._comparisons.append(comparison)
        return comparison

    @property
    def comparisons(self) -> list[FillComparison]:
        return list(self._comparisons)

    def summary(self) -> FillTrackerSummary:
        n = len(self._comparisons)
        rejected = [c for c in self._comparisons if c.rejected]
        filled = [c for c in self._comparisons if not c.rejected]

        latencies = [c.latency_seconds for c in filled if c.latency_seconds is not None]
        slippages = [c.slippage for c in filled if c.slippage is not None]
        slippage_pcts = [c.slippage_pct for c in filled if c.slippage_pct is not None]
        data_issues = [c.data_issue for c in filled if c.data_issue is not None]
        fill_ratios = [c.fill_ratio for c in filled]
        total_cost_bps = [c.total_cost_bps for c in filled if c.total_cost_bps is not None]

        return FillTrackerSummary(
            n_intents=n,
            n_rejected=len(rejected),
            rejection_rate=(len(rejected) / n) if n > 0 else float("nan"),
            mean_latency_seconds=_mean(latencies),
            median_latency_seconds=_median(latencies),
            mean_slippage=_mean(slippages),
            median_slippage=_median(slippages),
            mean_slippage_pct=_mean(slippage_pcts),
            data_issue_count=len(data_issues),
            data_issues=data_issues,
            n_partial_fills=sum(comparison.partial_fill for comparison in filled),
            mean_fill_ratio=_mean(fill_ratios),
            mean_total_cost_bps=_mean(total_cost_bps),
        )
