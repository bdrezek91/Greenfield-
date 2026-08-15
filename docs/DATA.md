# Data

## Scope (initial)

Market: Bybit USDT Perpetual Futures.

Symbols (starting set, expected to become dynamic later):
`BTC, ETH, SOL, XRP, BNB, DOGE, ADA, LINK, AVAX, BCH, LTC`

Timeframes: `1m, 5m, 15m, 1h, 4h, 1d`

Planned for later (architecture should not block these, but they are not
pulled from day one): funding rates, open interest, liquidation data, mark
price, index price, trades, order book.

## Source of truth

The official Bybit API (via `pybit`) is the primary source for klines,
funding rate history, open interest, mark/index price, and liquidations.
CCXT is kept available as an abstraction layer for future multi-exchange
needs, not as the primary path for Bybit-specific data.

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

## Implementation (Phase 2)

- `src/data/config.py` — loads the symbol/timeframe universe from
  `configs/symbols.yaml`.
- `src/data/bybit_client.py` — thin, injectable wrapper around Bybit's public
  v5 kline endpoint (via `pybit`). No API keys required for market data.
- `src/data/ingest.py` — pages through Bybit's kline history for a date range
  and assembles it into the canonical schema (`src/data/schema.py`).
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

This session's network egress policy blocks `api.bybit.com` (confirmed via
the agent proxy status, not a transient failure), so the ingestion pipeline
has been validated with unit tests against a mocked Bybit transport
(`tests/unit/test_ingest.py`, `tests/unit/test_bybit_client.py`), not a live
fetch. The first real download against Bybit should happen on a machine with
unrestricted egress (e.g. the target VPS) before this data is relied upon for
research — see `docs/PROJECT_STATUS.md`.
