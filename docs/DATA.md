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

## Status

This document defines the target data layer. Ingestion, validation, and
storage code are implemented in Phase 2 — see `docs/PROJECT_STATUS.md`.
