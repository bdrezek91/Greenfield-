"""Build NautilusTrader CryptoPerpetual instrument definitions from
configs/instruments.yaml (Bybit), configs/instruments_binance.yaml
(Binance), or configs/instruments_okx.yaml (OKX) - see
`venue_for_exchange`/`DEFAULT_INSTRUMENTS_CONFIG_PATHS`.

The initial BTC/ETH/SOL universe uses dated public instrument-info snapshots
with per-symbol price/size grids and explicit OKX contract multipliers. Fees
remain documented non-VIP defaults rather than account-specific schedules.

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
class SymbolInstrumentSpecs:
    base_currency: str
    price_precision: int
    size_precision: int
    price_increment: Decimal
    size_increment: Decimal
    contract_multiplier: Decimal

    def __post_init__(self) -> None:
        if not self.base_currency.strip():
            raise ValueError("symbol base currency must be non-empty")
        if self.price_precision < 0 or self.size_precision < 0:
            raise ValueError("instrument precision must be non-negative")
        if (
            self.price_increment <= 0
            or self.size_increment <= 0
            or self.contract_multiplier <= 0
        ):
            raise ValueError("instrument increments and multiplier must be positive")
        price_exponent = self.price_increment.as_tuple().exponent
        size_exponent = self.size_increment.as_tuple().exponent
        if not isinstance(price_exponent, int) or not isinstance(size_exponent, int):
            raise ValueError("instrument increments must be finite decimals")
        price_decimals = max(0, -price_exponent)
        size_decimals = max(0, -size_exponent)
        if price_decimals > self.price_precision or size_decimals > self.size_precision:
            raise ValueError("instrument precision cannot be coarser than its increment")


@dataclass(frozen=True)
class InstrumentSpecs:
    quote_currency: Currency
    settlement_currency: Currency
    maker_fee: Decimal
    taker_fee: Decimal
    default_leverage: Decimal
    base_currencies: dict[str, str]
    symbol_specs: dict[str, SymbolInstrumentSpecs]
    source_url: str
    retrieved_at_utc: str


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
    if "symbols" in raw:
        symbol_specs = {
            symbol: SymbolInstrumentSpecs(
                base_currency=item["base_currency"],
                price_precision=int(item["price_precision"]),
                size_precision=int(item["size_precision"]),
                price_increment=Decimal(str(item["price_increment"])),
                size_increment=Decimal(str(item["size_increment"])),
                contract_multiplier=Decimal(str(item.get("contract_multiplier", 1))),
            )
            for symbol, item in raw["symbols"].items()
        }
        source_url = str(raw["instrument_snapshot"]["source_url"])
        retrieved_at_utc = str(raw["instrument_snapshot"]["retrieved_at_utc"])
    else:
        # Backward-compatible loader for explicit legacy test/research files.
        symbol_specs = {
            symbol: SymbolInstrumentSpecs(
                base_currency=base,
                price_precision=int(raw["price_precision"]),
                size_precision=int(raw["size_precision"]),
                price_increment=Decimal(str(raw["price_increment"])),
                size_increment=Decimal(str(raw["size_increment"])),
                contract_multiplier=Decimal("1"),
            )
            for symbol, base in raw["base_currencies"].items()
        }
        source_url = "legacy-unversioned"
        retrieved_at_utc = "unknown"
    return InstrumentSpecs(
        quote_currency=Currency.from_str(raw["quote_currency"]),
        settlement_currency=Currency.from_str(raw["settlement_currency"]),
        maker_fee=Decimal(str(raw["fees"]["maker_fee"])),
        taker_fee=Decimal(str(raw["fees"]["taker_fee"])),
        default_leverage=Decimal(str(raw["default_leverage"])),
        base_currencies={symbol: item.base_currency for symbol, item in symbol_specs.items()},
        symbol_specs=symbol_specs,
        source_url=source_url,
        retrieved_at_utc=retrieved_at_utc,
    )


def instrument_id_for(symbol: str, exchange: str = "bybit") -> InstrumentId:
    """`<SYMBOL>-PERP.<VENUE>`, e.g. `BTCUSDT-PERP.BYBIT` or
    `BTCUSDT-PERP.BINANCE` - default `exchange="bybit"` preserves every
    existing caller's exact prior output."""
    return InstrumentId(Symbol(f"{symbol}-PERP"), venue_for_exchange(exchange))


def validate_order_grid(
    symbol: str,
    specs: InstrumentSpecs,
    *,
    price: Decimal,
    quantity: Decimal,
) -> None:
    """Reject prices/quantities that the snapshotted exchange grid rejects."""
    if symbol not in specs.symbol_specs:
        raise ValueError(f"no instrument grid configured for symbol {symbol!r}")
    symbol_spec = specs.symbol_specs[symbol]
    if price <= 0 or price % symbol_spec.price_increment != 0:
        raise ValueError(f"price does not align with {symbol}'s price increment")
    if quantity <= 0 or quantity % symbol_spec.size_increment != 0:
        raise ValueError(f"quantity does not align with {symbol}'s size increment")


def build_crypto_perpetual(
    symbol: str, specs: InstrumentSpecs, exchange: str = "bybit"
) -> CryptoPerpetual:
    if symbol not in specs.base_currencies:
        raise ValueError(f"no base currency configured for symbol {symbol!r}")
    symbol_spec = specs.symbol_specs[symbol]

    now_ns = 0  # instrument definition timestamps are not meaningful for a static backtest spec
    return CryptoPerpetual(
        instrument_id=instrument_id_for(symbol, exchange),
        raw_symbol=Symbol(symbol),
        base_currency=Currency.from_str(symbol_spec.base_currency),
        quote_currency=specs.quote_currency,
        settlement_currency=specs.settlement_currency,
        is_inverse=False,
        price_precision=symbol_spec.price_precision,
        size_precision=symbol_spec.size_precision,
        price_increment=Price(
            symbol_spec.price_increment, precision=symbol_spec.price_precision
        ),
        size_increment=Quantity(
            symbol_spec.size_increment, precision=symbol_spec.size_precision
        ),
        ts_event=now_ns,
        ts_init=now_ns,
        maker_fee=specs.maker_fee,
        taker_fee=specs.taker_fee,
    )
