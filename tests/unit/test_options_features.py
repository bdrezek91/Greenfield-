from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.data.instruments import ProductType, VenueInstrument
from src.features.options import (
    OptionQuote,
    OptionSurfaceError,
    OptionSurfaceQuality,
    build_option_surface_snapshot,
)

AS_OF = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _quote(
    *,
    expiry_days: int,
    strike: float,
    right: str,
    mark_iv: float,
    delta: float,
    open_interest: float = 10.0,
    received_seconds_ago: float = 1.0,
    underlying_price: float = 100.0,
    exchange: str = "deribit",
) -> OptionQuote:
    expiry = AS_OF + timedelta(days=expiry_days)
    venue_symbol = f"BTC-{expiry:%d%b%y}-{strike:g}-{right[0].upper()}"
    instrument = VenueInstrument(
        exchange=exchange,
        market_type="option",
        venue_symbol=venue_symbol,
        base_asset="BTC",
        quote_asset="USD",
        product_type=ProductType.OPTION,
        settlement_asset="BTC",
        expiry_utc=expiry,
        option_strike=f"{strike:g}",
        option_right=right,
    )
    received = AS_OF - timedelta(seconds=received_seconds_ago)
    return OptionQuote(
        instrument=instrument,
        event_at_utc=received - timedelta(milliseconds=25),
        received_at_utc=received,
        underlying_price=underlying_price,
        mark_iv=mark_iv,
        bid_iv=mark_iv - 1.0,
        ask_iv=mark_iv + 1.0,
        open_interest=open_interest,
        delta=delta,
    )


def _surface(expiry_days: int, *, atm_call_iv: float, atm_put_iv: float) -> list[OptionQuote]:
    return [
        _quote(
            expiry_days=expiry_days,
            strike=90,
            right="call",
            mark_iv=62,
            delta=0.75,
            open_interest=10,
        ),
        _quote(
            expiry_days=expiry_days,
            strike=90,
            right="put",
            mark_iv=60,
            delta=-0.25,
            open_interest=50,
        ),
        _quote(
            expiry_days=expiry_days,
            strike=100,
            right="call",
            mark_iv=atm_call_iv,
            delta=0.50,
            open_interest=100,
        ),
        _quote(
            expiry_days=expiry_days,
            strike=100,
            right="put",
            mark_iv=atm_put_iv,
            delta=-0.50,
            open_interest=80,
        ),
        _quote(
            expiry_days=expiry_days,
            strike=110,
            right="call",
            mark_iv=55,
            delta=0.25,
            open_interest=20,
        ),
        _quote(
            expiry_days=expiry_days,
            strike=110,
            right="put",
            mark_iv=63,
            delta=-0.75,
            open_interest=10,
        ),
    ]


def test_builds_atm_skew_term_structure_and_open_interest_context() -> None:
    snapshot = build_option_surface_snapshot(
        _surface(30, atm_call_iv=50, atm_put_iv=52) + _surface(90, atm_call_iv=58, atm_put_iv=60),
        as_of_utc=AS_OF,
        realized_volatility=40,
    )

    near, far = snapshot.expiries
    assert snapshot.accepted_quote_count == 12
    assert snapshot.rejected_quote_count == 0
    assert snapshot.near_atm_iv == pytest.approx(51)
    assert snapshot.implied_realized_spread == pytest.approx(11)
    assert snapshot.term_structure_slope_per_year == pytest.approx(48.6666667)
    assert snapshot.max_open_interest_strike == 100
    assert near.atm_strike == 100
    assert near.call_25d_iv == 55
    assert near.put_25d_iv == 60
    assert near.put_call_skew_25d == 5
    assert near.risk_reversal_25d == -5
    assert near.butterfly_25d == pytest.approx(6.5)
    assert near.call_open_interest == 130
    assert near.put_open_interest == 140
    assert near.put_call_oi_ratio == pytest.approx(140 / 130)
    assert far.days_to_expiry == pytest.approx(90)


def test_quality_gates_reject_bad_quotes_without_polluting_surface() -> None:
    valid = _surface(30, atm_call_iv=50, atm_put_iv=52)
    template = valid[0]
    invalid = [
        replace(
            template,
            instrument=replace(template.instrument, venue_symbol="future"),
            event_at_utc=AS_OF + timedelta(seconds=1),
            received_at_utc=AS_OF + timedelta(seconds=2),
        ),
        replace(
            template,
            instrument=replace(template.instrument, venue_symbol="stale"),
            event_at_utc=AS_OF - timedelta(seconds=362),
            received_at_utc=AS_OF - timedelta(seconds=361),
        ),
        replace(
            template,
            instrument=replace(template.instrument, venue_symbol="illiquid"),
            open_interest=0,
        ),
        replace(
            template,
            instrument=replace(template.instrument, venue_symbol="missing"),
            bid_iv=None,
        ),
        replace(
            template,
            instrument=replace(template.instrument, venue_symbol="crossed"),
            bid_iv=64,
            ask_iv=63,
        ),
        replace(
            template,
            instrument=replace(template.instrument, venue_symbol="wide"),
            bid_iv=40,
            ask_iv=60,
        ),
        replace(
            template,
            instrument=replace(template.instrument, venue_symbol="outside"),
            mark_iv=70,
            bid_iv=60,
            ask_iv=65,
        ),
        replace(
            template,
            instrument=replace(template.instrument, venue_symbol="outlier"),
            underlying_price=110,
        ),
    ]

    snapshot = build_option_surface_snapshot(valid + invalid, as_of_utc=AS_OF)

    assert snapshot.accepted_quote_count == 6
    assert snapshot.rejected_quote_count == 8
    assert snapshot.rejection_counts == {
        "crossed_iv": 1,
        "future": 1,
        "illiquid_open_interest": 1,
        "mark_outside_market": 1,
        "missing_two_sided_iv": 1,
        "stale": 1,
        "underlying_outlier": 1,
        "wide_iv_spread": 1,
    }


