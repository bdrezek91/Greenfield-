"""End-to-end proof that the backtest engine actually works against a
non-Bybit exchange - the payoff of Cycle 25's multi-exchange klines/venue
work (src/backtesting/instruments.py, src/backtesting/engine.py,
src/data/binance_klines_storage.py) and Cycle 32's OKX extension of the
same pattern (src/data/okx_klines_storage.py). Deliberately a separate
file from tests/integration/test_backtest_engine.py so the existing,
already-passing Bybit-default suite is never touched by this change.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.backtesting.engine import BacktestRunSpec, run_backtest
from src.backtesting.instruments import (
    build_crypto_perpetual,
    instrument_id_for,
    load_instrument_specs,
    validate_order_grid,
    venue_for_exchange,
)
from src.data.binance_klines_storage import write_binance_klines
from src.data.okx_klines_storage import write_okx_klines
from src.data.schema import COLUMNS


def _write_synthetic_klines(
    writer: object, data_dir: Path, symbol: str, n: int = 50
) -> pd.DatetimeIndex:
    ts = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0, 0.5, size=n))
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 10.0,
            "turnover": 1000.0,
            "symbol": symbol,
            "timeframe": "1h",
        }
    )[list(COLUMNS)]
    writer(df, data_dir)  # type: ignore[operator]
    return ts


def _write_synthetic_binance_klines(data_dir: Path, symbol: str, n: int = 50) -> pd.DatetimeIndex:
    return _write_synthetic_klines(write_binance_klines, data_dir, symbol, n)


def _write_synthetic_okx_klines(data_dir: Path, symbol: str, n: int = 50) -> pd.DatetimeIndex:
    return _write_synthetic_klines(write_okx_klines, data_dir, symbol, n)


def test_venue_for_exchange_distinguishes_bybit_and_binance() -> None:
    assert str(venue_for_exchange("bybit")) == "BYBIT"
    assert str(venue_for_exchange("binance")) == "BINANCE"
    with pytest.raises(ValueError, match="exchange"):
        venue_for_exchange("coinbase")  # no configs/instruments_coinbase.yaml yet


def test_instrument_id_for_defaults_to_bybit_unchanged() -> None:
    assert str(instrument_id_for("BTCUSDT")) == "BTCUSDT-PERP.BYBIT"
    assert str(instrument_id_for("BTCUSDT", "binance")) == "BTCUSDT-PERP.BINANCE"


def test_binance_instrument_specs_load_from_the_binance_config() -> None:
    specs = load_instrument_specs(exchange="binance")
    assert "BTCUSDT" in specs.base_currencies
    instrument = build_crypto_perpetual("BTCUSDT", specs, exchange="binance")
    assert str(instrument.id) == "BTCUSDT-PERP.BINANCE"
    assert str(instrument.price_increment) == "0.1"
    sol = build_crypto_perpetual("SOLUSDT", specs, exchange="binance")
    assert str(sol.size_increment) == "0.01"
    assert specs.source_url.startswith("https://fapi.binance.com/")
    validate_order_grid(
        "BTCUSDT", specs, price=Decimal("100000.1"), quantity=Decimal("0.001")
    )
    with pytest.raises(ValueError, match="price increment"):
        validate_order_grid(
            "BTCUSDT", specs, price=Decimal("100000.01"), quantity=Decimal("0.001")
        )
    with pytest.raises(ValueError, match="size increment"):
        validate_order_grid(
            "SOLUSDT", specs, price=Decimal("100.01"), quantity=Decimal("0.001")
        )


def test_engine_runs_end_to_end_against_real_binance_klines_storage(tmp_path: Path) -> None:
    """The actual payoff: a full backtest run against data written through
    the Binance-specific storage path, with the Binance venue/instrument
    specs/fee schedule - not a facade, an actually-executing engine."""
    ts = _write_synthetic_binance_klines(tmp_path, "BTCUSDT")
    spec = BacktestRunSpec(
        symbols=["BTCUSDT"],
        timeframe="1h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        exchange="binance",
    )

    engine = run_backtest(spec)

    assert engine.run_finished is not None
    venues = list(engine.list_venues())
    assert [str(v) for v in venues] == ["BINANCE"]
    account_report = engine.trader.generate_account_report(venues[0])
    assert not account_report.empty
    assert float(account_report["total"].iloc[0]) == 100_000.0


def test_engine_exchange_default_still_reads_bybit_storage_not_binance(tmp_path: Path) -> None:
    """Writing ONLY to the Binance storage path must not make a default
    (Bybit) BacktestRunSpec find any data - proves the two storage paths
    stay genuinely isolated, not silently merged."""
    ts = _write_synthetic_binance_klines(tmp_path, "BTCUSDT")
    spec = BacktestRunSpec(
        symbols=["BTCUSDT"],
        timeframe="1h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        # exchange defaults to "bybit" - no Bybit data was written above
    )

    engine = run_backtest(spec)

    assert engine.run_finished is not None
    assert engine.trader.generate_positions_report().empty


def test_okx_instrument_specs_load_from_the_okx_config() -> None:
    specs = load_instrument_specs(exchange="okx")
    assert "BTC-USDT-SWAP" in specs.base_currencies
    instrument = build_crypto_perpetual("BTC-USDT-SWAP", specs, exchange="okx")
    assert str(instrument.id) == "BTC-USDT-SWAP-PERP.OKX"
    assert str(instrument.price_increment) == "0.1"
    assert str(instrument.size_increment) == "0.0001"
    assert specs.symbol_specs["BTC-USDT-SWAP"].contract_multiplier == Decimal("0.01")


def test_engine_runs_end_to_end_against_real_okx_klines_storage(tmp_path: Path) -> None:
    """Same payoff as the Binance end-to-end test above, but for Cycle 32's
    OKX addition - proves data/instrument/venue/cost plumbing actually
    works for OKX, not just that the config files parse."""
    ts = _write_synthetic_okx_klines(tmp_path, "BTC-USDT-SWAP")
    spec = BacktestRunSpec(
        symbols=["BTC-USDT-SWAP"],
        timeframe="1h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        starting_balance=Decimal(100_000),
        exchange="okx",
    )

    engine = run_backtest(spec)

    assert engine.run_finished is not None
    venues = list(engine.list_venues())
    assert [str(v) for v in venues] == ["OKX"]
    account_report = engine.trader.generate_account_report(venues[0])
    assert not account_report.empty
    assert float(account_report["total"].iloc[0]) == 100_000.0


def test_engine_exchange_default_still_reads_bybit_storage_not_okx(tmp_path: Path) -> None:
    """Writing ONLY to the OKX storage path must not make a default
    (Bybit) BacktestRunSpec find any data - proves the two storage paths
    stay genuinely isolated, not silently merged."""
    ts = _write_synthetic_okx_klines(tmp_path, "BTC-USDT-SWAP")
    spec = BacktestRunSpec(
        symbols=["BTC-USDT-SWAP"],
        timeframe="1h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        # exchange defaults to "bybit" - no Bybit data was written above,
        # and "BTC-USDT-SWAP" isn't a symbol Bybit's config even knows.
    )

    with pytest.raises(ValueError, match="no base currency configured"):
        run_backtest(spec)


def test_engine_rejects_an_unknown_exchange(tmp_path: Path) -> None:
    ts = pd.date_range("2024-01-01", periods=5, freq="1h", tz="UTC")
    spec = BacktestRunSpec(
        symbols=["BTCUSDT"],
        timeframe="1h",
        start=ts[0],
        end=ts[-1],
        data_dir=tmp_path,
        exchange="coinbase",  # no configs/instruments_coinbase.yaml yet
    )
    with pytest.raises(ValueError, match="exchange"):
        run_backtest(spec)
