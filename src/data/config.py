"""Symbol/timeframe universe, loaded from configs/symbols.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "symbols.yaml"

# Bybit v5 kline interval -> milliseconds. Used to detect gaps/duplicates and
# to page through history.
TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


@dataclass(frozen=True)
class SymbolUniverse:
    category: str
    symbols: tuple[str, ...]
    # interval code (as sent to Bybit) -> canonical timeframe label
    timeframes: dict[str, str]

    @property
    def canonical_timeframes(self) -> tuple[str, ...]:
        return tuple(self.timeframes.values())

    def validate_symbol(self, symbol: str) -> None:
        """Raise ValueError for anything outside the configured universe.

        Symbols/timeframes reach filesystem paths (src/data/storage.py,
        src/analytics/experiment.py's fingerprint_dataset) via CLI options,
        so this is a system-boundary check against path-traversal input
        (e.g. `--symbol ../../etc`), not just a typo guard.
        """
        if symbol not in self.symbols:
            raise ValueError(f"unknown symbol {symbol!r}, expected one of {self.symbols}")

    def validate_timeframe(self, timeframe: str) -> None:
        if timeframe not in self.canonical_timeframes:
            raise ValueError(
                f"unknown timeframe {timeframe!r}, expected one of {self.canonical_timeframes}"
            )


def load_symbol_universe(path: Path = DEFAULT_CONFIG_PATH) -> SymbolUniverse:
    raw = yaml.safe_load(path.read_text())
    return SymbolUniverse(
        category=raw["category"],
        symbols=tuple(raw["symbols"]),
        timeframes={str(k): v for k, v in raw["timeframes"].items()},
    )
