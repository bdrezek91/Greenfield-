"""Live poller for a bounded, near-ATM set of Deribit option instrument
tickers - shares src/data/rest_poller.py's loop like every other REST
poller in this project (Cycles 17/18/24).

Each poll: (1) fetch the bulk book-summary for `currency`/kind="option"
(src/data/deribit_market_summary_client.py, already built in Cycle 24 -
reused here rather than duplicated) to get every active instrument's
strike/expiry/underlying_price, (2) pick the near-ATM subset
(src/data/deribit_option_instrument.py), (3) fetch each selected
instrument's ticker (src/data/deribit_option_ticker_client.py) for its
bid_iv/ask_iv/delta, (4) write the combined batch. Like the market-summary
poller, every poll is its own complete, independently-timestamped
snapshot - there is nothing to compare against a previous poll.

Live-verified this session: Deribit's ticker response uses
`best_bid_price`/`best_ask_price` (not `bid_price`/`ask_price`, unlike
the bulk book-summary endpoint) and nests delta under `greeks.delta`,
absent entirely (not zero) for an instrument Deribit doesn't compute
greeks for.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.deribit_market_summary_client import DeribitMarketSummaryClient
from src.data.deribit_option_instrument import (
    DeribitInstrumentNameError,
    parse_deribit_option_instrument_name,
    select_near_atm_option_instruments,
)
from src.data.deribit_option_ticker_client import DeribitOptionTickerClient
from src.data.deribit_option_ticker_storage import write_deribit_option_ticker
from src.data.rest_poller import run_polling_loop
from src.data.schema_deribit_option_ticker import DERIBIT_OPTION_TICKER_COLUMNS


def _ticker_row(
    instrument_name: str, ticker: dict[str, Any], poll_time: pd.Timestamp
) -> dict[str, Any] | None:
    try:
        parsed = parse_deribit_option_instrument_name(instrument_name)
    except DeribitInstrumentNameError:
        return None
    greeks = ticker.get("greeks")
    delta = greeks.get("delta") if isinstance(greeks, dict) else None
    return {
        "timestamp": poll_time,
        "instrument_name": instrument_name,
        "base_currency": parsed.base_currency,
        "expiry_utc": parsed.expiry_utc,
        "option_strike": parsed.strike,
        "option_right": parsed.option_right,
        "mark_price": ticker.get("mark_price"),
        "bid_price": ticker.get("best_bid_price"),
        "ask_price": ticker.get("best_ask_price"),
        "mark_iv": ticker.get("mark_iv"),
        "bid_iv": ticker.get("bid_iv"),
        "ask_iv": ticker.get("ask_iv"),
        "delta": delta,
        "open_interest": ticker.get("open_interest"),
        "underlying_price": ticker.get("underlying_price"),
    }


class DeribitOptionTickerCollector:
    def __init__(
        self,
        currency: str,
        data_dir: Path,
        *,
        expiries_count: int = 2,
        strikes_per_side: int = 5,
        poll_interval_secs: float = 300.0,
        summary_client: DeribitMarketSummaryClient | None = None,
        ticker_client: DeribitOptionTickerClient | None = None,
        clock: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._currency = currency
        self._data_dir = Path(data_dir)
        self._expiries_count = expiries_count
        self._strikes_per_side = strikes_per_side
        self._poll_interval_secs = poll_interval_secs
        self._summary_client = summary_client or DeribitMarketSummaryClient()
        self._ticker_client = ticker_client or DeribitOptionTickerClient()
        self._clock = clock
        self._sleep = sleep

    def poll_once(self) -> int:
        summary_rows = self._summary_client.get_book_summary_by_currency(
            self._currency, "option"
        )
        selected = select_near_atm_option_instruments(
            summary_rows,
            expiries_count=self._expiries_count,
            strikes_per_side=self._strikes_per_side,
        )
        if not selected:
            return 0
        poll_time = self._clock()
        rows: list[dict[str, Any]] = []
        for instrument_name in selected:
            ticker = self._ticker_client.get_ticker(instrument_name)
            row = _ticker_row(instrument_name, ticker, poll_time)
            if row is not None:
                rows.append(row)
        if not rows:
            return 0
        df = pd.DataFrame(rows)
        df = df.drop_duplicates(subset=["instrument_name"]).sort_values("instrument_name")
        df = df[list(DERIBIT_OPTION_TICKER_COLUMNS)].reset_index(drop=True)
        if df.empty:
            return 0
        write_deribit_option_ticker(df, self._data_dir, self._currency)
        return len(df)

    def run_forever(self) -> None:
        run_polling_loop(
            name="deribit option-ticker",
            poll_once=self.poll_once,
            poll_interval_secs=self._poll_interval_secs,
            sleep=self._sleep,
            extra_log_fields={"currency": self._currency},
        )
