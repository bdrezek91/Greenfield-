# VPS Deployment

## Target environment

Linux VPS, Docker + Docker Compose, Git/GitHub as the source of truth. No
Windows-specific assumptions anywhere in the codebase or tooling.

## Getting started

```bash
git clone <repo-url>
cd ai-trading-lab
cp .env.example .env   # fill in real values, .env is gitignored
docker compose build
docker compose up -d research
```

Run the test suite in a container (matches CI):

```bash
docker compose run --rm tests
```

## Services

`docker-compose.yml` defines logically separate services rather than a
single monolithic container. As of Phase 1:

Use a dedicated checkout with `COMPOSE_PROJECT_NAME=greenfield-v2`. Phase 1 raw
collectors and the alert receiver build from the smaller locked
`docker/Dockerfile.collector`, while historical/research images remain
separate. Raw collectors bind the exact host `DATA_DIR` tested by preflight;
never point it at another application's directory or Docker volume.

- `research` — long-running interactive workspace for backtests/experiments.
- `tests` — one-shot test runner.
- `research-worker` — the autonomous research factory (`src/research/`),
  one gated cycle per `--interval-hours`. See the dedicated section below.
- `paper-session` — one explicitly-approved strategy on Bybit Demo.
- `raw-bybit-btc`, `raw-bybit-eth`, `raw-bybit-sol` — isolated, exact-payload
  Phase 1 public-market collectors with independent queues and replay state.
- `microstructure-collector` — preserved reduced collector under the `legacy`
  profile; it is not the Greenfield v2 source of truth.
- `long-short-ratio-collector` — the existing Bybit ratio collector.
- `data-compactor` — daily, atomic compaction of microstructure files.
- `docker-compose.monitoring.yml` adds the isolated `monitoring` profile:
  node-exporter textfile ingestion, Prometheus, Alertmanager, the durable
  Greenfield alert receiver, and Grafana.

Each service does one job and can be restarted/scaled independently. None of
the collector, monitoring, research-worker, or paper services has a LIVE code
path capable of placing a real order - see `docs/LIVE_READINESS_CHECKLIST.md`.

## Autonomous research factory

```bash
# Research worker - runs a bounded, gated research cycle on a schedule.
docker compose up -d research-worker
docker compose logs -f research-worker
docker compose ps research-worker            # health status
docker compose stop research-worker          # graceful (SIGTERM, finishes current cycle)
docker compose restart research-worker

# Paper session - requires PAPER_SYMBOL/PAPER_STRATEGY in .env first (see
# .env.example) - never auto-selected. Set these only after a candidate
# has been promoted via src/research/promotion.py and a human has reviewed it.
docker compose up -d paper-session
docker compose logs -f paper-session
docker compose stop paper-session

# Microstructure collection + daily compaction.
docker compose up -d microstructure-collector
docker compose up -d data-compactor
docker compose logs -f microstructure-collector data-compactor
```

**Status/health**: `docker compose ps` shows each service's healthcheck
state (`healthy`/`unhealthy`/`starting`). `research-worker` and
`paper-session` are marked unhealthy if their heartbeat/checkpoint file
hasn't updated recently (see their `healthcheck` blocks in
`docker-compose.yml`) - `restart: unless-stopped` then restarts the
container automatically.

**Disk-space guard**: `src/research/orchestrator.py:run_cycle` checks free
disk space before doing any work and aborts the cycle (status `ERROR`,
nothing partially written) if fewer than 500MB are free, rather than
failing mid-write.

**Retention**: research cycle reports (`reports/research_cycles/<id>/`)
and the trial ledger/promotion state are never deleted automatically -
retention/archival is an operational decision for whoever runs the VPS,
not something this codebase enforces unilaterally against research
history. Docker's own log rotation is configured per service
(`max-size: 10m`, `max-file: 5`) so container logs don't grow unbounded.

**Backup**: back up the `ai-trading-lab-data` and `ai-trading-lab-reports`
named volumes (or their host bind-mount equivalents) - both are declared
in `docker-compose.yml`'s `volumes:` section and contain everything that
isn't reproducible from git (klines/funding/OI/microstructure data,
`reports/experiments/experiments.jsonl`, `reports/research/trial_ledger.jsonl`,
`reports/research/promotion_state.json`, every past cycle's report bundle).
A plain `docker run --rm -v ai-trading-lab-reports:/from -v $PWD:/to alpine
tar czf /to/reports-backup.tar.gz -C /from .` (same pattern for the data
volume) is sufficient - no database to dump.

