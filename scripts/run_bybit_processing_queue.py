"""Serial closed-day Bybit processing; stop safely on unhealthy collectors or low disk."""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SYMBOLS = {"BTCUSDT": "0.1", "ETHUSDT": "0.01", "SOLUSDT": "0.01"}
RESERVE = 6 * 1024**3  # One GiB headroom above the operator's five-GiB hard floor.


def build_jobs(
    first: date, last: date, root: Path, run_dir: Path, code_version: str
) -> list[tuple[str, list[str]]]:
    if first > last or last >= datetime.now(UTC).date():
        raise ValueError("only a non-empty range of closed UTC dates is allowed")
    days = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    jobs = []
    # Finish trade features for the entire range before the heavier L2 expansion.
    for channel in ("trades", "liquidations", "ticker", "orderbook"):
        for day in days:
            for symbol, tick in SYMBOLS.items():
                name = f"normalize-{channel}-{symbol}-{day}"
                jobs.append(
                    (
                        name,
                        [
                            "scripts/normalize_raw_bybit.py",
                            "--source-data-dir",
                            str(root),
                            "--output-data-dir",
                            str(root),
                            "--exchange",
                            "bybit",
                            "--market-type",
                            "linear",
                            "--symbol",
                            symbol,
                            "--channel",
                            channel,
                            "--utc-date",
                            day,
                            "--minimum-free-bytes",
                            str(RESERVE),
                            "--report-path",
                            str(run_dir / f"{name}.json"),
                        ],
                    )
                )
                if channel not in ("trades", "orderbook"):
                    continue
                script = (
                    "scripts/materialize_microstructure_gold.py"
                    if channel == "trades"
                    else "scripts/materialize_l2_gold.py"
                )
                cutoff = (date.fromisoformat(day) + timedelta(days=1)).isoformat() + "T00:00:00Z"
                args = [
                    script,
                    "--data-dir",
                    str(root),
                    "--exchange",
                    "bybit",
                    "--market-type",
                    "linear",
                    "--symbol",
                    symbol,
                    "--utc-date",
                    day,
                    "--as-of",
                    cutoff,
                    "--code-version",
                    code_version,
                ]
                if channel == "trades":
                    args += ["--price-tick", tick]
                jobs.append((f"gold-{channel}-{symbol}-{day}", args))
    return jobs


def read_health(root: Path) -> dict[str, dict]:
    return {
        symbol: json.loads((root / "health" / f"bybit-linear-{symbol.lower()}.json").read_text())
        for symbol in SYMBOLS
    }


def check_resources(root: Path, initial: dict[str, dict]) -> None:
    if shutil.disk_usage(root).free <= RESERVE:
        raise RuntimeError("disk guard: free space reached six-GiB processing reserve")
    for symbol, health in read_health(root).items():
        age = (time.time_ns() - health["heartbeat_ts_ns"]) / 1e9
        if (
            not health["connected"]
            or health["status"] != "running"
            or not health["sequence_continuity_verified"]
            or not -5 <= age <= 120
            or health["queue_depth"] > 5000
            or health["dropped_event_count"] > initial[symbol]["dropped_event_count"]
            or health["started_ts_ns"] != initial[symbol]["started_ts_ns"]
        ):
            raise RuntimeError(f"collector guard: {symbol} needs operational review")


def run_job(args: list[str], log_path: Path, root: Path, initial: dict[str, dict]) -> None:
    check_resources(root, initial)
    with log_path.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, *args],
            cwd=REPO,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            while True:
                try:
                    code = process.wait(timeout=10)
                    break
                except subprocess.TimeoutExpired:
                    check_resources(root, initial)
            if code:
                raise RuntimeError(f"processing failed with exit {code}; see {log_path}")
            if "--report-path" in args:
                report = json.loads(Path(args[args.index("--report-path") + 1]).read_text())
                if report["source_part_count"] == 0:
                    raise RuntimeError("empty Bronze selection; no completion claim allowed")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-date", type=date.fromisoformat, required=True)
    parser.add_argument("--last-date", type=date.fromisoformat, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--code-version", required=True)
    args = parser.parse_args()
    root, run_dir = args.data_dir.resolve(), args.run_dir.resolve()
    if not root.is_mount() or not run_dir.is_relative_to(root) or run_dir == root:
        raise ValueError("data root must be a mounted volume; run directory must be its child")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True)
    if head != args.code_version or dirty.strip():
        raise ValueError("processing requires a clean checkout pinned to code-version")
    jobs = build_jobs(args.first_date, args.last_date, root, run_dir, head)
    initial = read_health(root)
    check_resources(root, initial)
    run_dir.mkdir(parents=True, exist_ok=False)
    state: dict = {
        "code_version": head,
        "jobs": jobs,
        "completed": [],
        "state": "RUNNING",
        "promotion_allowed": False,
        "oos_ready": False,
    }

    def save() -> None:
        state["updated_at"] = datetime.now(UTC).isoformat()
        temp = run_dir / "status.tmp"
        temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        temp.replace(run_dir / "status.json")

    def stop(signum: int, frame: object) -> None:
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGTERM, stop)
    save()
    try:
        for name, command in jobs:
            state["active"] = name
            save()
            print(f"START {name}", flush=True)
            run_job(command, run_dir / f"{name}.log", root, initial)
            state["completed"].append(name)
            print(f"COMPLETE {name}", flush=True)
        state["state"] = "PROCESSED_PENDING_COVERAGE_AUDIT"
        state["active"] = None
    except (Exception, KeyboardInterrupt) as exc:
        state["state"] = "STOPPED_REQUIRES_REVIEW"
        state["error"] = str(exc)
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
