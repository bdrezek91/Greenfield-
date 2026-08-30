# Bybit Demo PAPER runbook

This runbook is only for Bybit's virtual-funds Demo environment. It does not
authorize, configure, or expose a mainnet/LIVE execution path.

Every autonomous scan is also appended idempotently to
`data/state/demo-scalp/signals.sqlite3`. The journal retains the market price,
experimental action, Directional Engine result, Market-Cipher-like veto,
the three independent family scores and source timestamps, execution result,
and any Demo trade ID. It is evidence for later calibration; it does not turn
an experimental candidate into a promoted strategy.

After enough observations have matured, build a create-once calibration
report (a non-zero exit is expected until the sample and actionable signals
meet the gate):

```bash
uv run python scripts/validate_demo_signals.py \
  --journal-path data/state/demo-scalp/signals.sqlite3 \
  --report-path reports/demo-signal-validation-<UTC>.json
```

The default gate requires 1,000 non-forced observations with matured 1, 5,
and 10 minute outcomes and at least one naturally actionable signal. WAIT is
retained as a real decision; forced operator probes are excluded.

## Safety boundary

- The v2 gateway is pinned in code to `https://api-demo.bybit.com`; callers
  cannot supply another host, `testnet` flag, or `demo` flag.
- It reads only `BYBIT_DEMO_API_KEY` and `BYBIT_DEMO_API_SECRET` and refuses an
  environment containing `BYBIT_API_KEY`, `BYBIT_API_SECRET`, or
  `CONFIRM_LIVE_TRADING`.
- Preflight verifies a write-capable Demo key with exactly Contract `Order`
  and `Position`, the provider-mandatory Unified Trading bundles (`Spot`,
  `Derivatives`, `Options`) only in their exact expected trade-only shape,
  no asset/wallet/transfer permission, and a named IP restriction.
- Order submission additionally requires the exact, separate confirmation
  `GREENFIELD_DEMO_ORDER_CONFIRMATION=BYBIT_DEMO_ONLY`.
- The smoke order is a bounded BTC/ETH/SOL linear Limit/PostOnly order. BUY
  must be below the supplied reference and SELL above it. Maximum virtual
  notional is 250 USDT. It is canceled immediately and reconciled from Bybit
  executions/order state into a durable SQLite WAL.
- A stable request ID is mandatory. Reusing it after a disconnect queries and
  reconciles the same deterministic `orderLinkId`; it never resubmits an
  ambiguous order.

## One-time secret file on the VPS

From `~/greenfield-claude`:

```bash
umask 077
nano bybit-demo.env
chmod 600 bybit-demo.env
```

Contents:

```text
TRADING_MODE=PAPER
BYBIT_DEMO_API_KEY=<Demo key created while switched to Bybit Demo Trading>
BYBIT_DEMO_API_SECRET=<Demo secret>
```

Never paste either value into chat, GitHub, logs, screenshots, shell history,
or the repository. The filename ends in `.env` and is covered by `.gitignore`.

## Read-only preflight

After pulling the commit containing this runbook:

```bash
uv sync --extra data --extra dev
uv run python scripts/bybit_demo_preflight.py --env-file bybit-demo.env
```

This performs only API-key information, wallet, position, and open-order
queries. It prints a sanitized JSON report and never prints credentials. Exit
code `0` means the account, least-privilege permissions, and IP restriction
were verified. Exit code `2` is fail-closed; do not proceed to an order.

To inspect the current Demo equity without printing credentials, run:

```bash
uv run python scripts/bybit_demo_balance.py --env-file bybit-demo.env
```

Bybit Demo does not expose the account fee-rate endpoint. Verify the fees
actually charged on bounded maker/taker probes from their durable journal:

```bash
uv run python scripts/bybit_demo_fee_rates.py \
  --journal-path data/state/paper-execution-probe/journal.sqlite3
```

The output is sanitized and computes `fee / filled notional` per symbol/mode.
Research cost assumptions must remain at least as conservative as these
observed rates; a discrepancy blocks promotion rather than silently changing
a frozen backtest.

