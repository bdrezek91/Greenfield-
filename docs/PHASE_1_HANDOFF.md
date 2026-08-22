# Greenfield v2 — Phase 1 checkpoint and handoff

Checkpoint date: 2026-08-22

This document is the concise operational handoff for continuing Phase 1. The
controlling product and architecture source of truth remains
[`GREENFIELD_V2_MASTER_PLAN.md`](GREENFIELD_V2_MASTER_PLAN.md). If this
checkpoint becomes stale, update both documents in the same pull request.

## Current Git state

- Development branch: `codex/phase-1-raw-collector-foundation`
- Last fully synchronized VPS commit before this documentation cycle:
  `c6f6fe559d7086390d297f721190ebb821240480`. Deployment reports and
  `git rev-parse HEAD` on the host are authoritative after subsequent cycles.
- Draft pull request: <https://github.com/bdrezek91/Greenfield-/pull/4>
- Default branch `main` and all original Claude branches remain untouched.
- The preserved v1 core and v2 planning branches remain separate.
- GitHub Actions run 120 passed all four jobs at the preceding checkpoint.
- The local full suite passed 736 tests at the preceding checkpoint.
- Real-money LIVE order submission remains disabled.

## What has been completed

### Repository and reproducibility

- Audited `main` and the three requested Claude branches without deleting or
  rewriting any history.
- Identified `claude/funding-aware-multi-horizon-trend` as the most complete
  original core and preserved it as the canonical v1 baseline.
- Established separate branches for the stable core, the v2 plan, Phase 0, and
  the Phase 1 collector implementation.
- Pinned CPython 3.11.15, uv 0.12.1, NautilusTrader 1.221.0, and the locked
  dependency graph across local, CI, and Docker environments.
- Added deterministic CI, linting, type checking, secret scanning, test-image
  verification, source-revision provenance, and a smaller collector runtime
  image.

### Phase 1 implementation

- Added a versioned raw event envelope with exact public WebSocket text,
  exchange/receive timestamps, sequence metadata, and provenance.
- Added atomic immutable Parquet parts, checksummed manifests, collision-safe
  writes, strict replay, deterministic L2/ticker reconstruction, and
  non-destructive compaction.
- Added isolated supervised collectors for BTC, ETH, and SOL. SOL remains in
  the medium risk tier; this does not weaken raw-data collection requirements.
- Added health history and Prometheus metrics for freshness, lag, gaps,
  reconnects, drops, queue pressure, storage, and process state.
- Added a 5 GiB hard runtime storage reserve that fails closed before
  subscription and during collection, drains the queue, and exposes a
  dedicated critical alert.
- Added a fail-closed seven-day capacity forecast based on raw bytes measured
  by a finalized, drained, lossless BTC/ETH/SOL sample. It applies a 4x burst
  factor and retains the 5 GiB runtime reserve. Marker schema v2 binds its
  SHA-256, deployed commit and target filesystem, then rechecks current free
  bytes; the final evidence bundle and acceptance gate verify the same report.
- Added version-pinned Prometheus, Alertmanager, Grafana, node-exporter, and a
  durable vendor-neutral alert receiver, bound to loopback by default.
- Added the formal target-host preflight, immutable soak-session marker,
  strict acceptance gate, recovery-drill reports, incident reconciliation,
  correlated off-host alert evidence, and a content-addressed evidence bundle.
- A public Bybit smoke test captured and deterministically replayed 1,276
  messages in about 12 seconds with no drops or sequence uncertainties.

### VPS checkpoint

- Created an isolated checkout at `/opt/greenfield-v2` on the exact clean
  commit above.
- Installed the locked Python 3.11 runtime and verified Docker/Compose.
- Mounted the dedicated 100 GB OVH volume at `/opt/greenfield-v2/data`, the
  Compose-default Greenfield data path, with about 93 GiB initially free.
- Verified atomic write, fsync, rename, read, and delete semantics there.
- Verified Bybit public DNS, TLS, and WebSocket connectivity and clock skew
  below the one-second limit.
- Safely rebooted the host onto `6.8.0-138-generic`; the pending-reboot flag is
  gone and Docker recovered.
- Confirmed that every existing Multiplekser container returned running, with
  all configured health checks healthy. Greenfield did not stop, start,
  reconfigure, prune, or otherwise modify that protected workload.
- The historical unrelated `microstructure` container has `restart=no` and
  therefore remained stopped after the host reboot. It was not restarted.
- No Greenfield v2 collector, monitoring stack, or seven-day soak is currently
  running.

The post-reboot report is stored on the VPS at
`/opt/greenfield-v2/reports/phase1_vps_preflight_blocked_post_reboot.json`.

## What is required now

Only one preflight blocker remains:

1. **Off-host alert delivery:** configure `ALERT_FORWARD_URL` as an absolute
   HTTPS endpoint controlled by the operator. A synthetic alert must be proven
   end to end and its external receipt retained.

The operator explicitly accepted a 90 GiB minimum for the dedicated volume.
This is a start gate, not a fixed expected file size. The smoke rate was about
106 events/second, or roughly 64 million events over seven days before
volatility bursts. Storage alerts and the fail-closed acceptance checks remain
mandatory because the reduced margin must never cause silent data loss or
impact another workload.

The preserved 12.82-second lossless sample projects 19,484,685,792 bytes over
seven days at its measured rate. With the mandatory 4x stress factor and 5 GiB
reserve, the forecast requires 83,307,452,288 bytes (about 77.59 GiB). Run
`scripts/forecast_phase1_capacity.py` against the actual mounted data path
before starting; this planning forecast does not replace the seven-day soak.

Do not use `docker system prune`, delete unrelated data, or touch the
Multiplekser/Dampol containers, images, volumes, files, networks, or
configuration to satisfy the capacity requirement.

## Continuation order

1. Configure the external HTTPS alert destination without committing its
   secret or URL if it is sensitive.
2. Rerun `scripts/preflight_phase1_vps.py` at the exact clean deployed commit.
   Continue only when it exits zero.
3. Run the capacity forecast against the actual data filesystem and retain its
   JSON report; continue only when it exits zero.
4. Create the immutable soak-session marker from the fresh preflight and
   capacity reports; this begins the measured seven-day window.
5. Immediately start the isolated `greenfield-v2` monitoring and BTC/ETH/SOL
   collector services using the documented Compose project name and data path.
6. During that same session perform graceful SIGTERM, process restart, VPS
   reboot, bounded disk-backlog, and verified storage-restore drills. The
   maintenance reboot recorded above does not count as an in-session drill.
7. Prove synthetic off-host alert delivery, retain correlated evidence, audit
   the soak, run strict replay and manifest verification, build the evidence
   bundle, and obtain explicit operator approval.
8. Only after the Phase 1 acceptance gate passes may Phase 2 data-quality and
   normalized-lake work begin.

## Safety boundaries for whoever continues

- Work through a feature branch and draft PR; never overwrite `main`.
- Preserve all existing branches and unrelated user changes.
- Treat Multiplekser/Dampol as protected production infrastructure.
- Keep Greenfield isolated under Compose project `greenfield-v2` and the
  dedicated checkout/data paths.
- Do not start LIVE or use real capital. PAPER/SHADOW/LIVE_SMALL remain later,
  separately gated phases.
- Do not add ATAS-like/order-flow, Market Cipher-like, ML, or new strategy work
  before the owned raw dataset passes Phase 1. These remain planned features,
  and no proprietary ATAS or Market Cipher code or formulas may be copied.
- Never claim Phase 1 complete without the full seven-day evidence and every
  fail-closed acceptance check passing.
