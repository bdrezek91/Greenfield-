# Binance public archive backfill

## Purpose

This path captures provider-original, checksum-verified Binance archives for
BTCUSDT, ETHUSDT and SOLUSDT without claiming that candles are a substitute
for tick trades or historical L2.  It covers:

- spot and USD-M futures `trades` and `aggTrades`;
- USD-M funding-rate history;
- 1-minute mark, index and premium-index price series;
- daily USD-M `metrics` archives, which include historical open-interest and
  positioning statistics when Binance publishes the requested date.

ZIP files and their manifests are immutable Bronze inputs under
`external/binance-public-data/`.  They are not committed to Git.

## Safety model

The script defaults to inventory only.  Before execution it:

1. probes every exact HTTPS archive URL;
2. records missing files instead of fabricating coverage;
3. calculates compressed download size;
4. applies both a per-run byte budget and a hard free-space reserve;
5. downloads through a `.part` file;
6. validates Binance's official `.CHECKSUM` SHA-256 before atomic rename;
7. writes a source URL, checksum, size and retrieval-time manifest;
8. verifies and reuses an existing archive rather than downloading it again.

The default reserve is 5 GiB, matching the live collector runtime floor. The
verified month-rotation workflow must run before another month if the measured
download + Silver + Gold projection would cross that floor. This lower reserve
was explicitly accepted for the dedicated production data volume on
2026-08-30; it is not permission to fill the system volume.

## Commands

Inventory one closed month without downloading:

```bash
uv run python scripts/backfill_binance_public_archive.py \
  --data-dir /opt/greenfield-v2/data \
  --start-period 2026-07 \
  --end-period 2026-07
```

Download a bounded recent futures funding batch:

```bash
uv run python scripts/backfill_binance_public_archive.py \
  --data-dir /opt/greenfield-v2/data \
  --market futures/um \
  --dataset fundingRate \
  --budget-gib 1 \
  --execute
```

Download a bounded recent tick batch only after reviewing the inventory:

```bash
uv run python scripts/backfill_binance_public_archive.py \
  --data-dir /opt/greenfield-v2/data \
  --dataset trades \
  --start-period 2026-07 \
  --end-period 2026-07 \
  --budget-gib 3 \
  --minimum-free-gib 5 \
  --execute
```

## Capacity evidence and next boundary

At the 2026-08-28 live probe, the 24 archives for one recent closed month
(spot/futures trades and aggTrades plus funding and mark/index/premium series,
BTC/ETH/SOL) totalled about 5.18 GB compressed.  The production data volume
had only about 47 GB free.  Consequently, a multi-year full tick mirror does
not fit safely on the current VPS.

The next data cycle must add a retention/off-host-object-storage policy before
broad execution. The streaming normalizer is available for trade archives:

```bash
uv run python scripts/normalize_binance_trade_archives.py \
  --data-dir /opt/greenfield-v2/data \
  --minimum-free-gib 5
```

It writes deterministic Silver Parquet with UTC timestamps, aggressor-signed
quantity and source/output checksums. Historical incremental L2 remains a
separate paid-provider experiment; neither this archive nor ATAS is allowed to
masquerade as historical L2.
