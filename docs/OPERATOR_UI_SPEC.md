# Greenfield v2 Operator UI and Read-only API Contract

Status: TARGET STATE contract; implementation follows stable real-time SHADOW

## 1. Purpose and safety boundary

The Operator UI is a read-only situational-awareness console for Greenfield
Market Intelligence v2. It explains what the system sees, why it returns
`LONG`, `SHORT`, `WAIT`, or `ARBITRAGE`, and whether data, research, risk, and
runtime gates are healthy. It is not an execution terminal and is not a
substitute for Prometheus, Alertmanager, or Grafana.

The first release must:

- expose no order-entry, cancel, leverage, credential, promotion, deployment,
  kill-switch-reset, or LIVE controls;
- never import or call an execution adapter;
- remain useful when every engine returns `WAIT`;
- show missing, stale, quarantined, or unverified evidence explicitly;
- preserve the distinction between independent confirmation families and
  correlated components within a family;
- bind every displayed decision to dataset, code, config, model, and feature
  versions;
- cover BTC, ETH, and SOL before any wider symbol universe.

Grafana remains the technical operations surface for low-level metrics and
alerts. The Operator UI presents domain state, decision provenance, and links
to the matching Grafana panels and runbooks.

## 2. Versioned response envelope

Every endpoint returns one immutable point-in-time envelope:

```json
{
  "schema_version": 1,
  "generated_at_utc": "2026-08-24T18:00:00Z",
  "as_of_utc": "2026-08-24T17:59:59Z",
  "status": "PASS",
  "reason_codes": [],
  "dataset_fingerprint": "sha256:...",
  "code_commit": "...",
  "config_fingerprint": "sha256:...",
  "max_source_timestamp_utc": "2026-08-24T17:59:58Z",
  "source_age_seconds": 1.0,
  "data": {}
}
```

Rules:

- timestamps are timezone-aware UTC and `max_source_timestamp_utc` may not
  follow `as_of_utc`;
- `status` is one of `PASS`, `WARN`, `FAIL`, or `UNKNOWN`;
- absent or stale source data produces `WARN`/`FAIL` plus reason codes, never
  fabricated zero values;
- fingerprints are mandatory for decision, research, SHADOW, PAPER, and risk
  responses;
- JSON numbers must be finite; unavailable values are `null` with a reason;
- lists have deterministic ordering and paginated endpoints use stable opaque
  cursors;
- a response assembled from multiple datasets reports each source and the
  maximum lineage timestamp, not only the API generation time.

## 3. Read-only endpoints

The initial API namespace is `/api/v1`:

| Endpoint | Required content |
| --- | --- |
| `GET /system` | service health, deployed commit, clock status, disk reserve, active alerts, latest integrity report |
| `GET /collectors` | exchange/symbol/channel, lifecycle state, lag, last event, reconnects, gaps, drops, queue depth, bytes and partitions |
| `GET /data-quality` | Bronze/Silver/Gold freshness, manifests, duplicates, gaps, quarantine, schema and replay status |
| `GET /market/{symbol}` | point-in-time price and market structure for BTC/ETH/SOL, separated by venue and market type |
| `GET /evidence/{symbol}` | six independent family aggregates, component provenance, empirical-dependence gate, quality and freshness |
| `GET /decisions` | recent `LONG`/`SHORT`/`WAIT`/`ARBITRAGE` decisions, rankings, costs, capacity, gates and reason codes |
| `GET /research` | hypothesis ledger, OOS/walk-forward/Monte Carlo/multiple-testing results, promotion state and negative findings |
| `GET /shadow` | immutable SHADOW observations, no-order/risk status, virtual exposure, degradation state and audit checksum |
| `GET /paper` | simulated order/fill/position reconciliation, partial fills, cost decomposition and ambiguous/orphaned state |
| `GET /risk` | exposure limits, drawdown guards, daily loss, kill-switch state and rejection reasons; no mutation endpoint |
| `GET /audit` | paginated lineage and decision audit index with checksums and artifact references |

`/paper` remains disabled until PAPER is explicitly deployed. A disabled
capability returns a typed `NOT_DEPLOYED` state, not HTTP success containing
empty fake activity.

