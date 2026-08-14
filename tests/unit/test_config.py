"""Symbol/timeframe universe must load from configs/symbols.yaml as documented."""

from src.data.config import load_symbol_universe


def test_default_universe_loads_expected_symbols() -> None:
    universe = load_symbol_universe()

    assert universe.category == "linear"
    assert "BTCUSDT" in universe.symbols
    assert len(universe.symbols) == 11
    assert set(universe.canonical_timeframes) == {"1m", "5m", "15m", "1h", "4h", "1d"}
