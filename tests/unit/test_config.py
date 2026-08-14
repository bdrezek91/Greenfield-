"""Symbol/timeframe universe must load from configs/symbols.yaml as documented."""

import pytest

from src.data.config import load_symbol_universe


def test_default_universe_loads_expected_symbols() -> None:
    universe = load_symbol_universe()

    assert "BTCUSD" in universe.symbols
    assert len(universe.symbols) == 10
    assert set(universe.canonical_timeframes) == {"1m", "5m", "15m", "1h", "4h", "1d"}


def test_validate_symbol_accepts_known_symbol() -> None:
    load_symbol_universe().validate_symbol("BTCUSD")  # must not raise


def test_validate_symbol_rejects_unknown_symbol() -> None:
    with pytest.raises(ValueError, match="unknown symbol"):
        load_symbol_universe().validate_symbol("../../etc/passwd")


def test_validate_timeframe_accepts_known_timeframe() -> None:
    load_symbol_universe().validate_timeframe("1h")  # must not raise


def test_validate_timeframe_rejects_unknown_timeframe() -> None:
    with pytest.raises(ValueError, match="unknown timeframe"):
        load_symbol_universe().validate_timeframe("2h")