The output contains only total equity, wallet balance, and available balance
in USD. The autonomous sizing rule uses `total_equity_usd`; one trade may use
at most 1% of that value as margin.

If equity differs materially from wallet/available balance, inspect sanitized
nonzero exposure before any new order:

```bash
uv run python scripts/bybit_demo_exposure.py --env-file bybit-demo.env
```

This prints no credentials, but lists every nonzero USDT-linear position and
open order. Any pre-existing or unattributed exposure blocks the autonomous
service; it is never silently adopted or closed.

## Explicit place/cancel smoke test

Do this only after a green preflight and a deliberate operator decision.
First add the following line to `bybit-demo.env`:

```text
GREENFIELD_DEMO_ORDER_CONFIRMATION=BYBIT_DEMO_ONLY
```

Use a current observed reference price and a grid-valid passive price within
5%: below reference for BUY or above reference for SELL. Example shape only
(the prices are placeholders, not trading advice):

```bash
uv run python scripts/bybit_demo_smoke_order.py \
  --env-file bybit-demo.env \
  --request-id operator-smoke-001 \
  --symbol ETHUSDT \
  --side BUY \
  --notional-quote 30 \
  --reference-price <CURRENT_REFERENCE> \
  --limit-price <PASSIVE_PRICE_BELOW_REFERENCE>
```

Exit code `0` requires a terminal durable state (`CANCELED`, `FILLED`, or
`REJECTED`). Exit code `3` means Bybit has not yet confirmed a terminal state;
rerun the exact command with the **same** request ID. Never invent a new retry
ID. A fill is possible if the market reaches the passive Demo price before
cancellation; it affects virtual Demo funds only and is durably reconciled.

After the smoke test, remove the confirmation line. Keep `TRADING_MODE=PAPER`
and the credentials if further read-only checks are required.

## Explicit BTC 100 USDT / 100x round-trip

This is a separate infrastructure test requested by the operator. It uses
virtual Demo funds only. `100 USDT` means approximate **position notional**,
not 100 USDT margin multiplied by 100. It sets BTCUSDT one-way leverage to
100x, submits one Market BUY near 100 USDT notional, and then closes the exact
observed long position with a reduce-only Market SELL.

Safety properties:

- it requires both the generic Demo confirmation and a narrower round-trip
  confirmation;
- before entry it requires zero BTCUSDT open orders and a flat BTCUSDT Demo
  position;
- quantity is derived from public market metadata and must estimate between
  75 and 125 USDT (otherwise nothing is sent);
- intent is durably written before submission and mapped to deterministic
  `orderLinkId` values, so an ambiguous retry never sends the same leg twice;
- close attempts are always `reduceOnly`; completion requires both Bybit Demo
  and the durable PAPER ledger to report zero BTC position.
- if Bybit order history reports a fill before its executions endpoint exposes
  the fill rows, the coordinator treats that as a retryable feed lag and still
  flattens any authoritative long position with one durable reduce-only close;
  it never resends the ambiguous entry.

After a green read-only preflight, add these two exact lines to
`bybit-demo.env`:

```text
GREENFIELD_DEMO_ORDER_CONFIRMATION=BYBIT_DEMO_ONLY
GREENFIELD_DEMO_BTC_ROUND_TRIP_CONFIRMATION=BTC_100_USDT_100X_DEMO_ONLY
```

Run once with a unique, stable request ID:

```bash
uv run python scripts/bybit_demo_btc_round_trip.py \
  --env-file bybit-demo.env \
  --request-id btc-demo-20260824-001
```

Exit code `0` with `"phase": "COMPLETE"` proves that both orders were
reconciled and both positions are flat. Exit code `3` is intentionally
fail-closed: rerun the **exact same command and request ID** until the exchange
outcome becomes authoritative. Never change the request ID to retry an
unresolved run. Exit code `2` means stop and inspect the sanitized error; do
not invent a workaround. After `COMPLETE`, remove both confirmation lines.

### Verified operator evidence (2026-08-24)

