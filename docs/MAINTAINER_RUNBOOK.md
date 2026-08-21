# Greenfield Maintainer Runbook

Last updated: 2026-08-21

This runbook defines the reproducible development, validation, branch, and
recovery workflow. Product scope and phase gates remain controlled by
[GREENFIELD_V2_MASTER_PLAN.md](GREENFIELD_V2_MASTER_PLAN.md).

## 1. Canonical branches

| Branch | Purpose | Mutation policy |
|---|---|---|
| main | Legacy default branch | Do not overwrite directly |
| codex/stable-greenfield-v1-core | Preserved full v1 core at 5e53162 | Stabilization fixes through reviewed PRs only |
| codex/greenfield-market-intelligence-v2 | v2 integration branch | Merge reviewed phase and feature PRs |
| codex/phase-* | Short-lived implementation work | Delete only after merge and retention review |
| claude/* | Historical development record | Never rewrite or delete |

The audited ancestry is linear:

main → claude/ai-trading-greenfield-gi0gr4 →
claude/ai-trading-experiment-factory-2lfl0x →
claude/funding-aware-multi-horizon-trend.

The selected core is the last branch in that chain. No manual merge of the
three Claude branches is required.

## 2. Supported toolchain

- CPython: 3.11.x only; automation uses 3.11.15.
- Package manager: uv 0.12.1.
- Backtest engine: NautilusTrader 1.221.0.
- Dependency source of truth: pyproject.toml plus uv.lock.

Do not broaden the Python range or upgrade NautilusTrader in an unrelated PR.
Engine upgrades require a dedicated compatibility PR that runs the complete
test suite and explicitly checks Bybit adapter imports, FillModel construction,
backtest output, and paper-node construction.

## 3. Clean-checkout setup

From the repository root:

    uv sync --all-extras --locked
    uv run python --version
    uv run python -c "import nautilus_trader; print(nautilus_trader.__version__)"

Expected major environment:

- Python 3.11;
- NautilusTrader 1.221.0;
- no lockfile changes after sync.

If uv reports that the lockfile is stale, stop. Update pyproject.toml in the
same change, regenerate with uv lock using Python 3.11, inspect the dependency
diff, and commit both files together.

## 4. Required local validation

Fast checks:

    uv run ruff check .
    uv run mypy src
    uv run pytest -q tests/unit
    uv run pytest -q tests/data_integrity
    uv run pytest -q tests/lookahead
    uv run pytest -q tests/integration

Final check before push:

    uv run pytest -q --cov=src --cov-report=term-missing
    git ls-files -z | xargs -0 uv run detect-secrets-hook --baseline .secrets.baseline
    git diff --check

For Docker or runtime changes:

    docker compose config
    docker compose build
    docker compose run --rm tests

A platform-specific skip or failure must be understood and documented. It
must not be hidden by removing a test from CI.

## 5. Pull-request workflow

1. Start from the current v2 integration branch.
2. Create one codex-prefixed branch for one bounded phase or component.
3. Do not mix unrelated user changes into the branch.
4. Add only the intended paths to the commit.
5. Run the required validation.
6. Push the branch and open a draft PR to the v2 integration branch.
7. Record purpose, safety impact, test evidence, operational impact, and known
   limitations.
8. Keep the PR draft until CI is green and the phase exit evidence is present.

Changes to execution, risk limits, credentials, promotion gates, dataset
deletion, or LIVE behavior require explicit human review.

## 6. Documentation workflow

GREENFIELD_V2_MASTER_PLAN.md is the source of truth. Update it when:

- a target capability becomes verified current state;
- a phase is completed or reordered;
- a data contract or source changes;
- a promotion or risk gate changes;
- a known limitation is removed or discovered.

PROJECT_STATUS.md is a historical development log. Do not use an old phase
entry to override the master plan.

README.md is the short operator entry point. Keep setup commands, current
capabilities, and safety status accurate.

## 7. Data safety

- Raw market data is append-only.
- Never silently repair a sequence gap or crossed order book.
- Quarantine corrupt input and preserve its manifest.
- Never delete raw partitions through a broad or computed path.
- Validate a compacted replacement before removing source fragments.
- Store all textual manifests and reports as UTF-8.
- Never commit market-data archives, generated reports, or trained models.

Before a material data deletion, resolve and display the exact absolute target,
verify that it is inside the configured data root, and prefer a recoverable
move where practical.

## 8. Collector incident response

When a collector becomes stale or reports a sequence gap:

1. mark the affected stream unhealthy;
2. stop deriving normalized book state from the uncertain connection;
3. flush valid buffered raw messages;
4. record connection ID, last good sequence, timestamps, and reason;
5. reconnect with bounded backoff;
6. fetch a new snapshot;
7. resume deltas only after the venue-specific sequence contract is restored;
8. quarantine the uncertain interval;
9. alert and include the incident in the daily data-quality report.

Never bridge a gap by assuming the missing events did not matter.

## 9. Research and promotion safety

- Research workers may propose and evaluate; they may not approve capital.
- The frozen holdout is used once per family and protocol version.
- Negative and inconclusive results remain in the global trial ledger.
- No metric bypasses data-quality, cost, drawdown, stability, or
  multiple-testing gates.
- Correlated transformations of price count as one confirmation family.
- A missing or conflicting edge returns WAIT.

## 10. Execution and LIVE policy

The current system supports research, backtest, and paper modes. LIVE order
submission is intentionally unavailable.

Do not add or enable LIVE as an incidental part of another phase. It requires:

- a dedicated authorized PR;
- least-privilege keys with withdrawals disabled;
- fixed small capital and exposure limits;
- persistent reconciliation;
- tested kill switches and drawdown guards;
- incident runbook and operator sign-off;
- successful shadow and paper evidence.

No restart may clear exposure, loss, or kill-switch state.

## 11. Recovery from a bad dependency update

Symptoms include import-path errors, changed constructor arguments, native
engine termination, or backtest drift.

Recovery:

1. confirm the installed Python and package versions;
2. compare pyproject.toml and uv.lock with the last green commit;
3. reproduce from a clean virtual environment;
4. do not edit generated lock sections manually;
5. restore compatible constraints through a normal reviewed commit;
6. regenerate the lock with Python 3.11;
7. run adapter, engine, paper-node, and full-suite tests;
8. document any output drift.

Never force-reset a shared branch or delete historical branches to recover.

## 12. Phase completion evidence

A phase may be marked complete only when:

- every exit criterion in the master plan has a linked result;
- clean-checkout CI is green;
- Docker validation is green for runtime changes;
- operational metrics and recovery behavior exist for 24/7 components;
- documentation reflects current reality;
- known limits are explicit;
- the PR contains no unrelated files.
