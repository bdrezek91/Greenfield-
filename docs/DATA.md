# Data

## Scope (initial)

Market: Kraken Futures, EEA-eligible USD perpetuals. (Migrated from Bybit
USDT Perpetual Futures - see `docs/PROJECT_STATUS.md`'s exchange migration
entry for why: EU/EEA retail access to leveraged crypto derivatives is
restricted on most exchanges, and Kraken is MiFID II/MiCA-compliant for
EEA clients.)

Symbols (starting set, expected to become dynamic later) - our own
canonical `<TICKER>USD` form, e.g. `BTCUSD`, translated to Kraken's raw
contract code (`PF_XBTUSD`) only at the API-call boundary
(`src/data/kraken_client.py:to_kraken_symbol`):
`BTC, ETH, SOL, XRP, ADA, LINK, AVAX, LTC, BCH, DOGE`

Timeframes: `1m, 5m, 15m, 1h, 4h, 1d`

Planned for later (architecture should not block these, but they are not
pulled from day one): funding rates, open interest, liquidation data, mark
price, index price, trades, order book.

## Source of truth

`ccxt`'s unified `krakenfutures` exchange class is the primary source for
klines (public, unauthenticated - no API keys required). ccxt was
originally added as a future multi-exchange abstraction layer alongside a
Bybit-specific client (`pybit`); the Bybit client was removed and ccxt
promoted to the sole data-layer dependency when the project migrated to
Kraken.

## Storage

- Format: **Parquet**, partitioned by `symbol/timeframe/year-month`.
- Location: on the VPS / local disk only, under `DATA_DIR` (see
  `.env.example`). Never committed to git — `data/`, `*.parquet` are in
  `.gitignore`.
- All timestamps stored and processed internally in **UTC**.

## Integrity validation

Every dataset must be checked for:

- missing candles
- duplicates
- timestamp continuity
- zero volume
- anomalous prices
- timezone correctness
- incomplete (still-forming) candles

Validation checks live in `tests/data_integrity/` and are run against any
newly ingested dataset before it is used for a backtest or experiment.

## Versioning

Datasets are referenced by a `dataset_version` in experiment metadata (see
`docs/RESEARCH_METHODOLOGY.md`) so that a backtest result can always be tied
back to the exact data it ran against.

## Implementation

- `src/data/config.py` — loads the symbol/timeframe universe from
  `configs/symbols.yaml`.
- `src/data/kraken_client.py` — thin, injectable wrapper around Kraken
  Futures' public OHLC endpoint (via `ccxt`). No API keys required for
  market data. `to_kraken_symbol()` translates our canonical
  `<TICKER>USD` symbol to Kraken's raw contract code (`PF_<TICKER>USD`,
  with a `BTC`→`XBT` ticker override) - kept as a separate, narrow
  translation rather than using Kraken's raw code as our canonical symbol
  everywhere, because NautilusTrader's `Symbol` parser reserves `_` as a
  multi-leg/spread-instrument separator and rejects Kraken's actual
  underscore-prefixed codes outright.
- `src/data/ingest.py` — pages FORWARD through Kraken's kline history for a
  date range (ccxt's `fetch_ohlcv` pages forward from a `since` timestamp,
  the opposite of Bybit's old newest-first backward paging) and assembles
  it into the canonical schema (`src/data/schema.py`). Turnover (a
  Bybit-specific convenience field) is derived here as `volume * close`,
  not a value Kraken reports directly - documented as an approximation.
- `src/data/validate.py` — integrity checks listed above; returns a
  `ValidationReport` rather than raising, so callers decide what's fatal.
  Gaps, duplicates, non-UTC timestamps, and anomalous prices are treated as
  fatal (`report.is_valid`); zero volume and an in-progress trailing candle
  are reported but non-fatal.
- `src/data/storage.py` — Parquet read/write, partitioned by
  `symbol/timeframe/year-month.parquet`, with incremental writes merging
  and de-duplicating against existing partitions.
- `scripts/download_data.py` — CLI entry point that ties the above together:
  fetch → validate → store, skipping storage for any dataset that fails
  validation.

### Known limitation

This session's network egress policy blocks `kraken.com` (confirmed via
the agent proxy status, not a transient failure - the same class of
restriction that applied to `api.bybit.com` before the exchange
migration), so the ingestion pipeline has been validated with unit tests
against a mocked Kraken/ccxt transport (`tests/unit/test_ingest.py`,
`tests/unit/test_kraken_client.py`), not a live fetch. Several concrete
details could not be verified live and are documented as placeholders
pending a real check: the exact symbol list actually offered to EEA retail
clients, the OHLC page size ceiling (`MAX_LIMIT` in
`src/data/kraken_client.py`), and per-symbol tick/lot sizes
(`configs/instruments.yaml`). The first real download against Kraken
should happen on a machine with unrestricted egress (e.g. the target VPS)
before this data is relied upon for research — see
`docs/PROJECT_STATUS.md`.
