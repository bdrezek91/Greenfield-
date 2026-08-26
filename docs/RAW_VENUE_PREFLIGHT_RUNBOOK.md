# Raw venue preflight runbook

This preflight is the first operational gate for Phase 3. It opens only public
market-data WebSockets for Binance, OKX, Coinbase and Deribit. It has no API
keys, account access or order path.

The test requires more than DNS/TLS: it sends one representative subscription
using the same production endpoint and protocol as the collector and requires
an acknowledgement for the exact channel/product. The output is immutable and
bound to a clean, exact Git commit.

Official protocol references:

- Binance USD-M futures market streams:
  <https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/Introduction>
- OKX public WebSocket and subscription contract:
  <https://www.okx.com/docs-v5/en/>
- Coinbase Advanced Trade public WebSocket:
  <https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-overview>
- Deribit `public/subscribe`:
  <https://docs.deribit.com/api-reference/subscription-management/public-subscribe>

## Run on the target VPS

Use a clean, commit-pinned checkout that is separate from the active Bybit
Phase 1 soak. Never alter or restart that soak to run this command.

```bash
cd /path/to/clean/greenfield-checkout
COMMIT=$(git rev-parse HEAD)
uv sync --extra data --locked
uv run python scripts/preflight_raw_venues.py \
  --source-commit "$COMMIT" \
  --report-path "reports/raw-venue-preflight-$(date -u +%Y%m%dt%H%M%sz).json"
```

To qualify one venue before its own isolated smoke/soak:

```bash
uv run python scripts/preflight_raw_venues.py \
  --source-commit "$(git rev-parse HEAD)" \
  --venue okx \
  --report-path "reports/raw-venue-preflight-okx-$(date -u +%Y%m%dt%H%M%sz).json"
```

Exit code `0` means the checkout is clean and exact and every selected public
subscription was acknowledged. Any timeout, transport exception, malformed or
unrelated response, subscription error, dirty checkout or commit mismatch
returns a non-qualified report and exit code `1`. Existing report paths are
never overwritten.

This report does not authorize a collector start by itself. The next gate is a
venue-specific immutable soak marker, dedicated data/health namespace and
disabled-by-default Compose profile. Venues are deployed one at a time. A
successful preflight is connectivity evidence, not continuity, data quality or
trading-edge evidence.

## Create the venue-bound soak marker

`scripts/start_raw_venue_soak.py` is the only Phase 3 marker creator. It fails
closed unless all evidence is fresh and tied to the same clean Git commit. The
marker binds:

- exactly one supported venue and its Compose profile;
- that venue's canonical collector IDs and health-history namespace;
- hashes of the host preflight, venue WebSocket preflight, capacity forecast,
  collector/Compose configuration and monitoring configuration;
- the target data filesystem and a minimum seven-day audit window.

Example for OKX, after generating fresh reports for the exact commit:

First run the public-only bounded sample in a brand-new directory. It is hard
limited to 30-900 seconds, defaults to 120 seconds, installs a stop timer before
opening the market connection and refuses a dirty/wrong checkout or stale
transport preflight:

```bash
COMMIT=$(git rev-parse HEAD)
uv run python scripts/run_raw_okx_smoke.py \
  --source-commit "$COMMIT" \
  --venue-preflight-report reports/raw-venue-preflight-okx.json \
  --sample-root "/opt/greenfield-v2/smoke/okx-$(date -u +%Y%m%dt%H%M%sz)" \
  --duration-secs 120
```

The sample qualifies only when all BTC/ETH/SOL order-book, trade and ticker
streams are present, the raw tree is nonempty, the queue drains, received and
written counts match, shutdown is clean and drop/sequence-uncertainty counters
remain zero. Its report is immutable and binds the transport preflight hash.

Then generate the venue-specific capacity forecast. It binds the complete
smoke-report hash and applies the measured rate to seven days with a 4x burst
factor plus a 5 GiB runtime reserve:

```bash
uv run python scripts/forecast_raw_venue_capacity.py \
  --smoke-report-path /opt/greenfield-v2/smoke/<sample>/okx-smoke-report.json \
  --target-data-dir "$DATA_DIR" \
  --report-path reports/raw-venue-capacity-okx.json
```

Only after both commands qualify should the formal marker be created:

```bash
export DATA_DIR=/opt/greenfield-v2/data
COMMIT=$(git rev-parse HEAD)
uv run python scripts/start_raw_venue_soak.py \
  --venue okx \
  --session-id "phase3-okx-$(date -u +%Y%m%dt%H%M%sz)" \
  --source-commit "$COMMIT" \
  --host-preflight-report reports/phase3-host-preflight-okx.json \
  --venue-preflight-report reports/raw-venue-preflight-okx.json \
  --capacity-forecast-report reports/raw-venue-capacity-okx.json
```

The capacity report contains `venue: "okx"`, `health_namespace: "okx-swap"`
and the smoke-report SHA-256; a Bybit or unbound capacity report is deliberately
rejected. The marker command creates evidence only and prints the exact
isolated Compose command (including marker ID and commit) for operator review.
It does not start containers by itself. Do not reuse or alter the active Bybit
marker.

After the reviewed collector run, audit the same immutable marker:

```bash
uv run python scripts/audit_raw_soak.py \
  --data-dir "$DATA_DIR" \
  --session-path "$DATA_DIR/health/soak_sessions/<session-id>.json" \
  --report-path reports/raw-soak-okx.json
```

The audit automatically reads `okx-swap-*` history and emits schema v3 evidence
containing the venue and venue-preflight hash. Cross-venue history cannot
silently satisfy this audit.

The `data` extra is mandatory. A development-only environment intentionally
does not install `websocket-client`; treating that import failure as a failed
preflight prevents an incomplete research environment from being mistaken for
a deployable collector runtime.
