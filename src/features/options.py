"""Point-in-time Deribit-style option surface quality and context features."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median

from src.data.instruments import ProductType, VenueInstrument


class OptionSurfaceError(ValueError):
    """A surface cannot be built without guessing or violating causality."""


@dataclass(frozen=True, slots=True)
class OptionQuote:
    instrument: VenueInstrument
    event_at_utc: datetime
    received_at_utc: datetime
    underlying_price: float
    mark_iv: float
    bid_iv: float | None
    ask_iv: float | None
    open_interest: float
    delta: float | None = None

    def __post_init__(self) -> None:
        if self.instrument.product_type != ProductType.OPTION:
            raise OptionSurfaceError("option quote requires an option instrument")
        if self.event_at_utc.tzinfo is None or self.received_at_utc.tzinfo is None:
            raise OptionSurfaceError("option timestamps must be timezone-aware")
        if self.event_at_utc.astimezone(UTC) > self.received_at_utc.astimezone(UTC):
            raise OptionSurfaceError("option event cannot arrive before it occurs")
        values = (self.underlying_price, self.mark_iv, self.open_interest)
        if any(not math.isfinite(value) for value in values):
            raise OptionSurfaceError("option quote values must be finite")
        if self.underlying_price <= 0 or self.mark_iv <= 0 or self.open_interest < 0:
            raise OptionSurfaceError("underlying/IV must be positive and OI non-negative")
        for name, value in (("bid_iv", self.bid_iv), ("ask_iv", self.ask_iv)):
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise OptionSurfaceError(f"{name} must be finite and positive")
        if self.delta is not None and (
            not math.isfinite(self.delta) or not -1.0 <= self.delta <= 1.0
        ):
            raise OptionSurfaceError("option delta must be between -1 and 1")


@dataclass(frozen=True, slots=True)
class OptionSurfaceQuality:
    max_age_seconds: float = 30.0
    min_open_interest: float = 1.0
    max_iv_spread: float = 10.0
    max_underlying_deviation_fraction: float = 0.005
    target_delta: float = 0.25
    max_delta_distance: float = 0.10

    def __post_init__(self) -> None:
        if (
            self.max_age_seconds <= 0
            or self.min_open_interest < 0
            or self.max_iv_spread <= 0
            or not 0 < self.max_underlying_deviation_fraction < 1
            or not 0 < self.target_delta < 0.5
            or not 0 < self.max_delta_distance < 0.5
        ):
            raise OptionSurfaceError("invalid option surface quality configuration")


@dataclass(frozen=True, slots=True)
class OptionExpiryFeatures:
    expiry_utc: datetime
    days_to_expiry: float
    atm_strike: float
    atm_iv: float
    call_25d_iv: float | None
    put_25d_iv: float | None
    put_call_skew_25d: float | None
    risk_reversal_25d: float | None
    butterfly_25d: float | None
    call_open_interest: float
    put_open_interest: float
    put_call_oi_ratio: float | None
    quote_count: int


@dataclass(frozen=True, slots=True)
class OptionSurfaceSnapshot:
    as_of_utc: datetime
    max_source_timestamp_utc: datetime
    base_asset: str
    quote_asset: str
    accepted_quote_count: int
    rejected_quote_count: int
    rejection_counts: dict[str, int]
    expiries: tuple[OptionExpiryFeatures, ...]
    near_atm_iv: float
    term_structure_slope_per_year: float | None
    implied_realized_spread: float | None
    max_open_interest_strike: float


def build_option_surface_snapshot(
    quotes: list[OptionQuote],
    *,
    as_of_utc: datetime,
    realized_volatility: float | None = None,
    quality: OptionSurfaceQuality | None = None,
) -> OptionSurfaceSnapshot:
    """Build causal surface context from quotes available by ``as_of_utc`` only."""
    quality = quality or OptionSurfaceQuality()
    if as_of_utc.tzinfo is None:
        raise OptionSurfaceError("surface as-of timestamp must be timezone-aware")
    as_of = as_of_utc.astimezone(UTC)
    if realized_volatility is not None and (
        not math.isfinite(realized_volatility) or realized_volatility <= 0
    ):
        raise OptionSurfaceError("realized volatility must be finite and positive")

    accepted: list[OptionQuote] = []
    rejected: Counter[str] = Counter()
    for quote in quotes:
        reason = _individual_rejection(quote, as_of=as_of, quality=quality)
        if reason is None:
            accepted.append(quote)
        else:
            rejected[reason] += 1
    if not accepted:
        raise OptionSurfaceError("no option quotes passed point-in-time quality gates")

    base_assets = {quote.instrument.base_asset.upper() for quote in accepted}
    quote_assets = {quote.instrument.quote_asset.upper() for quote in accepted}
    exchanges = {quote.instrument.exchange.lower() for quote in accepted}
    if len(base_assets) != 1 or len(quote_assets) != 1 or len(exchanges) != 1:
        raise OptionSurfaceError("one surface cannot mix exchanges, underlyings, or quote assets")

    latest_by_instrument: dict[tuple[str, str, str], OptionQuote] = {}
    for quote in sorted(
        accepted,
        key=lambda item: (
            item.received_at_utc.astimezone(UTC),
            item.event_at_utc.astimezone(UTC),
            item.instrument.venue_key,
        ),
    ):
        if quote.instrument.venue_key in latest_by_instrument:
            rejected["superseded"] += 1
        latest_by_instrument[quote.instrument.venue_key] = quote
    accepted = list(latest_by_instrument.values())

    reference_underlying = median(quote.underlying_price for quote in accepted)
    consistent: list[OptionQuote] = []
    for quote in accepted:
        deviation = abs(quote.underlying_price / reference_underlying - 1.0)
        if deviation > quality.max_underlying_deviation_fraction:
            rejected["underlying_outlier"] += 1
        else:
            consistent.append(quote)
    if not consistent:
        raise OptionSurfaceError("all option quotes failed underlying consistency")

    by_expiry: dict[datetime, list[OptionQuote]] = defaultdict(list)
    for quote in consistent:
        assert quote.instrument.expiry_utc is not None
        by_expiry[quote.instrument.expiry_utc.astimezone(UTC)].append(quote)

    expiries: list[OptionExpiryFeatures] = []
    for expiry, expiry_quotes in sorted(by_expiry.items()):
        feature = _expiry_features(
            expiry_quotes,
            expiry=expiry,
            as_of=as_of,
            underlying=reference_underlying,
            quality=quality,
        )
        if feature is None:
            rejected["missing_atm_pair"] += len(expiry_quotes)
        else:
            expiries.append(feature)
    if not expiries:
        raise OptionSurfaceError("no expiry contains a two-sided ATM call/put pair")

    term_slope = None
    if len(expiries) >= 2:
        near, far = expiries[0], expiries[-1]
        year_fraction = (far.days_to_expiry - near.days_to_expiry) / 365.0
        if year_fraction > 0:
            term_slope = (far.atm_iv - near.atm_iv) / year_fraction
    strikes = sorted({_strike(quote) for quote in consistent})
    max_oi_strike = max(
        strikes,
        key=lambda strike: (
            sum(quote.open_interest for quote in consistent if _strike(quote) == strike),
            -strike,
        ),
    )
    near_atm = expiries[0].atm_iv
    return OptionSurfaceSnapshot(
        as_of_utc=as_of,
        max_source_timestamp_utc=max(quote.received_at_utc.astimezone(UTC) for quote in consistent),
        base_asset=next(iter(base_assets)),
        quote_asset=next(iter(quote_assets)),
        accepted_quote_count=len(consistent),
        rejected_quote_count=sum(rejected.values()),
        rejection_counts=dict(sorted(rejected.items())),
        expiries=tuple(expiries),
        near_atm_iv=near_atm,
        term_structure_slope_per_year=term_slope,
        implied_realized_spread=(
            None if realized_volatility is None else near_atm - realized_volatility
        ),
        max_open_interest_strike=max_oi_strike,
    )


def _individual_rejection(
    quote: OptionQuote,
    *,
    as_of: datetime,
    quality: OptionSurfaceQuality,
) -> str | None:
    received = quote.received_at_utc.astimezone(UTC)
    if received > as_of:
        return "future"
    if (as_of - received).total_seconds() > quality.max_age_seconds:
        return "stale"
    assert quote.instrument.expiry_utc is not None
    if quote.instrument.expiry_utc.astimezone(UTC) <= as_of:
        return "expired"
    if quote.open_interest < quality.min_open_interest:
        return "illiquid_open_interest"
    if quote.bid_iv is None or quote.ask_iv is None:
        return "missing_two_sided_iv"
    if quote.bid_iv > quote.ask_iv:
        return "crossed_iv"
    if quote.ask_iv - quote.bid_iv > quality.max_iv_spread:
        return "wide_iv_spread"
    if not quote.bid_iv <= quote.mark_iv <= quote.ask_iv:
        return "mark_outside_market"
    return None


def _expiry_features(
    quotes: list[OptionQuote],
    *,
    expiry: datetime,
    as_of: datetime,
    underlying: float,
    quality: OptionSurfaceQuality,
) -> OptionExpiryFeatures | None:
    by_strike_right = {(_strike(quote), quote.instrument.option_right): quote for quote in quotes}
    paired_strikes = sorted(
        {
            strike
            for strike, right in by_strike_right
            if right == "call" and (strike, "put") in by_strike_right
        }
    )
    if not paired_strikes:
        return None
    atm_strike = min(paired_strikes, key=lambda strike: (abs(strike - underlying), strike))
    atm_iv = (
        by_strike_right[(atm_strike, "call")].mark_iv + by_strike_right[(atm_strike, "put")].mark_iv
    ) / 2.0
    call = _delta_quote(quotes, right="call", target=quality.target_delta)
    put = _delta_quote(quotes, right="put", target=-quality.target_delta)
    if (
        call is not None
        and abs((call.delta or 0.0) - quality.target_delta) > quality.max_delta_distance
    ):
        call = None
    if (
        put is not None
        and abs((put.delta or 0.0) + quality.target_delta) > quality.max_delta_distance
    ):
        put = None
    call_iv = None if call is None else call.mark_iv
    put_iv = None if put is None else put.mark_iv
    skew = None if call_iv is None or put_iv is None else put_iv - call_iv
    call_oi = sum(
        quote.open_interest for quote in quotes if quote.instrument.option_right == "call"
    )
    put_oi = sum(quote.open_interest for quote in quotes if quote.instrument.option_right == "put")
    return OptionExpiryFeatures(
        expiry_utc=expiry,
        days_to_expiry=(expiry - as_of).total_seconds() / 86_400.0,
        atm_strike=atm_strike,
        atm_iv=atm_iv,
        call_25d_iv=call_iv,
        put_25d_iv=put_iv,
        put_call_skew_25d=skew,
        risk_reversal_25d=None if skew is None else -skew,
        butterfly_25d=(
            None if call_iv is None or put_iv is None else (call_iv + put_iv) / 2.0 - atm_iv
        ),
        call_open_interest=call_oi,
        put_open_interest=put_oi,
        put_call_oi_ratio=None if call_oi == 0 else put_oi / call_oi,
        quote_count=len(quotes),
    )


def _delta_quote(quotes: list[OptionQuote], *, right: str, target: float) -> OptionQuote | None:
    candidates = [
        quote
        for quote in quotes
        if quote.instrument.option_right == right and quote.delta is not None
    ]
    return min(candidates, key=lambda quote: abs((quote.delta or 0.0) - target), default=None)


def _strike(quote: OptionQuote) -> float:
    assert quote.instrument.option_strike is not None
    return float(quote.instrument.option_strike)
