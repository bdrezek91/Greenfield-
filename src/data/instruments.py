"""Canonical multi-venue instrument identity and explicit symbol resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class ProductType(StrEnum):
    SPOT = "spot"
    PERPETUAL = "perpetual"
    FUTURE = "future"
    OPTION = "option"


@dataclass(frozen=True, slots=True)
class VenueInstrument:
    exchange: str
    market_type: str
    venue_symbol: str
    base_asset: str
    quote_asset: str
    product_type: ProductType
    settlement_asset: str | None = None
    expiry_utc: datetime | None = None
    option_strike: str | None = None
    option_right: str | None = None

    def __post_init__(self) -> None:
        text_fields = (
            self.exchange,
            self.market_type,
            self.venue_symbol,
            self.base_asset,
            self.quote_asset,
        )
        if any(not value or value != value.strip() for value in text_fields):
            raise ValueError("instrument identity fields must be non-empty and trimmed")
        if self.product_type in {ProductType.FUTURE, ProductType.OPTION}:
            if self.expiry_utc is None or self.expiry_utc.tzinfo is None:
                raise ValueError("dated instruments require a timezone-aware expiry")
        elif self.expiry_utc is not None:
            raise ValueError("spot and perpetual instruments cannot have expiry")
        if self.product_type == ProductType.OPTION:
            if self.option_right not in {"call", "put"} or self.option_strike is None:
                raise ValueError("options require strike and call/put right")
            try:
                strike = Decimal(self.option_strike)
            except InvalidOperation as exc:
                raise ValueError("option strike must be a valid decimal") from exc
            if not strike.is_finite() or strike <= 0:
                raise ValueError("option strike must be positive")
        elif self.option_strike is not None or self.option_right is not None:
            raise ValueError("option fields are forbidden for non-options")

    @property
    def venue_key(self) -> tuple[str, str, str]:
        return (self.exchange.lower(), self.market_type.lower(), self.venue_symbol)

    @property
    def canonical_id(self) -> str:
        base = self.base_asset.upper()
        quote = self.quote_asset.upper()
        if self.product_type == ProductType.SPOT:
            suffix = "SPOT"
        elif self.product_type == ProductType.PERPETUAL:
            settlement = (self.settlement_asset or quote).upper()
            suffix = f"PERP:{settlement}"
        elif self.product_type == ProductType.FUTURE:
            assert self.expiry_utc is not None
            suffix = f"FUT:{self.expiry_utc.astimezone(UTC):%Y%m%d}"
        else:
            assert self.expiry_utc is not None
            assert self.option_strike is not None
            assert self.option_right is not None
            right = "C" if self.option_right == "call" else "P"
            suffix = (
                f"OPT:{self.expiry_utc.astimezone(UTC):%Y%m%d}:"
                f"{self.option_strike}:{right}"
            )
        return f"{base}-{quote}:{suffix}"


class InstrumentRegistry:
    """Resolve venue identifiers without guessing across product namespaces."""

    def __init__(self, instruments: tuple[VenueInstrument, ...] = ()) -> None:
        self._by_venue: dict[tuple[str, str, str], VenueInstrument] = {}
        for instrument in instruments:
            self.register(instrument)

    def register(self, instrument: VenueInstrument) -> None:
        key = instrument.venue_key
        existing = self._by_venue.get(key)
        if existing is not None and existing != instrument:
            raise ValueError(f"ambiguous venue instrument mapping: {key}")
        self._by_venue[key] = instrument

    def resolve(self, exchange: str, market_type: str, venue_symbol: str) -> VenueInstrument:
        key = (exchange.lower(), market_type.lower(), venue_symbol)
        try:
            return self._by_venue[key]
        except KeyError as exc:
            raise KeyError(f"unknown venue instrument: {key}") from exc

    def venues_for(self, canonical_id: str) -> tuple[VenueInstrument, ...]:
        return tuple(
            sorted(
                (
                    instrument
                    for instrument in self._by_venue.values()
                    if instrument.canonical_id == canonical_id
                ),
                key=lambda item: item.venue_key,
            )
        )
