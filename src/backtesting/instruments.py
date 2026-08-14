"""Build NautilusTrader CryptoPerpetual instrument definitions from configs/instruments.yaml.

See the warning at the top of that file: specs here are placeholder
approximations, not a live sync from Kraken's instrument-info endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Currency, Price, Quantity

DEFAULT_INSTRUMENTS_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "instruments.yaml"
)
KRAKEN_VENUE = Venue("KRAKEN")


@dataclass(frozen=True)
class InstrumentSpecs:
    quote_currency: Currency
    settlement_currency: Currency
    maker_fee: Decimal
    taker_fee: Decimal
    price_precision: int
    size_precision: int
    price_increment: Decimal
    size_increment: Decimal
    default_leverage: Decimal
    base_currencies: dict[str, str]


def load_instrument_specs(path: Path = DEFAULT_INSTRUMENTS_CONFIG_PATH) -> InstrumentSpecs:
    raw = yaml.safe_load(path.read_text())
    return InstrumentSpecs(
        quote_currency=Currency.from_str(raw["quote_currency"]),
        settlement_currency=Currency.from_str(raw["settlement_currency"]),
        maker_fee=Decimal(str(raw["fees"]["maker_fee"])),
        taker_fee=Decimal(str(raw["fees"]["taker_fee"])),
        price_precision=int(raw["price_precision"]),
        size_precision=int(raw["size_precision"]),
        price_increment=Decimal(str(raw["price_increment"])),
        size_increment=Decimal(str(raw["size_increment"])),
        default_leverage=Decimal(str(raw["default_leverage"])),
        base_currencies=dict(raw["base_currencies"]),
    )


def instrument_id_for(symbol: str) -> InstrumentId:
    """Kraken Futures perpetuals as `<SYMBOL>-PERP.KRAKEN`, e.g.
    `BTCUSD-PERP.KRAKEN`.

    `symbol` is OUR OWN canonical ticker+USD convention (see
    configs/symbols.yaml), NOT Kraken's raw contract code - NautilusTrader's
    `Symbol` parser reserves `_` as a multi-leg/spread-instrument separator,
    so Kraken's actual raw codes (`PF_XBTUSD`, underscore-prefixed, BTC
    spelled XBT) can't be used directly here without breaking order
    matching (`ValueError: Invalid symbol format for component: PF`,
    discovered when this was first tried). `src.data.kraken_client`
    translates our canonical symbol to Kraken's raw code only at the
    point of an actual API call - the one place that translation needs to
    exist.
    """
    return InstrumentId(Symbol(f"{symbol}-PERP"), KRAKEN_VENUE)


def build_crypto_perpetual(symbol: str, specs: InstrumentSpecs) -> CryptoPerpetual:
    if symbol not in specs.base_currencies:
        raise ValueError(f"no base currency configured for symbol {symbol!r}")

    now_ns = 0  # instrument definition timestamps are not meaningful for a static backtest spec
    return CryptoPerpetual(
        instrument_id=instrument_id_for(symbol),
        raw_symbol=Symbol(symbol),
        base_currency=Currency.from_str(specs.base_currencies[symbol]),
        quote_currency=specs.quote_currency,
        settlement_currency=specs.settlement_currency,
        is_inverse=False,
        price_precision=specs.price_precision,
        size_precision=specs.size_precision,
        price_increment=Price(specs.price_increment, precision=specs.price_precision),
        size_increment=Quantity(specs.size_increment, precision=specs.size_precision),
        ts_event=now_ns,
        ts_init=now_ns,
        maker_fee=specs.maker_fee,
        taker_fee=specs.taker_fee,
    )
