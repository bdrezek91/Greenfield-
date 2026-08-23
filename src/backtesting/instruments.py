"""Build NautilusTrader CryptoPerpetual instrument definitions from
configs/instruments.yaml (Bybit), configs/instruments_binance.yaml
(Binance), or configs/instruments_okx.yaml (OKX) - see
`venue_for_exchange`/`DEFAULT_INSTRUMENTS_CONFIG_PATHS`.

See the warning at the top of each config file: specs here are
placeholder/documented-default approximations, not a live per-account
sync from any exchange's instrument-info endpoint.

Every function here defaults `exchange="bybit"`, preserving the exact
prior behavior for every existing caller that doesn't pass it - see
docs/CLAUDE_CODE_CONTINUATION.md's Cycle 25 section for why Binance
support was deferred across several earlier cycles until both this AND a
real klines source (src/data/binance_klines_storage.py) could ship
together as one complete, working cycle rather than a facade; Cycle 32
extended the same pattern to OKX (src/data/okx_klines_storage.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Currency, Price, Quantity

_CONFIGS_DIR = Path(__file__).resolve().parents[2] / "configs"
DEFAULT_INSTRUMENTS_CONFIG_PATH = _CONFIGS_DIR / "instruments.yaml"
DEFAULT_INSTRUMENTS_CONFIG_PATHS: dict[str, Path] = {
    "bybit": DEFAULT_INSTRUMENTS_CONFIG_PATH,
    "binance": _CONFIGS_DIR / "instruments_binance.yaml",
    "okx": _CONFIGS_DIR / "instruments_okx.yaml",
}
BYBIT_VENUE = Venue("BYBIT")
_VENUES: dict[str, Venue] = {
    "bybit": BYBIT_VENUE,
    "binance": Venue("BINANCE"),
    "okx": Venue("OKX"),
}


def venue_for_exchange(exchange: str) -> Venue:
    if exchange not in _VENUES:
        raise ValueError(f"unsupported exchange {exchange!r}, expected one of {tuple(_VENUES)}")
    return _VENUES[exchange]


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


def load_instrument_specs(
    path: Path | None = None, *, exchange: str = "bybit"
) -> InstrumentSpecs:
    """Load instrument specs for `exchange` (default "bybit", preserving
    every existing caller's behavior). Pass `path` to override the config
    file directly (e.g. a test fixture) - it always wins over `exchange`.
    """
    if path is None:
        if exchange not in DEFAULT_INSTRUMENTS_CONFIG_PATHS:
            raise ValueError(
                f"unsupported exchange {exchange!r}, "
                f"expected one of {tuple(DEFAULT_INSTRUMENTS_CONFIG_PATHS)}"
            )
        path = DEFAULT_INSTRUMENTS_CONFIG_PATHS[exchange]
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
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


def instrument_id_for(symbol: str, exchange: str = "bybit") -> InstrumentId:
    """`<SYMBOL>-PERP.<VENUE>`, e.g. `BTCUSDT-PERP.BYBIT` or
    `BTCUSDT-PERP.BINANCE` - default `exchange="bybit"` preserves every
    existing caller's exact prior output."""
    return InstrumentId(Symbol(f"{symbol}-PERP"), venue_for_exchange(exchange))


def build_crypto_perpetual(
    symbol: str, specs: InstrumentSpecs, exchange: str = "bybit"
) -> CryptoPerpetual:
    if symbol not in specs.base_currencies:
        raise ValueError(f"no base currency configured for symbol {symbol!r}")

    now_ns = 0  # instrument definition timestamps are not meaningful for a static backtest spec
    return CryptoPerpetual(
        instrument_id=instrument_id_for(symbol, exchange),
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
