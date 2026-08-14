"""Thin, injectable wrapper around Kraken Futures' public OHLC endpoint via
`ccxt`'s unified `krakenfutures` exchange class.

Only market-data (unauthenticated) calls are used here. No API keys are
required for this module - see docs/DATA.md. `ccxt` was already a project
dependency (originally listed as a future multi-exchange abstraction layer,
see pyproject.toml) - using its `krakenfutures` implementation instead of
hand-rolling raw REST calls against endpoint details this session's
network egress policy prevented us from verifying directly (kraken.com is
blocked - see docs/DATA.md's migration note).
"""

from __future__ import annotations

from typing import Any, Protocol

# Kraken/ccxt OHLC page size ceiling - PLACEHOLDER, not verified against
# live documentation (kraken.com blocked in this session). Conservative
# relative to Bybit's documented 1000; verify and raise if a real run shows
# Kraken accepts more per page.
MAX_LIMIT = 500

# Our canonical ticker (configs/symbols.yaml, e.g. "BTC" in "BTCUSD") ->
# Kraken's own ticker, where it differs. Bitcoin is the only known case
# (Kraken calls it XBT); every other ticker we list matches Kraken's
# convention directly. Verify against Kraken's actual instrument list
# before trusting this for anything beyond the tickers listed in
# configs/symbols.yaml - kraken.com is blocked in this session (see
# docs/DATA.md), so this could not be checked live.
_TICKER_OVERRIDES: dict[str, str] = {"BTC": "XBT"}


def to_kraken_symbol(symbol: str) -> str:
    """Our canonical `<TICKER>USD` (e.g. `BTCUSD`) -> Kraken's raw
    perpetual contract code (e.g. `PF_XBTUSD`). See
    src.backtesting.instruments.instrument_id_for for why our canonical
    symbol can't just BE Kraken's raw code (NautilusTrader rejects the
    underscore).
    """
    if not symbol.endswith("USD"):
        raise ValueError(f"expected a <TICKER>USD symbol, got {symbol!r}")
    ticker = symbol[: -len("USD")]
    ticker = _TICKER_OVERRIDES.get(ticker, ticker)
    return f"PF_{ticker}USD"


class OHLCVTransport(Protocol):
    """Anything shaped like ccxt's `fetch_ohlcv` for this call."""

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[list[Any]]: ...


def _default_transport() -> OHLCVTransport:
    import ccxt

    return ccxt.krakenfutures()


class KrakenKlineClient:
    """Fetches raw OHLC pages from Kraken Futures. Pagination lives in `ingest.py`."""

    def __init__(self, transport: OHLCVTransport | None = None) -> None:
        self._transport = transport or _default_transport()

    def get_kline_page(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = MAX_LIMIT,
    ) -> list[list[str]]:
        """Returns rows shaped like Bybit's kline rows for ingest.py's parser
        to stay unchanged: [timestamp_ms, open, high, low, close, volume,
        turnover]. ccxt's OHLCV has no turnover field (that's a Bybit-
        specific convenience field, not standard OHLCV) - it's derived here
        as `volume * close`, an approximation documented for anyone reading
        the stored data, not a value ever reported directly by Kraken.
        `end_ms` isn't a ccxt `fetch_ohlcv` parameter (it pages forward from
        `since` only) - the caller (ingest.fetch_klines) is responsible for
        stopping once it has covered the requested range. `symbol` is our
        canonical `<TICKER>USD` form (see configs/symbols.yaml); it's
        translated to Kraken's raw contract code (`to_kraken_symbol`) only
        here, at the actual API call.
        """
        kraken_symbol = to_kraken_symbol(symbol)
        rows = self._transport.fetch_ohlcv(
            kraken_symbol, timeframe=interval, since=start_ms, limit=limit
        )
        return [
            [str(int(ts)), str(o), str(h), str(low), str(c), str(v), str(float(v) * float(c))]
            for ts, o, h, low, c, v in rows
        ]
