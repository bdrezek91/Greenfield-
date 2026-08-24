"""src.engines.volatility_options_evidence's VOLATILITY_OPTIONS
ConfirmationFamily evidence producer (Cycle 47 - sixth and last
FamilyEvidence producer). Reuses the same real OptionQuote/
build_option_surface_snapshot fixture pattern as
tests/unit/test_options_features.py, which already proved this exact
shape produces a real, non-None risk_reversal_25d.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.data.instruments import ProductType, VenueInstrument
from src.engines.contracts import ConfirmationFamily
from src.engines.volatility_options_evidence import volatility_options_family_evidence
from src.features.options import OptionQuote, build_option_surface_snapshot

AS_OF = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _quote(
    *,
    expiry_days: int,
    strike: float,
    right: str,
    mark_iv: float,
    delta: float,
    open_interest: float = 10.0,
) -> OptionQuote:
    expiry = AS_OF + timedelta(days=expiry_days)
    venue_symbol = f"BTC-{expiry:%d%b%y}-{strike:g}-{right[0].upper()}"
    instrument = VenueInstrument(
        exchange="deribit",
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
    received = AS_OF - timedelta(seconds=1)
    return OptionQuote(
        instrument=instrument,
        event_at_utc=received - timedelta(milliseconds=25),
        received_at_utc=received,
        underlying_price=100.0,
        mark_iv=mark_iv,
        bid_iv=mark_iv - 1.0,
        ask_iv=mark_iv + 1.0,
        open_interest=open_interest,
        delta=delta,
    )


def _surface(
    expiry_days: int, *, call_25d_iv: float = 55.0, put_25d_iv: float = 60.0
) -> list[OptionQuote]:
    """Same shape as test_options_features.py's own _surface helper -
    call_25d_iv < put_25d_iv by default gives a real, negative
    (bearish) risk_reversal_25d."""
    return [
        _quote(expiry_days=expiry_days, strike=90, right="call", mark_iv=62, delta=0.75),
        _quote(
            expiry_days=expiry_days, strike=90, right="put", mark_iv=60, delta=-0.25,
            open_interest=50,
        ),
        _quote(
            expiry_days=expiry_days, strike=100, right="call", mark_iv=50, delta=0.50,
            open_interest=100,
        ),
        _quote(
            expiry_days=expiry_days, strike=100, right="put", mark_iv=52, delta=-0.50,
            open_interest=80,
        ),
        _quote(
            expiry_days=expiry_days, strike=110, right="call", mark_iv=call_25d_iv, delta=0.25,
            open_interest=20,
        ),
        _quote(
            expiry_days=expiry_days, strike=110, right="put", mark_iv=put_25d_iv, delta=-0.75,
        ),
    ]


def test_bearish_skew_gets_negative_score() -> None:
    """call_25d_iv=55 < put_25d_iv=60 -> risk_reversal_25d = -5 (puts bid
    up relative to calls - bearish skew)."""
    snapshot = build_option_surface_snapshot(_surface(30), as_of_utc=AS_OF)

    evidence = volatility_options_family_evidence(snapshot)

    assert evidence is not None
    assert evidence.family == ConfirmationFamily.VOLATILITY_OPTIONS
    assert evidence.score < 0
    assert "bearish" in evidence.rationale


def test_bullish_skew_gets_positive_score() -> None:
    """call_25d_iv=62 > put_25d_iv=55 -> a positive risk reversal."""
    snapshot = build_option_surface_snapshot(
        _surface(30, call_25d_iv=62.0, put_25d_iv=55.0), as_of_utc=AS_OF
    )

    evidence = volatility_options_family_evidence(snapshot)

    assert evidence is not None
    assert evidence.score > 0
    assert "bullish" in evidence.rationale


def test_confidence_reflects_the_surfaces_own_accept_rate() -> None:
    snapshot = build_option_surface_snapshot(_surface(30), as_of_utc=AS_OF)

    evidence = volatility_options_family_evidence(snapshot)

    assert evidence is not None
    total = snapshot.accepted_quote_count + snapshot.rejected_quote_count
    assert evidence.confidence == snapshot.accepted_quote_count / total


def test_no_25d_coverage_returns_none() -> None:
    """A surface with only ATM quotes has no 25-delta call/put pair, so
    risk_reversal_25d is None - this family must return None too, not a
    fabricated score."""
    atm_only = [
        _quote(expiry_days=30, strike=100, right="call", mark_iv=50, delta=0.50),
        _quote(expiry_days=30, strike=100, right="put", mark_iv=52, delta=-0.50),
    ]
    snapshot = build_option_surface_snapshot(atm_only, as_of_utc=AS_OF)

    assert volatility_options_family_evidence(snapshot) is None