**Disaster recovery**: restoring the two volumes from a backup and running
`docker compose up -d` again is sufficient to resume - the trial ledger and
promotion state are plain JSON/JSONL files, not requiring any migration.
`src/research/locking.py:CycleLock` detects and takes over a stale lock
left by a crashed prior worker (checks whether the recorded PID is still
alive) automatically on the next cycle, so a hard container kill mid-cycle
does not permanently wedge `research-worker`.

The Phase 1 raw collectors have an implemented metrics, dashboard, and durable
alert path described below. Existing research-worker, paper-session, and legacy
collector health states are not all converted into Prometheus metrics yet;
that remaining coverage is tracked separately and must not be confused with
the completed raw-collector rules.

## Monitoring and alert delivery

The monitoring stack is deliberately vendor-neutral and version-pinned:

- node-exporter reads only `*.prom` collector textfiles from the data volume;
- Prometheus retains 30 days and evaluates the checked-in alert rules;
- Alertmanager groups, deduplicates, retries, and sends firing/resolved events;
- `scripts/run_alert_receiver.py` fsyncs each valid delivery to
  `reports/alerts/YYYY-MM-DD.jsonl` before any optional external delivery;
- Grafana provisions the raw-collector operations dashboard from git.

The pinned images are Prometheus `v3.12.0`, Alertmanager `v0.32.1`,
node-exporter `v1.12.1`, and Grafana `13.1.0`. Do not replace these with
floating `latest` tags. Set at least this secret in the gitignored `.env`:

```dotenv
GRAFANA_ADMIN_PASSWORD=<unique-high-entropy-password>
```

For actual off-host notification, set an HTTPS endpoint that accepts the
Alertmanager JSON body, optionally with a bearer token:

```dotenv
ALERT_FORWARD_URL=https://alerts.example.net/greenfield
ALERT_FORWARD_BEARER_TOKEN=<optional-secret>
```

The local journal remains authoritative. If external forwarding fails, the
receiver writes a sanitized failure record and returns HTTP 502 so
Alertmanager retries. A direct Slack/Telegram webhook usually expects a
different JSON schema; place a small HTTPS adapter or automation endpoint in
front of it rather than weakening the receiver contract.

The forwarded document retains the Alertmanager body and adds reserved
`greenfield.schema_version` and `greenfield.event_id` fields. The same event ID
is sent as `X-Greenfield-Event-ID`. In Make.com map `greenfield.event_id` into
the Gmail/Telegram message body so the off-host receipt can be correlated with
the durable VPS journal without relying on whether an adapter exposes headers.

Validate and start collectors plus monitoring:

```bash
export GREENFIELD_DEPLOY_COMMIT="$(git rev-parse HEAD)"
python scripts/preflight_phase1_vps.py \
  --source-commit "$GREENFIELD_DEPLOY_COMMIT" \
  --data-dir "${DATA_DIR}" \
  --minimum-free-gib 90 \
  --report-path reports/phase1_vps_preflight.json

python scripts/forecast_phase1_capacity.py \
  --source-commit "$GREENFIELD_DEPLOY_COMMIT" \
  --sample-data-dir "${DATA_DIR}/calibration/2026-08-21-lossless-smoke" \
  --sample-health-path \
    "${DATA_DIR}/calibration/2026-08-21-lossless-smoke/health/bybit-linear-smoke.json" \
  --target-data-dir "${DATA_DIR}" \
  --report-path reports/phase1_capacity_forecast.json

export GREENFIELD_SOAK_ID="phase1-$(date -u +%Y%m%dt%H%M%sz)"
python scripts/start_phase1_soak.py \
  --session-id "$GREENFIELD_SOAK_ID" \
  --source-commit "$GREENFIELD_DEPLOY_COMMIT" \
  --preflight-report reports/phase1_vps_preflight.json \
  --capacity-forecast-report reports/phase1_capacity_forecast.json

docker compose \
  -f docker-compose.yml \
  -f docker-compose.monitoring.yml \
  --profile monitoring config --quiet

docker compose \
  -f docker-compose.yml \
  -f docker-compose.monitoring.yml \
  --profile monitoring up -d \
  raw-bybit-btc raw-bybit-eth raw-bybit-sol \
  node-exporter alert-receiver alertmanager prometheus grafana

docker compose \
  -f docker-compose.yml \
  -f docker-compose.monitoring.yml \
  --profile monitoring ps
```

