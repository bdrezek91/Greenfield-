# Greenfield v2 Raw Collector Contract and Runbook

Status: Phase 1 implementation and soak runbook

Schema: raw event v1 / manifest v1

Initial venues: Bybit linear perpetuals

Initial symbols: BTCUSDT, ETHUSDT, SOLUSDT

The source of truth for scope and phase gates remains
[GREENFIELD_V2_MASTER_PLAN.md](GREENFIELD_V2_MASTER_PLAN.md). This document is
the detailed data contract and operating procedure for its Phase 1.

## 1. Purpose and safety boundary

The collector exists to accumulate a trustworthy, owned microstructure
dataset before Greenfield adds ATAS-like features, more strategies, or AI. It
reads public market data only. It has no API credentials, account access,
order path, position authority, or LIVE capability.

Every WebSocket text message is enveloped and queued before order-book or
ticker validation. A parser, feature implementation, or schema migration can
therefore be rerun from the original venue message.

“Lossless” here means the exact UTF-8 application message delivered by the
WebSocket transport is retained in `payload_text` and protected by SHA-256.
WebSocket frame headers, TCP packets, compression frames, and whitespace added
outside the application message are not research data and are not retained.

## 2. Why the collector bypasses pybit callbacks

The official pybit client materializes order-book deltas into its own local
state and changes callback data to `type=snapshot`. That is convenient for a
consumer that only wants the current book, but it destroys the original
snapshot/delta event stream Greenfield needs for deterministic replay,
cancellation and replenishment research, and gap auditing.

The v2 collector therefore connects directly to Bybit's official public
WebSocket endpoint with `websocket-client`. It still uses the documented Bybit
protocol and does not use private or undocumented data.

Primary protocol references:

