"""Parse Deribit's option instrument-name convention and select a bounded,
near-ATM subset worth polling per-instrument for bid_iv/ask_iv/delta.

Deribit's public bulk endpoint (GET /public/get_book_summary_by_currency,
src/data/deribit_market_summary_client.py, Cycle 24) returns mark_iv but
NOT bid_iv/ask_iv/delta for any instrument - live-verified this session
(GET /public/ticker?instrument_name=...) that those three fields exist
ONLY on the per-instrument ticker endpoint. src/features/options.py's
build_option_surface_snapshot hard-requires bid_iv/ask_iv (rejects
"missing_two_sided_iv" otherwise) and needs delta to select 25-delta
call/put quotes - so a real surface needs per-instrument ticker calls.

Calling /public/ticker for all ~2000 active option instruments per poll
(the same operational-impracticality argument schema_deribit_market_
summary.py already made for WS L2) is unnecessary: build_option_surface_
snapshot only ever uses the near-ATM strikes of the nearest few expiries
(atm_strike is chosen by proximity to the underlying, and 25-delta
call/put quotes are deep-ITM/OTM relative to strikes far from the
underlying only in a degenerate sense - in practice a bounded near-ATM
window covers every quote a surface snapshot could ever select). This
module picks that bounded subset from the already-fetched bulk summary
(which has strike/expiry/underlying_price for every instrument, for
free, in the one call this project already makes) instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

# Deribit's option-expiry settlement time is always 08:00 UTC (documented
# platform convention, not guessed) - the instrument name only encodes
# the date.
_EXPIRY_HOUR_UTC = 8

_MONTH_ABBREVIATIONS: dict[str, int] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


class DeribitInstrumentNameError(ValueError):
    """A Deribit instrument name did not match the expected option format."""


@dataclass(frozen=True, slots=True)
class ParsedDeribitOption:
    base_currency: str
    expiry_utc: datetime
    strike: float
    option_right: str  # "call" or "put"


def parse_deribit_option_instrument_name(name: str) -> ParsedDeribitOption:
    """Parse Deribit's `{BASE}-{DDMMMYY}-{STRIKE}-{C|P}` option naming
    convention, e.g. "BTC-25JUN27-150000-P" - live-verified against
    GET /public/get_book_summary_by_currency this session. Does NOT
    handle non-option instrument names (perpetuals/dated futures have a
    different, shorter format) - raises rather than guessing.
    """
    parts = name.split("-")
    if len(parts) != 4:
        raise DeribitInstrumentNameError(f"not a 4-part option instrument name: {name!r}")
    base, day_month_year, strike_text, right_code = parts
    # Day is 1 or 2 digits, NOT zero-padded (live-verified: Deribit uses
    # "4SEP26", not "04SEP26") - so the token is 6 or 7 characters long.
    if len(day_month_year) not in (6, 7):
        raise DeribitInstrumentNameError(f"unexpected expiry token: {day_month_year!r}")
    day_text, month_text, year_text = (
        day_month_year[:-5],
        day_month_year[-5:-2],
        day_month_year[-2:],
    )
    month = _MONTH_ABBREVIATIONS.get(month_text.upper())
    if month is None:
        raise DeribitInstrumentNameError(f"unrecognized month in expiry token: {month_text!r}")
    try:
        day = int(day_text)
        year = 2000 + int(year_text)
        strike = float(strike_text)
    except ValueError as exc:
        raise DeribitInstrumentNameError(f"unparseable option instrument name: {name!r}") from exc
    if right_code == "C":
        right = "call"
    elif right_code == "P":
        right = "put"
    else:
        raise DeribitInstrumentNameError(f"unrecognized option right code: {right_code!r}")
    expiry_utc = datetime(year, month, day, _EXPIRY_HOUR_UTC, tzinfo=UTC)
    return ParsedDeribitOption(
        base_currency=base.upper(), expiry_utc=expiry_utc, strike=strike, option_right=right
    )


def select_near_atm_option_instruments(
    summary_rows: list[dict[str, object]],
    *,
    expiries_count: int = 2,
    strikes_per_side: int = 5,
) -> list[str]:
    """From a bulk get_book_summary_by_currency(kind="option") response,
    pick the `expiries_count` nearest (soonest) expiries and, within
    each, the `strikes_per_side` strikes immediately above and below the
    current underlying price (both call and put) - a small, bounded set
    (at most `expiries_count * strikes_per_side * 2 * 2` instruments)
    worth a real per-instrument ticker call each poll. Returns
    `instrument_name`s only; the caller fetches each one's ticker.
    """
    if expiries_count <= 0 or strikes_per_side <= 0:
        raise ValueError("expiries_count and strikes_per_side must be positive")
    parsed: list[tuple[str, ParsedDeribitOption, float]] = []
    for row in summary_rows:
        name = row.get("instrument_name")
        underlying = row.get("underlying_price")
        if not isinstance(name, str) or not isinstance(underlying, int | float):
            continue
        try:
            option = parse_deribit_option_instrument_name(name)
        except DeribitInstrumentNameError:
            continue
        parsed.append((name, option, float(underlying)))
    if not parsed:
        return []

    expiries = sorted({option.expiry_utc for _, option, _ in parsed})[:expiries_count]
    selected: list[str] = []
    for expiry in expiries:
        in_expiry = [item for item in parsed if item[1].expiry_utc == expiry]
        if not in_expiry:
            continue
        underlying = in_expiry[0][2]
        for right in ("call", "put"):
            candidates = [item for item in in_expiry if item[1].option_right == right]
            candidates.sort(key=lambda item: abs(item[1].strike - underlying))
            selected.extend(name for name, _, _ in candidates[:strikes_per_side])
    return selected