Do not start the seven-day clock unless both preflight and capacity forecast
exit zero. The immutable marker hashes both reports and rechecks current free
bytes. Preflight requires
Linux, CPython 3.11, the exact clean commit, a working Docker daemon and merged
Compose model, atomic fsync/rename behavior on `DATA_DIR`, at least 90 GiB free
by default, no pending host reboot, DNS/TLS/WebSocket access to Bybit, no more
than one second of clock skew against Bybit's public time endpoint, a strong
Grafana password, loopback monitoring ports, and a configured external HTTPS
alert destination. The JSON
report contains booleans and measurements but never secret values or URLs.
The second command exclusively creates
`DATA_DIR/health/soak_sessions/<session-id>.json`; it refuses a stale
preflight, dirty/different checkout, or overwrite. Create the marker immediately
before `docker compose up` and preserve its path. Its UTC timestamp—not a later
operator estimate—is the acceptance window boundary.

A pending `/var/run/reboot-required` always fails preflight. Schedule the reboot
without disrupting unrelated workloads, verify those workloads independently,
and rerun preflight; never start a seven-day clock that is already guaranteed
to be interrupted by maintenance.

Prometheus, Alertmanager, and Grafana bind to `127.0.0.1` by default. Do not
expose them directly to the Internet. From an operator workstation:

```bash
ssh -L 3000:127.0.0.1:3000 \
    -L 9090:127.0.0.1:9090 \
    -L 9093:127.0.0.1:9093 user@vps
```

Then open `http://127.0.0.1:3000`. The provisioned dashboard is in the
`Greenfield v2` folder. Test the entire routing path by creating a temporary
Alertmanager alert:

```bash
export GREENFIELD_OPERATOR="named-operator"
curl --fail-with-body -X POST \
  -H 'Content-Type: application/json' \
  -d "[{\"labels\":{\"alertname\":\"GreenfieldDeliveryTest\",\"severity\":\"warning\",\"owner\":\"${GREENFIELD_OPERATOR}\",\"component\":\"test\",\"session_id\":\"${GREENFIELD_SOAK_ID}\",\"source_commit\":\"${GREENFIELD_DEPLOY_COMMIT}\"},\"annotations\":{\"summary\":\"End-to-end delivery test\",\"description\":\"Expected test alert\"}}]" \
  http://127.0.0.1:9093/api/v2/alerts

docker compose \
  -f docker-compose.yml \
  -f docker-compose.monitoring.yml \
  --profile monitoring exec alert-receiver \
  python -c "from pathlib import Path; print(sorted(Path('/app/reports/alerts').glob('*.jsonl'))[-1].read_text())"
```

Phase 1 operational acceptance requires evidence that the test appears in
Alertmanager, Grafana, the durable journal, and the configured off-host channel.
Merely starting the containers is not acceptance.

Export the external system's receipt as JSON without credentials or webhook
URLs. Its minimum contract is:

```json
{
  "schema_version": 1,
  "event_id": "<X-Greenfield-Event-ID: 64 lowercase hex>",
  "delivery_status": "delivered",
  "received_at_utc": "2026-08-22T12:00:05Z",
  "receipt_id": "<immutable external message or delivery ID>",
  "destination": "<non-secret operator channel name>"
}
```

Capture the `event_id` from the durable journal and confirm the same
`X-Greenfield-Event-ID` correlation header at the external adapter, then run:

```bash
python scripts/capture_phase1_alert_delivery.py \
  --session-path \
    "${DATA_DIR}/health/soak_sessions/${GREENFIELD_SOAK_ID}.json" \
  --journal-path reports/phase1-evidence/alert-journal.jsonl \
  --external-receipt-path reports/phase1-evidence/off-host-receipt.json \
  --event-id "${GREENFIELD_ALERT_EVENT_ID}" \
  --operator "${GREENFIELD_OPERATOR}" \
  --report-path reports/phase1_alert_delivery.json
```

