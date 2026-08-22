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

The current v2 path uses a hybrid acquisition model. Bybit REST provides
backfillable klines, funding, and OI immediately, while the immutable v2 raw
collector builds the non-backfillable trades/L2/liquidation history in
parallel. Dataset provenance keeps these sources distinct; historical candles
are never presented as historical microstructure.

- `src/data/normalized_event.py` — deterministic Bronze-to-Silver mapping for
  full L2 level updates, trades, liquidations, and ticker fields. Exact venue
  decimals remain strings until feature computation and every row retains its
  raw event ID and payload hash.
- `src/data/normalized_store.py` — atomic, immutable, checksummed Silver
  Parquet parts and one manifest per verified Bronze source part.
- `src/data/normalization_pipeline.py` and
  `scripts/normalize_raw_bybit.py` — verified, idempotent raw-lake rebuild with
  an auditable report. Unknown or invalid venue shapes fail closed.
- `src/data/data_quality.py` and `scripts/audit_silver_quality.py` — daily
  integrity, identity, lineage, record-contract, ordering, and causal-time
  checks. A failed immutable part receives a quarantine overlay and is never
  silently repaired, moved, or deleted.
- `src/data/dataset_catalog.py` and `scripts/snapshot_silver_dataset.py` —
  reproducible point-in-time dataset versions bound to exact Silver checksums,
  receive-time availability, code version, filters, and cutoff.
- `src/features/store.py` — immutable Gold Parquet API. Every feature batch is
  bound to an exact dataset/code version and carries a maximum source timestamp
  per row; future, duplicate, null, infinite, non-numeric, or naive-time rows
  fail closed before storage.
- `src/features/order_flow.py` — first ATAS-like family from actual normalized
  trades and L2, not candle proxies: aggressor delta/CVD/VWAP and strict
  snapshot-plus-delta depth imbalance, spread, mid, and microprice. Stateful
  chunk/replay tests prevent boundary-dependent results.
- `src/features/auction.py` — tick-size-aware footprint rows, diagonal and
  stacked imbalance, causal VWAP/AVWAP, and contiguous Volume Profile value
  areas with POC, VAH, and VAL.
- `src/features/interaction.py` — exact L2 size additions, cancellations and
  replenishment plus tape-based multi-level sweeps, absorption stalls, and
  weakening-aggression exhaustion at new extremes.
- `src/features/divergence.py` — regular and hidden divergence evidence from
  delayed, fully confirmed pivots. Signals are timestamped when confirmation
  becomes available, never at the earlier pivot bar. Price/CVD outputs carry
  an explicit `cvd_` prefix so the order-flow family cannot be mistaken for
  several independent confirmations.
- `src/features/momentum_flow.py` — independent Market-Cipher-like family
  composed from documented standard EMA normalization, rolling money flow,
  Wilder RSI, and confirmed divergences. It uses no copied proprietary code
  or private formula.
- `src/features/derivatives.py` — causal mark/index basis, OI change,
  annualized funding context, long/short positioning, liquidation imbalance,
  and one composite derivatives-crowding family from point-in-time aligned
  observations.
- `src/data/instruments.py` — canonical spot/perpetual/future/option identity
  with exact venue/product namespace resolution and no symbol guessing.
- `src/features/cross_venue.py` — point-in-time latest-quote snapshots with
  staleness, clock-age, cross-venue median, and price-outlier checks.
- `src/data/binance_adapter.py` — lossless Binance USD-M raw/combined-stream
  envelope plus fail-closed REST-snapshot bridging and `U/u/pu` diff-depth
  continuity. Live transport and normalization remain separate gates.

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

### Live-validation status

The target VPS has successfully fetched and validated real Bybit public REST
data for BTCUSDT, ETHUSDT, and SOLUSDT. The 2026-08-22 hybrid checkpoint
contains 46,569 rows across 27 Parquet files with no duplicate timestamps:
seven days of 1m/5m/15m/1h/4h/1d klines, funding and 5-minute OI, plus the
500 most recent long/short samples exposed by Bybit for each symbol. The final
1-minute REST row can still be forming at download time and must be excluded
by the point-in-time dataset builder before research use.

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

The funding and OI clients have also been exercised against the real public
Bybit endpoints on the VPS. This does not remove the requirement for
point-in-time validation and dataset manifests.

## Market microstructure: order book, trade tape, liquidations (NOT backfillable)

Unlike everything else on this page, Bybit does not offer historical
order-book depth, historical trade-by-trade tape, or historical liquidation
events via REST — these only exist as live WebSocket streams. There is no
way to download the past; a collector has to run continuously, starting
from whenever it's first launched, to build up a history at all.

- `src/data/orderbook_state.py` — legacy client-side reduced order-book path.
  It is retained for compatibility but is not the v2 Bronze source of truth.
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

The v2 raw WebSocket path is live-verified on the VPS for BTCUSDT, ETHUSDT,
and SOLUSDT. It stores the exact venue payload before normalization and has
strict replay, sequence, health, and immutable-soak binding. The older
`microstructure_collector.py` path above remains historical compatibility
code; new development must use `bybit_raw_collector.py`, `raw_store.py`, and
the v2 normalization pipeline.
