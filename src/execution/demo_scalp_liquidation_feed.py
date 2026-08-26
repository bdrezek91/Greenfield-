"""Bronze liquidations reader for the "druga proba scalpingu" candidate.

Structurally mirrors HybridBybitOpportunityFeed._bronze_trades (same
discover_recent_manifests/read_raw_part/verify_raw_part contract), reading
the same VPS-collected `allLiquidation.<symbol>` topic (see
src/data/bybit_raw_collector.py). Deliberately its own small module rather
than a field added to BybitOpportunitySnapshot, so v1's scanner and feed are
completely untouched.

Unlike trades, a healthy market can legitimately produce zero liquidations
for long stretches - so this does not fail closed on "too few events" the
way `_bronze_trades` does, nor on "the newest liquidation manifest is a few
minutes old": bybit_raw_collector.py's writer only flushes a batch when it
is non-empty (see `_writer_loop`), so a quiet liquidation channel simply
produces no new manifest at all, for as long as the market stays quiet -
that is normal, not staleness. `maximum_age_seconds` is instead a coarse
"is this collector fundamentally alive" check (default generously wide) -
it fires only when no liquidation manifest has appeared in a very long time,
which is what a dead/misconfigured collector looks like, not a quiet BTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.data.raw_store import discover_recent_manifests, read_raw_part, verify_raw_part
from src.execution.demo_scalp_liquidation_signal import LiquidatedSide, LiquidationEvent


class BronzeLiquidationFeedError(RuntimeError):
    """Public liquidation data is stale, malformed, or unavailable."""


@dataclass(frozen=True, slots=True)
class BronzeLiquidationFeedConfig:
    # Must cover at least LiquidationCascadeConfig.reference_window_seconds
    # for the caller's cascade detection to have a valid baseline - see
    # detect_liquidation_cascade.
    fetch_window_seconds: float = 1_800.0
    maximum_events: int = 5_000
    # A coarse dead-collector detector, not a "recent liquidation" check -
    # see the module docstring. Wide by design: BTC can plausibly go many
    # hours without a large liquidation in a calm market.
    maximum_age_seconds: float = 21_600.0

    def __post_init__(self) -> None:
        if not self.fetch_window_seconds > 0:
            raise ValueError("liquidation feed fetch window must be positive")
        if self.maximum_events < 1:
            raise ValueError("liquidation feed maximum events must be positive")
        if not self.maximum_age_seconds > 0:
            raise ValueError("liquidation feed maximum age must be positive")


def fetch_recent_liquidations(
    data_dir: Path,
    *,
    symbol: str,
    observed_at_utc: datetime,
    config: BronzeLiquidationFeedConfig | None = None,
) -> tuple[LiquidationEvent, ...]:
    config = config or BronzeLiquidationFeedConfig()
    observed = _utc(observed_at_utc, "liquidation feed observation timestamp")
    maximum_receive_ts_ns = int(observed.timestamp() * 1_000_000_000) + 1_000_000_000
    selection = discover_recent_manifests(
        data_dir,
        exchange="bybit",
        market_type="linear",
        channel="liquidations",
        symbol=symbol,
        maximum_receive_ts_ns=maximum_receive_ts_ns,
        maximum_rows=config.maximum_events,
    )
    if not selection.manifests:
        raise BronzeLiquidationFeedError("no Bronze liquidation manifests found for symbol")
    newest_receive_ts = max(item.max_receive_ts_ns for item in selection.manifests)
    age = observed.timestamp() - newest_receive_ts / 1_000_000_000
    if age < 0:
        raise BronzeLiquidationFeedError("Bronze liquidation manifest is from the future")
    if age > config.maximum_age_seconds:
        raise BronzeLiquidationFeedError(
            "no Bronze liquidation manifest in a very long time - collector may be dead"
        )

    lookback_start = observed.timestamp() - config.fetch_window_seconds
    events: dict[tuple[float, str, float, float], LiquidationEvent] = {}
    for manifest in reversed(selection.manifests):
        verify_raw_part(data_dir, manifest)
        for raw_event in read_raw_part(data_dir, manifest):
            data = raw_event.payload().get("data")
            if not isinstance(data, list):
                continue
            for row in data:
                if not isinstance(row, dict) or str(row.get("s", "")) != symbol:
                    continue
                timestamp_ms = int(row["T"])
                timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
                if timestamp > observed or timestamp.timestamp() < lookback_start:
                    continue
                forced_side = str(row["S"])
                # Bybit's allLiquidation "S" is the side of the FORCED order
                # used to close the position: "Sell" force-closes a long,
                # "Buy" force-closes a short.
                side = LiquidatedSide.LONGS if forced_side == "Sell" else LiquidatedSide.SHORTS
                price = float(row["p"])
                size = float(row["v"])
                key = (timestamp_ms / 1000, forced_side, price, size)
                events[key] = LiquidationEvent(
                    timestamp_utc=timestamp, side=side, price=price, size=size
                )
    return tuple(sorted(events.values(), key=lambda item: item.timestamp_utc))[
        -config.maximum_events :
    ]


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)
