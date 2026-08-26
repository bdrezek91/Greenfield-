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
