# Bybit Demo PAPER runbook

This runbook is only for Bybit's virtual-funds Demo environment. It does not
authorize, configure, or expose a mainnet/LIVE execution path.

## Safety boundary

- The v2 gateway is pinned in code to `https://api-demo.bybit.com`; callers
  cannot supply another host, `testnet` flag, or `demo` flag.
- It reads only `BYBIT_DEMO_API_KEY` and `BYBIT_DEMO_API_SECRET` and refuses an
  environment containing `BYBIT_API_KEY`, `BYBIT_API_SECRET`, or
  `CONFIRM_LIVE_TRADING`.
- Preflight verifies a write-capable Demo key with Contract `Order` and
  `Position`, no permissions in other families, and a named IP restriction.
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

## What this does not prove

A successful smoke test proves endpoint isolation, authentication, permission
shape, place/cancel mechanics, deterministic idempotency, and reconciliation.
It does not prove strategy edge, production readiness, multi-day stability,
or eligibility for LIVE/LIVE_SMALL. Promotion still follows the gates in
`GREENFIELD_V2_MASTER_PLAN.md`.
