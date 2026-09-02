"""The catch-up runner never trades, processes live days, or ignores resource guards."""

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_bybit_processing_queue import RESERVE, SYMBOLS, build_jobs, check_resources


def test_queue_prioritizes_trades_for_all_symbols_before_l2(tmp_path: Path) -> None:
    jobs = build_jobs(date(2026, 1, 1), date(2026, 1, 2), tmp_path, tmp_path / "run", "abc")
    assert len(jobs) == 36
    assert [name for name, _ in jobs[:2]] == [
        "normalize-trades-BTCUSDT-2026-01-01",
        "gold-trades-BTCUSDT-2026-01-01",
    ]
    assert all("trades" in name for name, _ in jobs[:12])
    for _, args in jobs:
        assert args[0] in {
            "scripts/normalize_raw_bybit.py",
            "scripts/materialize_microstructure_gold.py",
            "scripts/materialize_l2_gold.py",
        }
        if "--minimum-free-bytes" in args:
            assert args[args.index("--minimum-free-bytes") + 1] == str(RESERVE)


def test_queue_rejects_open_day(tmp_path: Path) -> None:
    today = datetime.now(UTC).date()
    with pytest.raises(ValueError, match="closed"):
        build_jobs(today, today, tmp_path, tmp_path / "run", "abc")


@pytest.mark.parametrize("change", ["disk", "stale", "dropped", "restart", "queue", "sequence"])
def test_guard_stops_on_resource_or_collector_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    import time

    health = {
        symbol: {
            "status": "running",
            "connected": True,
            "sequence_continuity_verified": True,
            "heartbeat_ts_ns": time.time_ns(),
            "queue_depth": 0,
            "dropped_event_count": 0,
            "started_ts_ns": 1,
        }
        for symbol in SYMBOLS
    }
    initial = {symbol: dict(values) for symbol, values in health.items()}
    updates = {
        "stale": {"heartbeat_ts_ns": 1},
        "dropped": {"dropped_event_count": 1},
        "restart": {"started_ts_ns": 2},
        "queue": {"queue_depth": 5001},
        "sequence": {"sequence_continuity_verified": False},
    }
    health["BTCUSDT"].update(updates.get(change, {}))
    monkeypatch.setattr("scripts.run_bybit_processing_queue.read_health", lambda root: health)
    monkeypatch.setattr(
        "scripts.run_bybit_processing_queue.shutil.disk_usage",
        lambda root: SimpleNamespace(free=RESERVE if change == "disk" else RESERVE + 1),
    )
    with pytest.raises(RuntimeError, match="guard"):
        check_resources(tmp_path, initial)