- [Bybit WebSocket connection and heartbeat](https://bybit-exchange.github.io/docs/v5/ws/connect)
- [Bybit order-book snapshot/delta protocol](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)
- [Bybit public trades](https://bybit-exchange.github.io/docs/v5/websocket/public/trade)
- [Bybit derivative ticker](https://bybit-exchange.github.io/docs/v5/websocket/public/ticker)
- [Bybit all-liquidation stream](https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation)
- [Official pybit delta materialization implementation](https://github.com/bybit-exchange/pybit/blob/master/pybit/_websocket_stream.py)

## 3. Captured streams

Each isolated symbol process subscribes to:

- `orderbook.50.{symbol}` — actual L2 snapshot and delta messages;
- `publicTrade.{symbol}` — individual aggressor-side trades;
- `allLiquidation.{symbol}` — batched liquidation events;
- `tickers.{symbol}` — snapshot/delta state containing last, mark and index
  prices, open interest, funding rate, next funding time, best bid/ask, and
  related venue fields;
- connection acknowledgements and pong messages as the `control` channel.

Depth 50 is pushed approximately every 20 ms by Bybit. It does not contain RPI
orders. Later phases may add other depths, full order book, or venue products
only through a versioned contract change.

Existing REST collectors for funding history and open-interest history remain
useful for backfill. The raw ticker feed adds point-in-time live provenance and
mark/index state; it does not rewrite the REST datasets.

## 4. Raw event v1

Each row contains:

- `schema_version` and `ingestion_version`;
- deterministic `event_id`;
- `exchange`, `market_type`, `channel`, exact `topic`, and `symbol`;
- venue `message_type`;
- `exchange_ts_ms` and local `receive_ts_ns`;
- monotonic process-local `receive_sequence`, which disambiguates equal local
  timestamps;
- matching-engine `matching_ts_ms` where Bybit supplies `cts`;
- cross `sequence` and order-book `update_id` where supplied;
- unique `connection_id` for every reconnect episode;
- exact `payload_text` and its `payload_sha256`.

The application payload is hashed before normalization. Loading a row
recomputes the hash and fails if it no longer matches.

## 5. Immutable Bronze layout

Raw parts use Hive-style partitions:

    data/raw/v1/
      exchange=bybit/
        market=linear/
          channel=orderbook/
            symbol=BTCUSDT/
              date=YYYY-MM-DD/
                part-<first-ns>-<last-ns>-<event-hash>.parquet
                part-<first-ns>-<last-ns>-<event-hash>.manifest.json

Every part:

- is sorted by receive time, receive sequence, and event ID;
- uses a fixed Arrow schema and Zstandard compression;
- is written to a same-directory temporary file, fsynced, and atomically
  renamed;
- has a separately atomic manifest with row count, time bounds, event-set
  checksum, and Parquet-file checksum;
- is immutable and idempotent if an identical batch is retried;
- fails closed on a collision, missing manifest, changed byte, duplicate, or
  stream-order regression.

The replay reader verifies every manifest and part before yielding events.
Its memory use is bounded by one part, so multi-day datasets do not need to be
loaded into RAM.

## 6. Sequence and replay rules

Order-book state uses exact decimal price and quantity values.

On a snapshot:

1. Replace both sides completely.
2. Require non-empty, non-crossed bids and asks.
3. Record `u` and `seq`.

On a delta:

1. Require a valid snapshot on the same `connection_id`.
2. Require `u == previous_u + 1`.
3. Require cross-sequence `seq` to increase, but not to be contiguous. Bybit's
   cross sequence is global and normally jumps between messages.
4. Delete a level when size is zero, insert a missing level, or update an
   existing level.
5. Validate both sides and reject a crossed or empty book before committing
   the update.

Any missing, repeated, or regressed `u`, non-increasing `seq`, delta before a
snapshot, invalid decimal, or crossed book invalidates local state. The live
connection is closed and rebuilt from a new venue snapshot. The offending raw
message remains in Bronze. Replay fails with a specific exception rather than
guessing through the uncertainty.

Ticker state follows Bybit's documented snapshot/delta rule: omitted delta
fields retain their last snapshot value. A delta before a snapshot or a
non-increasing ticker cross sequence is rejected.

## 7. Backpressure and failure behavior

The WebSocket thread only envelopes, queues, and validates messages. A
separate writer thread creates Parquet parts. Defaults are:

- queue capacity: 100,000 events;
- maximum part batch: 10,000 events;
- flush interval: 5 seconds;
- JSON ping interval: 20 seconds;
- reconnect backoff: 1 to 30 seconds.

If the queue fills, a message is invalid UTF-8/JSON, the writer fails, or
health evidence cannot be published, the process stops and records a failed
state. It never continues while pretending the dataset is complete.

SIGINT and SIGTERM both close the socket, drain the queue, fsync final parts,
publish final health, and exit. Docker `restart: unless-stopped` handles an
unexpected process or host restart. Every connection receives a new ID and
must start its book and ticker state from snapshots.

## 8. Supervision and observability

Docker Compose defines three independent services:

- `raw-bybit-btc`;
- `raw-bybit-eth`;
- `raw-bybit-sol`.

A problem in one symbol therefore cannot corrupt or force reconnects in the
other two. The old reduced `microstructure-collector` is preserved under the
`legacy` profile.

Each raw service publishes:

- latest atomic JSON: `data/health/bybit-linear-<symbol>.json`;
- Prometheus textfile: `data/health/bybit-linear-<symbol>.prom`;
- fsynced daily JSONL history under
  `data/health/history/bybit-linear-<symbol>/`.

Metrics include connected state, heartbeat, event/write counts, queue depth,
part count, reconnects, sequence uncertainty, dropped events, last event,
last flush, raw-volume capacity, and last error. Container health fails on a stale heartbeat,
failed/stopped status, or any dropped event. Sequence-uncertainty and reconnect
counter increases must alert an operator and be reconciled with a successful
new snapshot and replay.

## 9. Operating commands

Build and start the three isolated collectors:

    docker compose build raw-bybit-btc raw-bybit-eth raw-bybit-sol
    docker compose up -d raw-bybit-btc raw-bybit-eth raw-bybit-sol

Inspect state:

    docker compose ps
    docker compose logs -f raw-bybit-btc raw-bybit-eth raw-bybit-sol
    python scripts/check_raw_collector_health.py \
      --health-path data/health/bybit-linear-btcusdt.json

Verify every manifest and replay without loading the full lake into memory:

    python scripts/replay_raw_bybit.py \
      --data-dir data \
      --report-path reports/raw_replay.json

Create a verified, event-identical compacted mirror for one partition:

    python scripts/compact_raw_bybit.py \
      --channel orderbook \
      --symbol BTCUSDT \
      --utc-date YYYY-MM-DD

Compaction never deletes or changes Bronze source parts. A future retention
policy may archive verified source parts to durable object storage, but that is
not an implicit compaction action.

Stop gracefully:

    docker compose stop raw-bybit-btc raw-bybit-eth raw-bybit-sol

## 10. Monitoring and alert delivery

`docker-compose.monitoring.yml` supplies the version-pinned monitoring profile.
It scrapes the three collector textfiles, evaluates checked-in rules, persists
30 days of Prometheus state, provisions a Grafana operations dashboard, and
routes alerts through a durable JSONL receiver. The receiver always fsyncs the
Alertmanager payload before it optionally forwards to an operator-controlled
HTTPS endpoint.

Start it together with the collectors after setting `GRAFANA_ADMIN_PASSWORD`
in `.env`:

    export GREENFIELD_DEPLOY_COMMIT="$(git rev-parse HEAD)"
    python scripts/preflight_phase1_vps.py \
      --source-commit "$GREENFIELD_DEPLOY_COMMIT" \
      --data-dir "${DATA_DIR}" \
      --report-path reports/phase1_vps_preflight.json

    docker compose \
      -f docker-compose.yml \
      -f docker-compose.monitoring.yml \
      --profile monitoring up -d \
      raw-bybit-btc raw-bybit-eth raw-bybit-sol \
      node-exporter alert-receiver alertmanager prometheus grafana

Ports 3000, 9090, and 9093 bind only to VPS loopback unless an operator
explicitly changes `MONITORING_BIND_ADDRESS`. Use an SSH tunnel. The full setup,
external delivery variables, and end-to-end alert test are in
`docs/VPS_DEPLOYMENT.md#monitoring-and-alert-delivery`.

Repository implementation is not deployment evidence. Before beginning the
soak, prove one synthetic alert appears in Alertmanager, Grafana, the durable
`reports/alerts` journal, and the configured off-host operator channel.
The preflight report must be qualified and archived in the same evidence
bundle; a failed check means the seven-day clock has not started.

## 11. Incident response

Every critical collector alert makes the affected interval ineligible for
research until investigated. Preserve health history, raw parts, manifests,
container logs, alert-journal records, and exact UTC times before restarting.

- **stale/disconnected/no events:** verify VPS and exchange connectivity, then
  allow reconnect; require a fresh order-book snapshot before deltas resume;
- **sequence uncertainty or dropped event:** quarantine from the last proven
  checkpoint through the next verified snapshot; run full manifest validation
  and strict replay; never reset a counter merely to clear an alert;
- **write backlog/queue pressure:** preserve the process if possible, inspect
  disk and I/O, and stop gracefully before the bounded queue can overflow;
- **storage below 10%:** archive only verified data according to an explicit
  retention decision; compaction never deletes Bronze source parts;
- **monitoring/forwarding failure:** inspect the local alert journal first,
  restore external delivery, and run the synthetic end-to-end alert again.

Record the cause, affected partitions, replay result, recovery action, and
operator in the soak evidence bundle. If continuity cannot be proven, keep the
partition quarantined.

## 12. Seven-day Phase 1 soak

Start all three services and record the exact UTC start time. Do not restart
them merely to hide an alert. Investigate and preserve every incident.

After at least seven continuous days:

    python scripts/audit_raw_soak.py \
      --data-dir data \
      --days 7 \
      --max-gap-secs 30 \
      --report-path reports/raw_collector_soak.json

Then run full manifest verification and replay. Archive:

- soak report;
- replay report and checksum;
- service configuration and source commit;
- disk usage and event counts by symbol/channel/day;
- every reconnect, sequence uncertainty, dropped event, disk-pressure alert,
  VPS reboot, and recovery action;
- evidence that graceful stop and restart both produced a new snapshot and a
  valid replay.

Copy `configs/phase1_operational_evidence.example.yaml` to the gitignored
reports directory, replace every placeholder with real immutable evidence, and
run the final fail-closed gate with the exact deployed SHA:

    cp configs/phase1_operational_evidence.example.yaml \
      reports/phase1_operational_evidence.yaml
    python scripts/check_phase1_acceptance.py \
      --source-commit "$(git rev-parse HEAD)" \
      --soak-report reports/raw_collector_soak.json \
      --replay-report reports/raw_replay.json \
      --operational-evidence reports/phase1_operational_evidence.yaml \
      --report-path reports/phase1_acceptance.json

The gate requires all five drills, off-host alert proof, a complete BTC/ETH/SOL
book/ticker replay, nonempty trades/orderbook/ticker/liquidation channels,
explicit operator approval, and one reconciliation record for every reconnect
or sequence uncertainty counted by the soak. Its output hashes all three input
documents so the accepted bundle cannot be silently substituted later.

Phase 1 does not exit until all master-plan criteria pass. A short live test is
evidence for implementation behavior, not a substitute for the soak.

## 13. Current verification evidence

On 2026-08-21 a local public-feed smoke test captured all three symbols on one
connection for approximately twelve seconds:

- 1,276 exact raw messages;
- 1,007 order-book messages;
- 227 ticker messages;
- 41 trade messages;
- zero dropped events;
- zero sequence uncertainties;
- all 1,276 received messages flushed before exit;
- valid 50-by-50 final books for BTC, ETH, and SOL;
- deterministic replay checksum
  `e2b6e792da5d73954d34cb41618d56949959cdb66306d0310c9d3d5a73c1cc61`.

No liquidation occurred during that short interval. The subscription and
payload contract follow Bybit's current official all-liquidation
documentation; the seven-day soak is expected to provide real examples.

The smoke test also exposed and led to fixes for two operational defects:

- SIGINT initially triggered reconnect instead of process shutdown;
- equal local receive timestamps could reorder snapshot and delta without an
  explicit receive sequence.

Both paths now have deterministic handling and regression tests.

## 14. Known limitations before Phase 1 exit

- Seven continuous days per symbol have not yet been demonstrated.
- VPS reboot, prolonged disk backlog, and storage restoration drills still
  require measured evidence on the target host.
- The persistent Prometheus/Alertmanager/Grafana/receiver configuration exists
  and is tested as code, but it must still be deployed and exercised on the VPS,
  including a real off-host delivery endpoint.
- Liquidation payloads must be observed in the soak dataset.
- Bybit is the only raw venue in Phase 1. Binance, OKX, Coinbase, and Deribit
  belong to Phase 3 after Phase 2 data contracts.
- This layer intentionally implements no ATAS-like features, Market
  Cipher-like calculations, signals, strategies, or AI. Those consume this
  data only after the dataset is research-eligible.
