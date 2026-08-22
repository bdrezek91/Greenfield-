"""The initial v2 raw fleet is deliberately limited to BTC, ETH, and SOL."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.data.raw_collector_config import (
    INITIAL_V2_SYMBOLS,
    load_bybit_raw_collector_config,
)


def test_default_raw_collector_config_is_strict_and_complete() -> None:
    config = load_bybit_raw_collector_config()

    assert config.symbols == INITIAL_V2_SYMBOLS
    assert config.market_type == "linear"
    assert config.orderbook_depth == 50
    assert config.queue_capacity > config.max_batch_events
    assert config.minimum_runtime_free_gib == 5.0


def test_unreviewed_universe_expansion_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "raw.yaml"
    path.write_text(
        """schema_version: 1
bybit:
  market_type: linear
  symbols: [BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT]
  orderbook_depth: 50
  flush_interval_secs: 5
  max_batch_events: 100
  queue_capacity: 1000
  ping_interval_secs: 20
  health_interval_secs: 5
  minimum_runtime_free_gib: 5
  reconnect_min_secs: 1
  reconnect_max_secs: 30
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exactly"):
        load_bybit_raw_collector_config(path)


def test_invalid_reconnect_range_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "raw.yaml"
    path.write_text(
        """schema_version: 1
bybit:
  market_type: linear
  symbols: [BTCUSDT, ETHUSDT, SOLUSDT]
  orderbook_depth: 50
  flush_interval_secs: 5
  max_batch_events: 100
  queue_capacity: 1000
  ping_interval_secs: 20
  health_interval_secs: 5
  minimum_runtime_free_gib: 5
  reconnect_min_secs: 30
  reconnect_max_secs: 1
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cannot exceed"):
        load_bybit_raw_collector_config(path)


def test_compose_supervises_three_isolated_raw_collectors() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    expected = {
        "raw-bybit-btc": "BTCUSDT",
        "raw-bybit-eth": "ETHUSDT",
        "raw-bybit-sol": "SOLUSDT",
    }
    for service_name, symbol in expected.items():
        service = services[service_name]
        assert service["restart"] == "unless-stopped"
        assert symbol in service["command"]
        assert service["healthcheck"]["test"] == [
            "CMD",
            "python",
            "scripts/check_raw_collector_health.py",
        ]

    assert services["microstructure-collector"]["profiles"] == ["legacy"]