The validator requires a durable receipt followed by `forward_success`, exactly
one matching synthetic test alert carrying the same session, commit, and
operator, an external `delivered` receipt with the same event ID, and no more
than one hour between local forwarding success and external receipt. It only
validates captured evidence and sends no network request.

### Recovery-drill evidence

Perform the five Phase 1 drills during the immutable soak session: graceful
SIGTERM, process restart, VPS reboot, bounded disk backlog, and verified storage
restore. Preserve the three collector health JSON files immediately before and
after each drill, run `scripts/replay_raw_bybit.py` after recovery, and pass the
artifacts to `scripts/capture_phase1_recovery_drill.py`. For graceful SIGTERM,
also preserve the stopped/drained snapshots. For a reboot, preserve the host
boot ID before and after. For backlog and restore, preserve the measured queue
capacity/peak and independently calculated bundle hashes respectively.

The capture tool is deliberately non-destructive: the operator performs each
approved host action and it only validates the resulting evidence. It binds the
report to the soak session and deployed commit, requires zero loss or sequence
uncertainty, and refuses to overwrite an existing report. See
`docs/RAW_COLLECTOR_V2.md` section 12 for the command and exact per-drill gates.
Calculate each report's SHA-256 and place both its repository-root-relative path
and hash in `reports/phase1_operational_evidence.yaml`. The final acceptance
command reopens and verifies all five files; a YAML checkbox alone cannot pass.

After the soak and drills, gather the small reports and receipts under one
protected evidence root and run `scripts/build_phase1_evidence_bundle.py`. The
resulting manifest content-addresses the soak marker, its bound capacity
forecast, soak report, replay, alert journal, off-host receipt, correlated
alert-delivery report, secret-free deployed configuration, and all drill
reports. Record the manifest SHA-256 in
the operator approval. The final gate
re-hashes every referenced file and cross-checks it against the reports it
actually evaluates. Do not include `.env`, API keys, bearer tokens, or a Compose
render with interpolated secrets in the bundle.

Every reconnect or sequence uncertainty counted by the soak audit also needs a
named reconciliation artifact. Hash the file, put that SHA-256 in the matching
operational-evidence entry, and add it to the bundle with
`--extra-artifact incident/<incident_id>=reports/incidents/<file>`. Missing,
duplicate, changed, or unbundled incident evidence makes acceptance fail.

## Secrets

API keys and other secrets are provided exclusively through `.env`
(gitignored). `.env.example` documents every required variable with no real
values. No secret is ever hardcoded or committed.

## Runtime modes

`TRADING_MODE` in `.env` controls `RESEARCH` / `BACKTEST` / `PAPER` / `LIVE`,
enforced by `src/execution/mode.py:resolve_trading_mode()` (Phase 10) —
every entry point that might submit real orders routes through it rather
than reading `TRADING_MODE` directly. `LIVE` is refused unless the
environment variable `CONFIRM_LIVE_TRADING=I_UNDERSTAND_THE_RISK` is *also*
set explicitly — not reachable by setting `TRADING_MODE=LIVE` alone. No
live-trading execution path exists yet regardless (only `PAPER`, against a
Bybit simulation backend via `scripts/paper_trade.py`, is implemented).

## Paper trading (Bybit testnet or Demo Trading)

