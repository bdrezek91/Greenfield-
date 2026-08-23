"""Bridge: convert stored Deribit near-ATM option-ticker rows
(src/data/deribit_option_ticker_storage.py, Cycle 36) into
src.features.options.OptionQuote objects that
build_option_surface_snapshot can consume.

Kept as a separate, storage-aware module rather than folded into
src/features/options.py, which stays storage-agnostic - the same
"feature layer never imports storage directly" separation as
src/features/order_flow.py's list[NormalizedMarketEvent] inputs (built
by the caller from Silver rows, not read from disk inside the feature
module itself).

The stored schema has only one `timestamp` per row (when this project
polled Deribit's ticker endpoint), not a separate exchange-event time -
same "bulk REST snapshot, one poll timestamp" shape as
src/data/schema_deribit_market_summary.py (Cycle 24). `event_at_utc` and
`received_at_utc` are both set to that poll timestamp - not a
fabricated distinction this data doesn't actually have.
"""

from __future__ import annotations

import pandas as pd

from src.data.instruments import ProductType, VenueInstrument
from src.features.options import OptionQuote


def option_quotes_from_ticker_rows(df: pd.DataFrame) -> list[OptionQuote]:
    """One `OptionQuote` per row of a
    src.data.deribit_option_ticker_storage frame. A row that fails
    `VenueInstrument`/`OptionQuote`'s own validation (e.g. a NaN
    mark_iv/underlying_price from a poll that hit a transient gap) is
    skipped rather than raising - a caller building a surface snapshot
    only cares about the quotes that are actually usable, and
    `build_option_surface_snapshot` itself already fails closed if none
    of them pass its quality gates.
    """
    quotes: list[OptionQuote] = []
    for row in df.itertuples():
        try:
            instrument = VenueInstrument(
                exchange="deribit",
                market_type="option",
                venue_symbol=str(row.instrument_name),
                base_asset=str(row.base_currency),
                quote_asset="USD",
                product_type=ProductType.OPTION,
                expiry_utc=row.expiry_utc.to_pydatetime(),
                option_strike=str(row.option_strike),
                option_right=str(row.option_right),
            )
            quote = OptionQuote(
                instrument=instrument,
                event_at_utc=row.timestamp.to_pydatetime(),
                received_at_utc=row.timestamp.to_pydatetime(),
                underlying_price=float(row.underlying_price),
                mark_iv=float(row.mark_iv),
                bid_iv=None if pd.isna(row.bid_iv) else float(row.bid_iv),
                ask_iv=None if pd.isna(row.ask_iv) else float(row.ask_iv),
                open_interest=float(row.open_interest),
                delta=None if pd.isna(row.delta) else float(row.delta),
            )
        except (ValueError, TypeError):
            continue
        quotes.append(quote)
    return quotes
