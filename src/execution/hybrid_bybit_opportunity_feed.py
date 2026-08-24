"""Hybrid opportunity input: local history + verified Bronze + live public REST."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.data.raw_store import discover_manifests, read_raw_part, verify_raw_part
from src.data.storage import read_klines
from src.execution.bybit_demo_opportunity_feed import (
    BybitOpportunityFeedError,
    PybitBybitOpportunityFeed,
)
from src.execution.demo_opportunity_scanner import (
    BybitOpportunitySnapshot,
    PublicTrade,
)


@dataclass(frozen=True, slots=True)
class HybridOpportunityFeedConfig:
    minimum_bronze_dates: int = 3
    minimum_bronze_trades: int = 300
    maximum_bronze_trades: int = 5_000
    maximum_bronze_age_seconds: float = 360.0
    maximum_candles: int = 2_000

    def __post_init__(self) -> None:
        if (
            self.minimum_bronze_dates < 1
            or self.minimum_bronze_trades < 1
            or self.maximum_bronze_trades < self.minimum_bronze_trades
            or self.maximum_bronze_age_seconds <= 0
            or self.maximum_candles < 200
        ):
            raise ValueError("invalid hybrid opportunity feed configuration")


class HybridBybitOpportunityFeed:
    """Use the local lake when it is complete and current; otherwise fail closed."""

    def __init__(
        self,
        *,
        data_dir: Path,
        public_feed: PybitBybitOpportunityFeed | None = None,
        config: HybridOpportunityFeedConfig | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.public_feed = public_feed or PybitBybitOpportunityFeed()
        self.config = config or HybridOpportunityFeedConfig()

    def fetch(self, *, symbol: str) -> BybitOpportunitySnapshot:
        live = self.public_feed.fetch(symbol=symbol)
        candles = self._candles(live)
        trades = self._bronze_trades(symbol=symbol, observed=live.observed_at_utc)
        return BybitOpportunitySnapshot(
            symbol=symbol,
            observed_at_utc=live.observed_at_utc,
            candles=candles,
            trades=trades,
            derivatives=live.derivatives,
            price_tick=live.price_tick,
        )

    def _candles(self, live: BybitOpportunitySnapshot) -> pd.DataFrame:
        historical = read_klines(
            self.data_dir,
            live.symbol,
            "5m",
            end=pd.Timestamp(live.observed_at_utc),
        )
        if historical.empty:
            raise BybitOpportunityFeedError("hybrid feed has no local 5m history")
        local = historical.rename(columns={"timestamp": "timestamp"}).copy()
        local["max_source_timestamp"] = local["timestamp"]
        columns = [
            "timestamp",
            "max_source_timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
        combined = pd.concat([local[columns], live.candles[columns]], ignore_index=True)
        combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)
        return (
            combined.sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
            .tail(self.config.maximum_candles)
            .reset_index(drop=True)
        )

    def _bronze_trades(
        self, *, symbol: str, observed: datetime
    ) -> tuple[PublicTrade, ...]:
        manifests = discover_manifests(
            self.data_dir,
            exchange="bybit",
            market_type="linear",
            channel="trades",
            symbol=symbol,
        )
        eligible = [
            item
            for item in manifests
            if item.max_receive_ts_ns <= int(observed.timestamp() * 1_000_000_000) + 1_000_000_000
        ]
        if len({item.utc_date for item in eligible}) < self.config.minimum_bronze_dates:
            raise BybitOpportunityFeedError("hybrid feed has insufficient Bronze trade dates")
        selected = []
        selected_rows = 0
        for manifest in sorted(eligible, key=lambda item: item.max_receive_ts_ns, reverse=True):
            selected.append(manifest)
            selected_rows += manifest.row_count
            if selected_rows >= self.config.maximum_bronze_trades:
                break
        trades: dict[str, PublicTrade] = {}
        for manifest in reversed(selected):
            verify_raw_part(self.data_dir, manifest)
            for event in read_raw_part(self.data_dir, manifest):
                data = event.payload().get("data")
                if not isinstance(data, list):
                    continue
                for row in data:
                    if not isinstance(row, dict) or str(row.get("s", "")) != symbol:
                        continue
                    timestamp = datetime.fromtimestamp(int(row["T"]) / 1000, tz=UTC)
                    if timestamp > observed:
                        continue
                    trade = PublicTrade(
                        trade_id=str(row["i"]),
                        timestamp_utc=timestamp,
                        side=str(row["S"]).casefold(),
                        price=float(row["p"]),
                        size=float(row["v"]),
                    )
                    trades[trade.trade_id] = trade
        ordered = tuple(
            sorted(trades.values(), key=lambda item: (item.timestamp_utc, item.trade_id))[
                -self.config.maximum_bronze_trades :
            ]
        )
        if len(ordered) < self.config.minimum_bronze_trades:
            raise BybitOpportunityFeedError("hybrid feed has insufficient Bronze trades")
        age = (observed.astimezone(UTC) - ordered[-1].timestamp_utc).total_seconds()
        if age < 0 or age > self.config.maximum_bronze_age_seconds:
            raise BybitOpportunityFeedError("hybrid feed Bronze trades are stale")
        return ordered