def test_future_quote_cannot_change_point_in_time_features() -> None:
    quotes = _surface(30, atm_call_iv=50, atm_put_iv=52)
    future = replace(
        quotes[2],
        mark_iv=99,
        bid_iv=98,
        ask_iv=100,
        event_at_utc=AS_OF + timedelta(seconds=1),
        received_at_utc=AS_OF + timedelta(seconds=2),
    )

    baseline = build_option_surface_snapshot(quotes, as_of_utc=AS_OF)
    guarded = build_option_surface_snapshot(quotes + [future], as_of_utc=AS_OF)

    assert guarded.expiries == baseline.expiries
    assert guarded.near_atm_iv == baseline.near_atm_iv
    assert guarded.rejection_counts == {"future": 1}


def test_latest_available_quote_supersedes_older_instrument_observation() -> None:
    quotes = _surface(30, atm_call_iv=50, atm_put_iv=52)
    older = replace(
        quotes[2],
        mark_iv=40,
        bid_iv=39,
        ask_iv=41,
        event_at_utc=AS_OF - timedelta(seconds=11),
        received_at_utc=AS_OF - timedelta(seconds=10),
    )

    snapshot = build_option_surface_snapshot([older, *quotes], as_of_utc=AS_OF)

    assert snapshot.accepted_quote_count == 6
    assert snapshot.rejection_counts == {"superseded": 1}
    assert snapshot.near_atm_iv == 51


def test_missing_usable_delta_leaves_25_delta_metrics_empty() -> None:
    quotes = [
        replace(quote, delta=0.5 if quote.instrument.option_right == "call" else -0.5)
        for quote in _surface(30, atm_call_iv=50, atm_put_iv=52)
    ]

    snapshot = build_option_surface_snapshot(quotes, as_of_utc=AS_OF)

    expiry = snapshot.expiries[0]
    assert expiry.call_25d_iv is None
    assert expiry.put_25d_iv is None
    assert expiry.risk_reversal_25d is None
    assert expiry.butterfly_25d is None


def test_rejects_mixed_venues_and_invalid_inputs() -> None:
    quotes = _surface(30, atm_call_iv=50, atm_put_iv=52)
    mixed = replace(
        quotes[0],
        instrument=replace(quotes[0].instrument, exchange="other"),
    )

    with pytest.raises(OptionSurfaceError, match="cannot mix exchanges"):
        build_option_surface_snapshot([mixed, *quotes], as_of_utc=AS_OF)
    with pytest.raises(OptionSurfaceError, match="timezone-aware"):
        build_option_surface_snapshot(quotes, as_of_utc=AS_OF.replace(tzinfo=None))
    with pytest.raises(OptionSurfaceError, match="realized volatility"):
        build_option_surface_snapshot(quotes, as_of_utc=AS_OF, realized_volatility=0)
    with pytest.raises(OptionSurfaceError, match="quality configuration"):
        OptionSurfaceQuality(max_age_seconds=0)


def test_default_freshness_covers_poll_cycle_and_grace_then_expires() -> None:
    boundary = _surface(30, atm_call_iv=50, atm_put_iv=52)
    boundary = [replace(quote, received_at_utc=AS_OF - timedelta(seconds=360),
                        event_at_utc=AS_OF - timedelta(seconds=361)) for quote in boundary]
    snapshot = build_option_surface_snapshot(boundary, as_of_utc=AS_OF)
    assert snapshot.accepted_quote_count == len(boundary)

    stale = [replace(quote, received_at_utc=AS_OF - timedelta(seconds=361),
                     event_at_utc=AS_OF - timedelta(seconds=362)) for quote in boundary]
    with pytest.raises(OptionSurfaceError, match="no option quotes"):
        build_option_surface_snapshot(stale, as_of_utc=AS_OF)


def test_short_freshness_window_requires_explicit_research_override() -> None:
    with pytest.raises(OptionSurfaceError, match="poll interval plus collection grace"):
        OptionSurfaceQuality(max_age_seconds=30)

    quality = OptionSurfaceQuality(max_age_seconds=30, allow_short_freshness_window=True)
    assert quality.max_age_seconds == 30
