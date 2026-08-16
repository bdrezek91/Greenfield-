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

## Funding rate & open interest (backfillable, REST)

Same shape as klines - historical, downloadable for any past date range:

- `src/data/funding_client.py` / `src/data/open_interest_client.py` — thin
  wrappers around Bybit's public v5 funding-rate-history and open-interest
  endpoints, same injectable-transport pattern as `bybit_client.py`.
- `src/data/ingest_funding.py` / `src/data/ingest_open_interest.py` —
  pagination (time-window backwards for funding, cursor-forward for open
  interest — different pagination shapes, see each module's docstring).
- `src/data/storage.py` — `write_funding`/`read_funding` and
  `write_open_interest`/`read_open_interest`, partitioned under
  `funding/{symbol}/` and `open_interest/{symbol}/{interval}/`.
- `scripts/download_funding_oi.py` — CLI, same pattern as
  `download_data.py`.
- `src/features/pipeline.py`'s `build_feature_matrix()` accepts optional
  `funding`/`open_interest` frames and adds `funding_rate`/`oi_change`
  columns (see `EXTENDED_FEATURE_COLUMNS`) — opt-in, `None` by default so
  every existing caller/saved model is unaffected.

Same network-egress limitation as above: unit-tested against mocked
transports, not exercised against a live Bybit call in this session.

## Market microstructure: order book, trade tape, liquidations (NOT backfillable)

Unlike everything else on this page, Bybit does not offer historical
order-book depth, historical trade-by-trade tape, or historical liquidation
events via REST — these only exist as live WebSocket streams. There is no
way to download the past; a collector has to run continuously, starting
from whenever it's first launched, to build up a history at all.

- `src/data/orderbook_state.py` — client-side order book (applies Bybit's
  v5 snapshot/delta protocol), reduced to a top-of-book summary
  (best bid/ask, top-N depth, imbalance) rather than storing raw depth.
- `src/data/microstructure_parser.py` — pure parsing of raw WebSocket
  message shapes into canonical rows, deliberately isolated from the live
  connection so it's fully unit-testable offline
  (`tests/unit/test_microstructure_parser.py`,
  `tests/unit/test_orderbook_state.py`).
- `src/data/microstructure_writer.py` — batch Parquet writer: every flush
  is its own file (never a read-modify-write merge like `write_klines`,
  which would get slower every flush as a day's data grows at
  tens-of-updates-per-second frequency).
- `src/data/microstructure_collector.py` — ties the above to pybit's public
  WebSocket client (`orderbook_stream`/`trade_stream`/`liquidation_stream`),
  buffering and periodically flushing each of the three streams
  independently.
- `scripts/collect_microstructure.py` — CLI, meant to run continuously via
  `docker compose run -d` (same pattern as `run_paper_session.py`). Public
  data only — no API keys, no account/order actions, independent of
  `TRADING_MODE`.

**NOT VERIFIED IN THIS SESSION** (same network-egress limitation): pybit's
WebSocket method names and Bybit's v5 message shapes are documented from
public API docs, not exercised against a live connection here — validate
on the VPS (`docker compose run -d --name microstructure research python
scripts/collect_microstructure.py --symbol BTCUSDT`) before relying on the
collected data. Since nothing can be backfilled, collection should start as
early as possible even before every detail is validated — worst case, a
parsing bug is caught and fixed, and collection resumes from then; there
was never a way to recover the gap before that fix regardless.
