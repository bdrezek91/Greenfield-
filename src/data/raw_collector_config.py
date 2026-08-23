"""Strict configuration for the Greenfield v2 raw collector fleet."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RAW_COLLECTOR_CONFIG = (
    Path(__file__).resolve().parents[2] / "configs" / "raw_collectors.yaml"
)
INITIAL_V2_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
INITIAL_V2_OKX_INST_IDS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP")


@dataclass(frozen=True, slots=True)
class BybitRawCollectorConfig:
    market_type: str
    symbols: tuple[str, ...]
    orderbook_depth: int
    flush_interval_secs: float
    max_batch_events: int
    queue_capacity: int
    ping_interval_secs: float
    health_interval_secs: float
    minimum_runtime_free_gib: float
    reconnect_min_secs: float
    reconnect_max_secs: float


def load_bybit_raw_collector_config(
    path: Path = DEFAULT_RAW_COLLECTOR_CONFIG,
) -> BybitRawCollectorConfig:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("raw collector config must use schema_version 1")
    bybit = value.get("bybit")
    if not isinstance(bybit, dict):
        raise ValueError("raw collector config is missing the bybit section")
    config = _build_config(bybit)
    if config.symbols != INITIAL_V2_SYMBOLS:
        raise ValueError(
            f"initial v2 raw universe must be exactly {INITIAL_V2_SYMBOLS}; "
            "expansion requires a reviewed master-plan change"
        )
    return config


def _build_config(value: dict[str, Any]) -> BybitRawCollectorConfig:
    try:
        config = BybitRawCollectorConfig(
            market_type=str(value["market_type"]),
            symbols=tuple(str(symbol) for symbol in value["symbols"]),
            orderbook_depth=int(value["orderbook_depth"]),
            flush_interval_secs=float(value["flush_interval_secs"]),
            max_batch_events=int(value["max_batch_events"]),
            queue_capacity=int(value["queue_capacity"]),
            ping_interval_secs=float(value["ping_interval_secs"]),
            health_interval_secs=float(value["health_interval_secs"]),
            minimum_runtime_free_gib=float(value["minimum_runtime_free_gib"]),
            reconnect_min_secs=float(value["reconnect_min_secs"]),
            reconnect_max_secs=float(value["reconnect_max_secs"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid raw collector config: {exc}") from exc

    positive_values = (
        config.flush_interval_secs,
        config.max_batch_events,
        config.queue_capacity,
        config.ping_interval_secs,
        config.health_interval_secs,
        config.minimum_runtime_free_gib,
        config.reconnect_min_secs,
        config.reconnect_max_secs,
    )
    if any(value <= 0 for value in positive_values):
        raise ValueError("raw collector timing and capacity values must be positive")
    if config.reconnect_min_secs > config.reconnect_max_secs:
        raise ValueError("reconnect_min_secs cannot exceed reconnect_max_secs")
    return config


@dataclass(frozen=True, slots=True)
class OkxRawCollectorConfig:
    market_type: str
    inst_ids: tuple[str, ...]
    flush_interval_secs: float
    max_batch_events: int
    queue_capacity: int
    ping_interval_secs: float
    health_interval_secs: float
    minimum_runtime_free_gib: float
    reconnect_min_secs: float
    reconnect_max_secs: float


def load_okx_raw_collector_config(
    path: Path = DEFAULT_RAW_COLLECTOR_CONFIG,
) -> OkxRawCollectorConfig:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("raw collector config must use schema_version 1")
    okx = value.get("okx")
    if not isinstance(okx, dict):
        raise ValueError("raw collector config is missing the okx section")
    config = _build_okx_config(okx)
    if config.inst_ids != INITIAL_V2_OKX_INST_IDS:
        raise ValueError(
            f"initial v2 OKX raw universe must be exactly {INITIAL_V2_OKX_INST_IDS}; "
            "expansion requires a reviewed master-plan change"
        )
    return config


def _build_okx_config(value: dict[str, Any]) -> OkxRawCollectorConfig:
    try:
        config = OkxRawCollectorConfig(
            market_type=str(value["market_type"]),
            inst_ids=tuple(str(inst_id) for inst_id in value["inst_ids"]),
            flush_interval_secs=float(value["flush_interval_secs"]),
            max_batch_events=int(value["max_batch_events"]),
            queue_capacity=int(value["queue_capacity"]),
            ping_interval_secs=float(value["ping_interval_secs"]),
            health_interval_secs=float(value["health_interval_secs"]),
            minimum_runtime_free_gib=float(value["minimum_runtime_free_gib"]),
            reconnect_min_secs=float(value["reconnect_min_secs"]),
            reconnect_max_secs=float(value["reconnect_max_secs"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid raw collector config: {exc}") from exc

    positive_values = (
        config.flush_interval_secs,
        config.max_batch_events,
        config.queue_capacity,
        config.ping_interval_secs,
        config.health_interval_secs,
        config.minimum_runtime_free_gib,
        config.reconnect_min_secs,
        config.reconnect_max_secs,
    )
    if any(value <= 0 for value in positive_values):
        raise ValueError("raw collector timing and capacity values must be positive")
    if config.reconnect_min_secs > config.reconnect_max_secs:
        raise ValueError("reconnect_min_secs cannot exceed reconnect_max_secs")
    return config