## 4. Operator views

### 4.1 Overview

- overall readiness and the strongest blocking reason;
- BTC/ETH/SOL cards with current action, confidence range, conservative edge
  after costs, freshness, and regime;
- collector/data-quality/risk/SHADOW/PAPER health summary;
- active alerts and runbook links;
- an unmistakable `LIVE DISABLED` banner until a separately authorized phase.

### 4.2 Market intelligence

For each symbol and venue, show:

- trades, bid/ask, spread, L2 depth and book integrity;
- ATAS-like outputs: CVD, delta, footprint, diagonal/stacked imbalance,
  absorption, exhaustion, sweeps, Volume Profile, POC, VAH/VAL, VWAP and
  AVWAP;
- independent Market Cipher-like outputs: momentum, money flow and causal
  divergences, with no proprietary formula or copied code;
- derivatives: OI, funding, basis, liquidations and crowding;
- options: IV, 25-delta skew, term structure and surface freshness;
- cross-venue and cross-market differences;
- multidomain regime and historical analog distribution.

The UI must label raw measurements, derived features, research-stage scores,
and promoted evidence differently. A chart is not evidence of an edge unless
the linked research report passed its gates.

### 4.3 Decision explanation

Each decision view shows:

- action and all reason codes, including why `WAIT` won;
- decision time, data cutoff, maximum source time and production lag;
- family-level score, confidence, quality, components and empirical
  dependence result;
- no double counting of indicators from the same family;
- expected gross value, fee/spread/slippage/latency/funding assumptions,
  conservative net range and capacity;
- Directional/Neutral candidate rankings and Meta allocation decision;
- research approval, promotion state, portfolio gates and kill switches;
- immutable SHADOW/PAPER artifact and audit references when present.

## 5. Security and deployment

- bind privately by default; external exposure requires TLS and authenticated
  reverse proxy access;
- authorize only read methods (`GET`/`HEAD`) in the first release;
- redact secrets, account identifiers, webhook URLs, raw authorization
  headers, and exchange credentials from all payloads and logs;
- apply response-size, rate, and query-window limits;
- render stored text as text, never trusted HTML;
- access logs contain actor, endpoint, time, status, and correlation id but no
  sensitive payload;
- the UI process receives read-only datasets or published snapshots, never
  write access to collector, research, risk, or execution state;
- failure of the UI cannot restart or block collectors or trading runtimes.

## 6. Performance and retention

- overview p95 response time: at most 500 ms from a local snapshot cache;
- detail endpoint p95: at most 2 s for a bounded query;
- default decision/audit page: 100 records, maximum 1,000;
- expensive historical charts use precomputed Gold aggregates;
- API snapshots publish atomically and retain at least the latest valid
  version during a failed refresh, marked stale with the failure reason;
- UI-specific cache files are disposable and never become the source of truth.

## 7. Rollout gates

1. Implement a typed snapshot publisher and API only after the real-time
   evidence-to-SHADOW path is stable and restart-tested.
2. Validate every endpoint against frozen fixtures and a running read-only
   SHADOW environment.
3. Add authentication, security headers, redaction tests, pagination and
   load tests before any public-network exposure.
4. Add the browser UI only after the API, alerts, and data-quality semantics
   are stable.
5. PAPER panels appear only after PAPER deployment; LIVE controls remain out
   of scope until separate explicit authorization.

## 8. Definition of Done

The first Operator UI release is done only when:

- all endpoints have versioned schemas and generated OpenAPI documentation;
- stale, missing, future, quarantined and fingerprint-mismatched inputs fail
  closed and have tests;
- the six-family/Meta/SHADOW explanation matches the immutable stored work;
- collector and dataset totals reconcile with manifests;
- SHADOW/PAPER/risk state reconciles with its durable stores and audit chain;
- security and redaction tests pass;
- p95 performance targets pass on the VPS-sized environment;
- restart, corrupt-snapshot and unavailable-source tests pass;
- Grafana/runbook links and alert correlation IDs are verified;
- CI is green and the draft PR records evidence and known limitations.
