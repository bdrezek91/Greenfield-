"""Strict point-in-time lookup over a sorted (timestamp, value) series -
shared by any strategy that reads an auxiliary, lower-frequency data
source (funding rate, open interest, ...) directly from disk and needs to
look up "the most recent reading at or before this bar's timestamp,
never a future one" (src.strategies.funding_contrarian,
src.strategies.liquidity_sweep_confluence).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class AsOfSeries:
    def __init__(self, df: pd.DataFrame, value_col: str) -> None:
        ordered = df.sort_values("timestamp")
        self._timestamps_ns = ordered["timestamp"].to_numpy(dtype="datetime64[ns]").astype("int64")
        self._values = ordered[value_col].to_numpy(dtype=float)

    def __len__(self) -> int:
        return len(self._values)

    def window_ending_at(self, ts_ns: int, n: int) -> np.ndarray:
        idx = int(np.searchsorted(self._timestamps_ns, ts_ns, side="right"))
        return self._values[max(0, idx - n) : idx]
