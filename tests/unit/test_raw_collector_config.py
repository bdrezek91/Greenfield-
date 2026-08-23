"""The initial v2 raw fleet is deliberately limited to BTC, ETH, and SOL."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.data.raw_collector_config import (
    INITIAL_V2_OKX_INST_IDS,
    INITIAL_V2_SYMBOLS,
    load_bybit_raw_collector_config,
    load_okx_raw_collector_config,
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


def test_default_okx_raw_collector_config_is_strict_and_complete() -> None:
    config = load_okx_raw_collector_config()

    assert config.inst_ids == INITIAL_V2_OKX_INST_IDS
    assert config.market_type == "swap"
    assert config.queue_capacity > config.max_batch_events
    assert config.minimum_runtime_free_gib == 5.0


def test_okx_unreviewed_universe_expansion_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "raw.yaml"
    path.write_text(
        """schema_version: 1
okx:
  market_type: swap
  inst_ids: [BTC-USDT-SWAP, ETH-USDT-SWAP, SOL-USDT-SWAP, XRP-USDT-SWAP]
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
        load_okx_raw_collector_config(path)


def test_okx_invalid_reconnect_range_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "raw.yaml"
    path.write_text(
        """schema_version: 1
okx:
  market_type: swap
  inst_ids: [BTC-USDT-SWAP, ETH-USDT-SWAP, SOL-USDT-SWAP]
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
        load_okx_raw_collector_config(path)


def test_okx_config_missing_section_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "raw.yaml"
    path.write_text("schema_version: 1\nbybit: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="okx section"):
        load_okx_raw_collector_config(path)


def test_default_config_file_serves_both_bybit_and_okx_without_conflict() -> None:
    """Both loaders read the same configs/raw_collectors.yaml - adding OKX
    must never change what the Bybit loader (and its soak-marker-pinned
    hash) sees for the bybit section."""
    bybit_config = load_bybit_raw_collector_config()
    okx_config = load_okx_raw_collector_config()

    assert bybit_config.symbols == INITIAL_V2_SYMBOLS
    assert okx_config.inst_ids == INITIAL_V2_OKX_INST_IDS


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
        assert service["environment"]["GREENFIELD_SOAK_ID"] == "${GREENFIELD_SOAK_ID:-}"
        assert service["environment"]["GREENFIELD_DEPLOY_COMMIT"] == (
            "${GREENFIELD_DEPLOY_COMMIT:-}"
        )
        assert service["healthcheck"]["test"] == [
            "CMD",
            "python",
            "scripts/check_raw_collector_health.py",
        ]

    assert services["microstructure-collector"]["profiles"] == ["legacy"]

    # raw-bybit-* must be completely untouched by any later cycle - the
    # active soak's start-gate pins a hash of this whole file.
    assert "profiles" not in services["raw-bybit-btc"]
    assert "profiles" not in services["raw-bybit-eth"]
    assert "profiles" not in services["raw-bybit-sol"]


def test_compose_supervises_three_isolated_disabled_okx_collectors() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    expected = {
        "raw-okx-btc": "BTC-USDT-SWAP",
        "raw-okx-eth": "ETH-USDT-SWAP",
        "raw-okx-sol": "SOL-USDT-SWAP",
    }
    for service_name, inst_id in expected.items():
        service = services[service_name]
        assert service["restart"] == "unless-stopped"
        assert inst_id in service["command"]
        assert service["profiles"] == ["okx"]  # disabled by default
        assert service["environment"]["EXCHANGE"] == "okx"
        assert service["environment"]["MARKET_TYPE"] == "swap"
        assert service["environment"]["GREENFIELD_SOAK_ID"] == "${GREENFIELD_SOAK_ID:-}"
        assert service["environment"]["GREENFIELD_DEPLOY_COMMIT"] == (
            "${GREENFIELD_DEPLOY_COMMIT:-}"
        )
        assert service["healthcheck"]["test"] == [
            "CMD",
            "python",
            "scripts/check_raw_collector_health.py",
        ]
        # same Bronze data lake as raw-bybit-* by design, not the same
        # mutable control-state concern shadow-service had
        assert "${DATA_DIR:-./data}:/app/data" in service["volumes"]
