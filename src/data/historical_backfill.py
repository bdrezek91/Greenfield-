"""Deterministic, resumable plan for bounded multi-venue historical data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "historical_backfill.yaml"
)
_VENUES = {"bybit", "binance", "okx"}
_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d"}


@dataclass(frozen=True, slots=True)
class HistoricalSymbol:
    symbol: str
    okx_inst_id: str
    earliest_date: date


@dataclass(frozen=True, slots=True)
class HistoricalBackfillConfig:
    version: int
    symbols: tuple[HistoricalSymbol, ...]
    timeframe_days: tuple[tuple[str, int], ...]
    venues: tuple[str, ...]
    funding_days: int
    open_interest_days: int
    open_interest_interval: str


@dataclass(frozen=True, slots=True)
class HistoricalBackfillJob:
    dataset: str
    venue: str
    symbol: str
    venue_symbol: str
    timeframe: str | None
    start: date
    end: date

    @property
    def identity(self) -> str:
        interval = self.timeframe or "none"
        return f"{self.dataset}:{self.venue}:{self.venue_symbol}:{interval}:{self.start}:{self.end}"


def load_historical_backfill_config(
    path: Path = DEFAULT_CONFIG_PATH,
) -> HistoricalBackfillConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("version", 0)) != 1:
        raise ValueError("historical backfill config version must be 1")
    raw_symbols = raw.get("symbols")
    raw_timeframes = raw.get("timeframes")
    derivatives = raw.get("bybit_derivatives")
    venues = tuple(str(value) for value in raw.get("venues", ()))
    if not isinstance(raw_symbols, dict) or not isinstance(raw_timeframes, dict):
        raise ValueError("historical backfill symbols/timeframes are required")
    if not isinstance(derivatives, dict):
        raise ValueError("historical backfill derivatives config is required")
    if not venues or len(set(venues)) != len(venues) or set(venues) - _VENUES:
        raise ValueError("historical backfill venues are invalid")
    symbols = tuple(
        HistoricalSymbol(
            symbol=str(symbol),
            okx_inst_id=str(_mapping(value, "symbol")["okx_inst_id"]),
            earliest_date=date.fromisoformat(str(_mapping(value, "symbol")["earliest_date"])),
        )
        for symbol, value in raw_symbols.items()
    )
    if {item.symbol for item in symbols} != {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
        raise ValueError("historical backfill universe must be exactly BTC/ETH/SOL")
    timeframe_days = tuple((str(name), int(days)) for name, days in raw_timeframes.items())
    if (
        {name for name, _ in timeframe_days} != _TIMEFRAMES
        or any(days <= 0 for _, days in timeframe_days)
    ):
        raise ValueError("historical backfill timeframes are invalid")
    funding_days = int(derivatives.get("funding_days", 0))
    oi_days = int(derivatives.get("open_interest_days", 0))
    oi_interval = str(derivatives.get("open_interest_interval", ""))
    valid_oi_intervals = {"5min", "15min", "30min", "1h", "4h", "1d"}
    if funding_days <= 0 or oi_days <= 0 or oi_interval not in valid_oi_intervals:
        raise ValueError("historical backfill derivatives window is invalid")
    return HistoricalBackfillConfig(
        version=1,
        symbols=symbols,
        timeframe_days=timeframe_days,
        venues=venues,
        funding_days=funding_days,
        open_interest_days=oi_days,
        open_interest_interval=oi_interval,
    )


def build_historical_backfill_jobs(
    config: HistoricalBackfillConfig,
    *,
    as_of: date,
) -> tuple[HistoricalBackfillJob, ...]:
    jobs: list[HistoricalBackfillJob] = []
    for item in config.symbols:
        for venue in config.venues:
            venue_symbol = item.okx_inst_id if venue == "okx" else item.symbol
            for timeframe, days in config.timeframe_days:
                jobs.append(
                    HistoricalBackfillJob(
                        dataset="klines",
                        venue=venue,
                        symbol=item.symbol,
                        venue_symbol=venue_symbol,
                        timeframe=timeframe,
                        start=max(item.earliest_date, as_of - timedelta(days=days)),
                        end=as_of,
                    )
                )
        jobs.extend(
            (
                HistoricalBackfillJob(
                    dataset="funding",
                    venue="bybit",
                    symbol=item.symbol,
                    venue_symbol=item.symbol,
                    timeframe=None,
                    start=max(
                        item.earliest_date,
                        as_of - timedelta(days=config.funding_days),
                    ),
                    end=as_of,
                ),
                HistoricalBackfillJob(
                    dataset="open_interest",
                    venue="bybit",
                    symbol=item.symbol,
                    venue_symbol=item.symbol,
                    timeframe=config.open_interest_interval,
                    start=max(
                        item.earliest_date,
                        as_of - timedelta(days=config.open_interest_days),
                    ),
                    end=as_of,
                ),
            )
        )
    return tuple(jobs)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"historical backfill {name} entry must be a mapping")
    return value