Two simulation backends are supported, selected with `--backend` (see
`src/execution/paper_node.py`'s module docstring):

```bash
# --backend testnet (default): requires a *separate* testnet.bybit.com
# account registration - geo-blocked for some EU users independent of a
# regular bybit.com account.
export TRADING_MODE=PAPER
export BYBIT_TESTNET_API_KEY=...
export BYBIT_TESTNET_API_SECRET=...
python scripts/paper_trade.py --symbol BTCUSDT --timeframe 1h --strategy trend_following

# --backend demo: Bybit's "Demo Trading" feature for account/order actions,
# reachable from an existing regular bybit.com login (avatar menu -> Demo
# Trading), no separate site registration - use this if testnet.bybit.com
# registration is geo-blocked for you. Generate these while switched into
# Demo Trading mode. ALSO needs a real mainnet BYBIT_API_KEY/SECRET
# ("Tylko do snapshotu" / read-only is enough, cannot place orders or move
# funds) - Bybit's Demo Trading REST only supports private/account
# endpoints, so market-data (public) calls need a plain mainnet client
# instead; see src/execution/paper_node.py's module docstring.
export TRADING_MODE=PAPER
export BYBIT_DEMO_API_KEY=...
export BYBIT_DEMO_API_SECRET=...
export BYBIT_API_KEY=...          # real mainnet, read-only permission is enough
export BYBIT_API_SECRET=...
python scripts/paper_trade.py --symbol BTCUSDT --timeframe 1h \
    --strategy trend_following --backend demo
```

This runs the exact same `Strategy` class used in backtests
(`src/strategies/`) live against the chosen Bybit simulation backend, via
NautilusTrader's native Bybit adapter (`src/execution/paper_node.py`) —
the Phase 0 architecture decision's payoff: no strategy code changes
between backtest and paper. See `docs/RESEARCH_METHODOLOGY.md` for the
expected-vs-actual fill comparison this mode is meant to produce (latency,
slippage, rejected orders, data issues).

**Known limitation:** this repository's development sessions run under a
network policy that blocks `api.bybit.com`, so live testnet connectivity
has not been exercised end to end in that environment (only construction of
the trading node, without connecting, has been verified — see
`docs/PROJECT_STATUS.md`). Validate connectivity on the actual VPS or a
local machine with unrestricted network access before relying on this.

## Long-running paper trading (Phase 14)

`scripts/paper_trade.py`'s `node.run()` is a single blocking call: any
failure (e.g. a testnet disconnect) kills the whole process. For a session
meant to run for days, use the supervised entry point instead:

```bash
export TRADING_MODE=PAPER
export BYBIT_API_KEY=...
export BYBIT_API_SECRET=...
python scripts/run_paper_session.py --symbol BTCUSDT --timeframe 1h \
    --strategy trend_following --checkpoint-path reports/paper_session.json
```

Also accepts `--backend demo` (with `BYBIT_DEMO_API_KEY`/`BYBIT_DEMO_API_SECRET`)
in place of the testnet env vars, same as `paper_trade.py` above.

This adds three things on top of `paper_trade.py`:

- **Fill recording** (`src/execution/session_recorder.py`): real
  `OrderFilled`/`OrderRejected` events are scored against the intents that
  produced them (the section-32 expected-vs-actual comparison
  `docs/RESEARCH_METHODOLOGY.md` calls for), not just replayed backtest
  trades.
- **Restart with backoff** (`src/execution/supervisor.py`): a failure
  triggers a retry with exponential backoff, up to `--max-restarts`,
  instead of the process dying on the first disconnect.
- **Durable checkpointing** (`src/execution/session_state.py`): restart
  count, last error, and the latest fill summary are written to
  `--checkpoint-path` as plain JSON before and after every attempt, so a
  full process restart (a deploy, an out-of-memory kill, `docker compose
  restart`) resumes the session's history instead of losing it.

Same known limitation as above: not exercised against real Bybit testnet
connectivity in this repository's development sessions. The
retry/checkpoint logic itself is unit-tested with an injected failing
`run_fn` (`tests/unit/test_supervisor.py`), and fill recording is proven
against NautilusTrader's real backtest engine
(`tests/integration/test_session_recorder_live.py`) — only the live
network path is unverified here.

## Data persistence

Datasets and models live in a Docker volume / host directory
(`DATA_DIR`), never inside the git-tracked repository tree.

## Monitoring status

Raw-collector health, freshness, connectivity, event/write backlog, queues,
reconnects, sequence uncertainty, drops, storage, monitoring-target health,
and alert-forwarding failures are implemented. Broader resource and service
coverage will be added with each later phase; deployment and a successful
seven-day measured run on the target VPS are still required evidence.

## Status

This document defines both the current deployment procedure and the later
target approach. Additional services are added only as their code and
operational evidence are implemented — see `docs/PROJECT_STATUS.md`.