The recovery-safe path completed against Bybit Demo with request ID
`btc-demo-20260824-001`: `0.001 BTC` Market BUY filled at `78,893.2`, the
matching `0.001 BTC` reduce-only Market SELL filled at `78,865.3`, leverage
was `100`, and both the exchange position and durable PAPER position finished
at exactly zero. Total reported Demo fees were approximately `0.08677 USDT`.
The submitted notional was approximately `78.9 USDT`, the closest permitted
BTC quantity step within the preregistered 75–125 USDT safety interval.

The first reconciliation attempts also exercised a real eventual-consistency
condition: order history exposed cumulative fill quantity before the execution
rows appeared. The stable request ID prevented a duplicate BUY; after the
execution feed caught up, the coordinator placed exactly one durable
reduce-only close and reached `COMPLETE`. No mainnet/LIVE order was involved.

## What this does not prove

A successful smoke test proves endpoint isolation, authentication, permission
shape, place/cancel mechanics, deterministic idempotency, and reconciliation.
It does not prove strategy edge, production readiness, multi-day stability,
or eligibility for LIVE/LIVE_SMALL. Promotion still follows the gates in
`GREENFIELD_V2_MASTER_PLAN.md`.

## Execution-quality probe (PAPER_EXECUTION_PROBE, disabled by default)

`scripts/run_paper_execution_probe.py` is not a strategy and has no edge
estimate. Its only purpose is to generate real Bybit Demo execution evidence
- maker fill probability, taker execution, spread paid/captured, slippage,
order latency, partial fills, adverse selection, and post-fill markouts at
+100/250/500ms and +1/2/5/10/30/60s - so a later, separate calibration job
can call `src.execution.calibration.compute_markout_calibration()` and
`compare_predicted_to_realized()` against real fills instead of only the
deterministic simulator's static assumptions. Every trade it opens is
durably tagged `EXECUTION_PROBE` (see `AutonomousTradeRecord.candidate_id`)
and journaled separately from any research signal, so a forced probe can
never be counted as a naturally occurring strategy observation.

It reuses, unmodified: `PybitBybitDemoGateway` (still hard-pinned to
`https://api-demo.bybit.com`), the durable `PaperOrderStore`/
`DemoOrderReconciler` order reconciliation, and `AutonomousDemoStateStore`
for the one-active-lifecycle invariant, daily order-count/cooldown/kill-
switch bookkeeping, and crash-safe phase recovery - pointed at its own
database directory (`data/state/paper-execution-probe/` by default),
entirely separate from any future qualified strategy's ledger.

Safety properties:

- disabled by default: requires **both**
  `GREENFIELD_DEMO_ORDER_CONFIRMATION=BYBIT_DEMO_ONLY` **and**
  `GREENFIELD_DEMO_EXECUTION_PROBE_CONFIRMATION=EXECUTION_EVIDENCE_ONLY` in
  the environment file before any order is submitted;
- virtual funds only, on the same Demo account as everything else in this
  runbook; fixed leverage of 1x (not the 100x used by a future strategy
  skeleton - the probe measures execution mechanics, not capital
  efficiency);
- a small, fixed, bounded USDT notional per order (default 30, hard cap 60),
  never a fraction of Demo equity; a non-configurable code-level ceiling
  (100 USDT) prevents the cap from being raised past what was reviewed here;
  if a symbol's exchange-minimum order size would exceed the cap, the probe
  refuses that symbol rather than silently oversizing;
