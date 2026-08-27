# Daily Silver quality and catalog maintenance

This job turns the previous completed UTC day into deterministic Phase 2
evidence. It does not modify Bronze or Silver market data. It creates:

- the immutable daily Silver quality report and non-destructive quarantine
  overlays;
- one partition-scoped point-in-time catalog snapshot for every
  exchange/market pair present in that UTC partition;
- one immutable maintenance report binding all report and snapshot hashes to
  the exact clean Git commit.

The cutoff is always midnight immediately after `utc_date`. Therefore retries
for the same day and commit are byte-reproducible instead of changing with the
wall clock. The snapshot also carries the exact `utc_date`; it cannot silently
include an older partition that was outside this run's quality audit.

## Manual qualification

Run from the deployed, clean checkout after the previous UTC day has finished:

```bash
cd /path/to/greenfield
uv run python scripts/run_daily_data_maintenance.py \
  --data-dir /opt/greenfield-v2/data \
  --code-version "$(git rev-parse HEAD)"
```

The default date is yesterday in UTC. Use `--utc-date YYYY-MM-DD` only for an
explicit replay. Exit `0` means the day contained Silver partitions, every
partition passed fatal quality rules and catalog evidence was written. Exit
`1` is valid fail-closed evidence (empty or unqualified day). Exit `2` means
the run itself was unsafe or invalid. Existing evidence is never overwritten
with different bytes.

## VPS scheduling contract

Schedule this command once daily after the Silver materializer's completion
window. The scheduler must provide an absolute application checkout and data
root, run as the Greenfield service account and retain stdout/stderr in the
host journal. Do not schedule it from the active raw collector container.

Example timer policy (adapt paths and the service account to the target host):

```ini
[Timer]
OnCalendar=*-*-* 00:20:00 UTC
Persistent=true
RandomizedDelaySec=120
```

Before enabling a timer, run one manual day, confirm the maintenance report
under `maintenance/v1/daily/`, then execute the same date again and prove the
same `maintenance_id` is returned. Actual timer installation and at least one
observed scheduled execution remain operational acceptance evidence; adding
this runbook alone is not that proof.

## Deployment gotcha: `git` under a `User=root` unit

If the deployed checkout is owned by a non-root user (e.g. `ubuntu`) and the
service runs as `User=root`, `git rev-parse HEAD`/`git status` inside the
script will fail with "detected dubious ownership" under systemd's minimal
environment even though an interactive `sudo git ...` in the same session
looks clean — an interactive `sudo` session can inherit a different, already-
trusted git context that masks this. The script reports this identically to
a genuinely dirty checkout ("daily maintenance requires a clean checkout at
the exact code version"), so do not assume dirtiness without checking. Fix
once per host with root's own global config, not a repo-tracked file:

```bash
sudo env -i HOME=/root git config --global --add safe.directory /path/to/deployed/checkout
```

Reproduce/verify with `sudo env -i HOME=/root git -C /path/to/deployed/checkout status --porcelain`
before assuming the fix worked.
