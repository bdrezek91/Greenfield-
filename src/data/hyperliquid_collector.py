"""Live poller for Hyperliquid research market data - funding/OI/mark/
oracle/mid price, cross-venue predicted funding, and top-of-book (BBO).
Read-only, bounded to a fixed coin universe, no order placement, no
full-depth book (only the top level of `l2Book` is kept) - the
Hyperliquid counterpart to src/data/okx_derivatives_collector.py.

`metaAndAssetCtxs` and `predictedFundings` carry no timestamp of their
own in Hyperliquid's response (unlike `l2Book`, which has `"time"`, and
`fundingHistory`, which has per-row `"time"`) - they are "current state"
snapshots, not historical series, so this collector stamps them with its
own poll time (injectable `now`, same testability shape as `clock`/
`sleep` elsewhere in this project) rather than fabricating a source
timestamp that doesn't exist.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.hyperliquid_client import HyperliquidInfoClient
from src.data.hyperliquid_storage import (
    write_hyperliquid_asset_ctx,
    write_hyperliquid_bbo,
    write_hyperliquid_predicted_funding,
)
from src.data.rest_poller import run_polling_loop
from src.data.schema_hyperliquid import (
    HYPERLIQUID_ASSET_CONTEXT_COLUMNS,
    HYPERLIQUID_BBO_COLUMNS,
    HYPERLIQUID_PREDICTED_FUNDING_COLUMNS,
)


def _parse_asset_ctx_rows(
    universe: list[dict[str, Any]],
    asset_ctxs: list[dict[str, Any]],
    coins: tuple[str, ...],
    observed_at: pd.Timestamp,
) -> pd.DataFrame:
    rows = []
    for meta, ctx in zip(universe, asset_ctxs, strict=True):
        coin = meta["name"]
        if coin not in coins:
            continue
        rows.append(
            {
                "timestamp": observed_at,
                "coin": coin,
                "funding": float(ctx["funding"]),
                "open_interest": float(ctx["openInterest"]),
                "mark_px": float(ctx["markPx"]),
                "oracle_px": float(ctx["oraclePx"]),
                "mid_px": float(ctx["midPx"]),
                "premium": float(ctx["premium"]) if ctx.get("premium") is not None else 0.0,
                "day_ntl_vlm": float(ctx["dayNtlVlm"]),
            }
        )
    if not rows:
        return pd.DataFrame(columns=list(HYPERLIQUID_ASSET_CONTEXT_COLUMNS))
    return pd.DataFrame(rows)[list(HYPERLIQUID_ASSET_CONTEXT_COLUMNS)]


def _parse_predicted_funding_rows(
    predicted: list[list[Any]], coins: tuple[str, ...], observed_at: pd.Timestamp
) -> pd.DataFrame:
    rows = []
    for coin, venues in predicted:
        if coin not in coins:
            continue
        for venue, info in venues:
            rows.append(
                {
                    "timestamp": observed_at,
                    "coin": coin,
                    "venue": venue,
                    "funding_rate": float(info["fundingRate"]),
                    "next_funding_time": float(info["nextFundingTime"]),
                    "funding_interval_hours": float(info["fundingIntervalHours"]),
                }
            )
    if not rows:
        return pd.DataFrame(columns=list(HYPERLIQUID_PREDICTED_FUNDING_COLUMNS))
    return pd.DataFrame(rows)[list(HYPERLIQUID_PREDICTED_FUNDING_COLUMNS)]


def _parse_bbo_row(coin: str, book: dict[str, Any]) -> pd.DataFrame:
    bids, asks = book["levels"][0], book["levels"][1]
    if not bids or not asks:
        return pd.DataFrame(columns=list(HYPERLIQUID_BBO_COLUMNS))
    row = {
        "timestamp": pd.to_datetime(int(book["time"]), unit="ms", utc=True),
        "coin": coin,
        "bid_price": float(bids[0]["px"]),
        "bid_size": float(bids[0]["sz"]),
        "ask_price": float(asks[0]["px"]),
        "ask_size": float(asks[0]["sz"]),
    }
    return pd.DataFrame([row])[list(HYPERLIQUID_BBO_COLUMNS)]


class HyperliquidMarketSnapshotCollector:
    """Each poll: one `metaAndAssetCtxs` call, one `predictedFundings`
    call (both cover every Hyperliquid coin; filtered down to `coins`
    here), and one `l2Book` call per coin in `coins` for top-of-book only.
    """

    def __init__(
        self,
        coins: tuple[str, ...],
        data_dir: Path,
        *,
        poll_interval_secs: float = 30.0,
        client: HyperliquidInfoClient | None = None,
        now: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not coins:
            raise ValueError("HyperliquidMarketSnapshotCollector requires at least one coin")
        self._coins = coins
        self._data_dir = Path(data_dir)
        self._poll_interval_secs = poll_interval_secs
        self._client = client or HyperliquidInfoClient()
        self._now = now
        self._sleep = sleep

    def poll_once(self) -> int:
        observed_at = self._now()
        universe, asset_ctxs = self._client.get_meta_and_asset_ctxs()
        asset_ctx_df = _parse_asset_ctx_rows(universe, asset_ctxs, self._coins, observed_at)
        predicted = self._client.get_predicted_fundings()
        predicted_df = _parse_predicted_funding_rows(predicted, self._coins, observed_at)
        bbo_frames = [_parse_bbo_row(coin, self._client.get_l2_book(coin)) for coin in self._coins]
        bbo_df = (
            pd.concat(bbo_frames, ignore_index=True)
            if bbo_frames
            else pd.DataFrame(columns=list(HYPERLIQUID_BBO_COLUMNS))
        )

        written = 0
        if not asset_ctx_df.empty:
            write_hyperliquid_asset_ctx(asset_ctx_df, self._data_dir)
            written += len(asset_ctx_df)
        if not predicted_df.empty:
            write_hyperliquid_predicted_funding(predicted_df, self._data_dir)
            written += len(predicted_df)
        if not bbo_df.empty:
            write_hyperliquid_bbo(bbo_df, self._data_dir)
            written += len(bbo_df)
        return written

    def run_forever(self) -> None:
        run_polling_loop(
            name="hyperliquid market snapshot",
            poll_once=self.poll_once,
            poll_interval_secs=self._poll_interval_secs,
            sleep=self._sleep,
            extra_log_fields={"coins": ",".join(self._coins)},
        )
