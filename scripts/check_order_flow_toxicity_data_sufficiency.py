"""Track B, step 1: verify the data-sufficiency gate preregistered in
docs/PREREGISTRATION_order_flow_toxicity_veto.md BEFORE building or running
anything else for the order-flow-toxicity-veto hypothesis.

Reuses src.data.normalized_store.discover_normalized_manifests (no new
storage-layer code) to find how many CONTIGUOUS (no-gap) UTC days of
Silver-tier `trades` data exist per symbol - the minimum viable input for
CVD/delta/footprint/VWAP, per the preregistration. The 20-contiguous-day
minimum itself is frozen in that document, not a parameter of this script -
this script only measures reality against it.

Usage:
    python scripts/check_order_flow_toxicity_data_sufficiency.py \
        --data-dir /opt/greenfield-v2/data \
        --report-path reports/order-flow-toxicity-veto/data_sufficiency.json
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import typer

from src.data.normalized_store import discover_normalized_manifests

app = typer.Typer(add_completion=False)

MINIMUM_CONTIGUOUS_DAYS = 20
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


@dataclass(frozen=True, slots=True)
class SymbolDataSufficiency:
    symbol: str
    available_dates: tuple[str, ...]
    longest_contiguous_run_days: int
    longest_contiguous_run_dates: tuple[str, ...]
    sufficient: bool


def _longest_contiguous_run(dates: list[str]) -> list[str]:
    if not dates:
        return []
    parsed = sorted({date.fromisoformat(d) for d in dates})
    best_run: list[date] = [parsed[0]]
    current_run: list[date] = [parsed[0]]
    # Deliberately mismatched-length consecutive-pair iteration (parsed[1:]
    # is always one shorter) - not a bug, see
    # tests/data_integrity/test_cross_session_raw_replay.py for the same
    # established pattern in this repo.
    for previous, current in zip(parsed, parsed[1:], strict=False):
        if current - previous == timedelta(days=1):
            current_run.append(current)
        else:
            current_run = [current]
        if len(current_run) > len(best_run):
            best_run = current_run
    return [d.isoformat() for d in best_run]


def check_symbol_sufficiency(
    data_dir: Path, symbol: str, *, minimum_contiguous_days: int
) -> SymbolDataSufficiency:
    manifests = discover_normalized_manifests(
        data_dir,
        exchange="bybit",
        market_type="linear",
        channel="trades",
        symbol=symbol,
    )
    available_dates = sorted({m.utc_date for m in manifests})
    longest_run = _longest_contiguous_run(available_dates)
    return SymbolDataSufficiency(
        symbol=symbol,
        available_dates=tuple(available_dates),
        longest_contiguous_run_days=len(longest_run),
        longest_contiguous_run_dates=tuple(longest_run),
        sufficient=len(longest_run) >= minimum_contiguous_days,
    )


@app.command()
def check(
    data_dir: str = typer.Option(..., help="Greenfield production data root."),
    report_path: str = typer.Option(
        "reports/order-flow-toxicity-veto/data_sufficiency.json",
        help="Where to write the manifest.",
    ),
    minimum_contiguous_days: int = typer.Option(
        MINIMUM_CONTIGUOUS_DAYS,
        hidden=True,
    ),
) -> None:
    if minimum_contiguous_days != MINIMUM_CONTIGUOUS_DAYS:
        raise typer.BadParameter(
            f"the preregistered threshold is frozen at {MINIMUM_CONTIGUOUS_DAYS} days"
        )
    root = Path(data_dir)
    per_symbol = {
        symbol: check_symbol_sufficiency(
            root, symbol, minimum_contiguous_days=minimum_contiguous_days
        )
        for symbol in SYMBOLS
    }
    verdict = (
        "DATA_SUFFICIENT_PROCEED"
        if all(s.sufficient for s in per_symbol.values())
        else "INSUFFICIENT_DATA"
    )
    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "preregistration": "docs/PREREGISTRATION_order_flow_toxicity_veto.md",
        "minimum_contiguous_days_per_symbol": minimum_contiguous_days,
        "per_symbol": {symbol: asdict(result) for symbol, result in per_symbol.items()},
        "verdict": verdict,
    }
    out_path = Path(report_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2))
    typer.echo(json.dumps(manifest, indent=2))
    if verdict != "DATA_SUFFICIENT_PROCEED":
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