- exactly one active probe lifecycle at a time, a strict daily order-count
  cap, a cooldown between entries, and an absolute Demo-USDT daily loss cap
  (not a fraction of the account's virtual equity) - all enforced by the
  same durable risk ledger and kill switch the rest of this runbook uses;
- every probe order is unconditionally reduce-only-flattened the instant any
  quantity fills - there is no stop-loss, take-profit, or holding period.
  The only reason a probe position exists at all is to observe one fill;
  markouts up to 60s are measured from public quotes with the position
  already flat, so real Demo exposure lasts seconds, not minutes;
  fail-closed at start: refuses to run if the account is not flat, and
  refuses to resubmit if a prior attempt under the same request ID reached a
  different outcome (rerun with a new `--request-id` instead);
- deterministic `orderLinkId`s and a crash-safe phase machine: a rerun with
  the **same** `--request-id` resumes the exact same probe instead of
  submitting a duplicate order, exactly like the smoke test and round-trip
  above.

A maker probe places a PostOnly order at the current best bid/ask; if it has
not filled within `--maker-fill-timeout-seconds` (default 20) it is
canceled, and any resulting zero/partial fill is recorded and flattened. A
taker probe places a Market order. Mode (MAKER/TAKER) and side (BUY/SELL)
alternate deterministically across the day's entries unless `--mode`/
`--side` is passed explicitly.

Run one probe cycle after a green preflight, with both confirmation lines
added to `bybit-demo.env`:

```bash
uv run python scripts/run_paper_execution_probe.py \\
  --request-id probe-$(date -u +%Y%m%dt%H%M%sz) \\
  --symbol ETHUSDT \\
  --env-file bybit-demo.env
```

Exit code `0` means the cycle reached a terminal, evidence-recording state
(`CLOSED`, `CLOSED_NO_FILL`) or a fail-closed `WAIT` (cooldown/daily
cap/kill switch - not an error). Exit code `3` means the outcome is still
unresolved; rerun the exact same command with the same `--request-id`,
exactly like the smoke test and round-trip above. Exit code `2` means stop
and inspect; a `SAFETY_HOLD` also exits `2` and requires manual review
before any further probe or strategy activity on this account.

Results land in `data/state/paper-execution-probe/journal.sqlite3`
(`ExecutionProbeJournal`), in exactly the `PaperOrderObservation`/
`TopOfBookQuote` shapes `src.execution.calibration` already defines. There is
currently no `validate_demo_signals.py`-style report generator for this
journal; build one the same way once enough probe samples exist, gated the
same way the opportunity-scan validator is gated on sample size before it
produces a calibration report.

After the probe, remove `GREENFIELD_DEMO_EXECUTION_PROBE_CONFIRMATION` (and
`GREENFIELD_DEMO_ORDER_CONFIRMATION`, if nothing else needs it armed) from
`bybit-demo.env`.

For a deliberately armed evidence-collection period, the reviewed units in
`ops/systemd/greenfield-execution-probe.{service,timer}` run one idempotent
probe every two hours. The wrapper rotates BTC/ETH/SOL by deterministic UTC
slot, reuses the same request ID if a persistent timer catches up after a
restart, keeps the existing 12-orders/day and 10-USDT/day-loss caps, and does
not expose command-line switches that enlarge the fixed 30-USDT probe. Install
the units only after the one-shot command above succeeds and the account is
flat. Disable the timer immediately on `SAFETY_HOLD` or unexpected exposure.

Audit collection progress without placing an order:

```bash
uv run python scripts/report_paper_execution_probe.py \
  --journal /home/ubuntu/greenfield-state/paper-execution-probe/journal.sqlite3 \
  --output /home/ubuntu/greenfield-state/paper-execution-probe/calibration-progress.json
```

The report separates every BTC/ETH/SOL × MAKER/TAKER bucket and remains
`COLLECTING` until all six have at least 100 observations. Thirty observations
per bucket are only an initial diagnostic checkpoint. Missing reference quotes
fail the join, and markouts are matched by the durable probe trade ID and exact
horizon label so a later probe cannot silently fill a missing earlier horizon.

## Autonomous opportunity scan (no orders yet)

`scripts/scan_bybit_demo_opportunities.py` now performs a public-mainnet data
scan for BTCUSDT, ETHUSDT, and SOLUSDT while keeping execution completely
disconnected. It combines exactly three independent families: trade-volume
auction location, recent aggressor order flow, and price/open-interest
derivatives confirmation. The original Market-Cipher-like momentum/money-flow
implementation is a veto only and is never counted as a fourth confirmation.

The command is intentionally pinned to `RESEARCH_CANDIDATE` with a zero edge
estimate, so it always remains fail-closed at `WAIT` even when the raw family
votes align. There is no command-line switch that can fabricate a promotion
state or expected return. A future automated Demo executor must obtain both
from durable Experiment Factory artifacts and a `PAPER_CHALLENGER` or
`PAPER_CHAMPION` registry state.

On the VPS, pass `--data-dir` to require the hybrid input path:

```bash
uv run python scripts/scan_bybit_demo_opportunities.py \
  --data-dir /srv/greenfield-data
```

This path merges local 5-minute history with current public candles and
replaces the short REST trade sample with verified immutable Bybit Bronze
trade events. It requires at least three distinct Bronze UTC dates, at least
300 trades, fresh final trade data, and valid part checksums; otherwise it
fails closed. L2 and liquidation Bronze are retained for later ATAS-like
feature validation but are not silently counted by this scanner yet.

The operator selected `100x` leverage and exactly `1%` of deployable Demo
capital as the maximum margin per trade. Deployable capital is the lower of
`totalEquity` and `totalAvailableBalance`, so non-deployable collateral or an
unrealized component cannot inflate the order. Quantity is rounded down to the
venue step and the rounded order may never exceed the 1% margin envelope.

The initial protective envelope is 20 bps stop, 30 bps take profit, 30 minute
maximum holding time, one open position, six entries per UTC day, 15 minute
cooldown, and a 1% daily loss guard. These constants are validated in code and
are Demo-only. This selection does not authorize LIVE or reuse of those limits
for real funds.

Autonomous lifecycle state is stored separately from exchange order/fill
reconciliation. `AutonomousDemoStateStore` records the observation before an
entry exists, binds deterministic entry and exit client-order IDs, permits one
active lifecycle across BTC/ETH/SOL, and retains `SAFETY_HOLD` across restart.
Its daily UTC ledger makes starting deployable capital immutable for the day,
counts entries atomically, persists cooldown and realized PnL, and activates a
durable kill switch when the daily loss envelope is reached.

# Retired strategy experiments and reusable Demo skeleton

The ATAS/MC v1 scalper and liquidation-fade v2 strategy have been removed.
There is no continuous Demo strategy service or Compose profile to start, and
there is no force-once path. Their historical outcomes remain documented in
the development ledger, but neither candidate is executable or promoted.

The reusable infrastructure remains:

- `scripts/bybit_demo_preflight.py`, `bybit_demo_balance.py` and
  `bybit_demo_exposure.py` for authenticated, read-only operator checks;
- `scripts/bybit_demo_btc_round_trip.py` for an explicitly confirmed bounded
  infrastructure test only;
- `PybitBybitDemoGateway`, durable order reconciliation, lifecycle state,
  partial-fill/restart recovery, reduce-only exits and risk/kill-switch code;
- `DemoStrategyExecutor` as a library skeleton. It has no runner, no signal
  source, no implicit risk configuration and cannot run in the background.

A future strategy must first pass the Research Factory gates, provide a
versioned evidence artifact and an explicit `AutonomousDemoRiskConfig`, then
receive a new adapter and disabled-by-default Compose profile in a reviewed
commit. Only that adapter may set:

```text
GREENFIELD_DEMO_STRATEGY_CONFIRMATION=CONTINUOUS_BYBIT_DEMO_STRATEGY_ONLY
```

The confirmation does nothing by itself because no continuous runner exists.
After independently proving the Demo account is flat, an unsubmitted
`SAFETY_HOLD` created by a future adapter can be cleared with
`scripts/clear_unsubmitted_demo_strategy_hold.py`. This repair path cannot
clear a trade that has any durable order identity or exchange exposure.

## Controlled recovery fault drill

The operational drill below does **not** submit an exchange order. It first
proves the real Bybit Demo account has no position and no open order, runs the
deterministic execution-feed-lag, restart, and partial-cancelled-exit scenarios
against isolated temporary stores, and then proves the real account is still
flat. The checkout must be clean so the immutable report identifies exactly
the code that was exercised.

```bash
uv run python scripts/capture_demo_fault_drill.py \
  --env-file bybit-demo.env \
  --repository-root . \
  --report-path reports/demo-fault-drills/demo-fault-$(date -u +%Y%m%dt%H%M%sz).json
```

The report is created exclusively and cannot overwrite earlier evidence. A
non-flat boundary, failed scenario, dirty checkout, invalid source commit, or
second use of the same report path fails closed. This drill proves recovery
plumbing only; it does not validate trading edge or authorize LIVE.
