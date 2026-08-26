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

The capacity report must explicitly contain `venue: "okx"` and
`health_namespace: "okx-swap"`; a Bybit capacity report is deliberately
rejected. The command creates evidence only and prints the exact isolated
Compose command for operator review. It does not start containers by itself.
Do not create the formal marker until the venue-specific bounded smoke and its
capacity forecast are available. Do not reuse or alter the active Bybit marker.

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
