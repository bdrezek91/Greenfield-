# Historical L2 acquisition gate

Status: **SOURCE IDENTIFIED, SAMPLE DOWNLOAD BLOCKED** (2026-08-28).

## Required first experiment

The first paid-data experiment remains deliberately narrow:

- venue: Bybit derivatives;
- instrument: BTC perpetual first, then ETH and SOL only after acceptance;
- duration: 30 days minimum, 90 days preferred;
- data: genuine incremental L2 with initial/reconnect snapshots, exchange and
  local timestamps, side, price, amount and snapshot/update identity;
- no synthetic DOM and no snapshot interpolation presented as raw history.

## Source audit

Bybit's official V5 orderbook REST endpoint returns a current snapshot. It is
useful for live resynchronization but is not a historical 30–90 day L2 API.
Official historical downloads advertise OHLCV/trades, not replayable L2.

Tardis.dev documents Bybit incremental L2 collected from exchange WebSockets,
with a snapshot at day start/reconnect followed by deltas. Its normalized CSV
schema includes exchange timestamp and local timestamp; the first day of each
month is documented as downloadable without an API key. Bybit derivatives
coverage begins in 2019 for inverse products and 2020 for linear products.

The exact free sample selected for the format/provenance proof was:

`https://datasets.tardis.dev/v1/bybit/incremental_book_L2/2020/01/01/BTCUSD.csv.gz`

Direct GET/Range attempts from both the Windows workstation and VPS returned
Cloudflare HTTP 403. An ordinary in-app browser attempt was also blocked by
the client. Therefore no bytes, checksum, row count, continuity result or
license acceptance is claimed. The source is identified, not accepted.

## Acceptance gates

Before purchasing or importing 30–90 days:

1. obtain one free daily file through a provider-supported download path;
2. retain the original gzip bytes and SHA-256 under a separate
   `source=tardis` Bronze namespace;
3. validate schema, monotonic local time and the first usable snapshot;
4. reconstruct the book message-atomically (all rows sharing local timestamp),
   rejecting updates before the first snapshot;
5. measure gaps, reconnect snapshots, crossed books, duplicate updates,
   depth-level distribution, compressed/uncompressed size and replay speed;
6. compare an overlapping interval with native Greenfield Bybit Bronze;
7. review subscription/licensing terms and obtain explicit user approval for
   the exact price before any purchase;
8. run a disk-capacity proof preserving Greenfield's hard free-space reserve.

Only after these gates pass may BTC expand to 30–90 days. ETH and SOL follow
using the same immutable evidence contract. Paid L2 is calibration/OOS input;
it does not itself authorize strategy promotion or trading.
