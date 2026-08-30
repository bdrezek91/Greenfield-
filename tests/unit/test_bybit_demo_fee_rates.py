from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.bybit_demo_fee_rates import audit_observed_fee_rates


def _journal(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE execution_probe_orders (
            order_id TEXT,
            probe_mode TEXT,
            symbol TEXT,
            filled_price REAL,
            filled_quantity REAL,
            fee_cost_quote REAL,
            rejected INTEGER,
            recorded_at_utc TEXT
        )
        """
    )
    return connection


def test_audit_reports_exact_realized_fee_bps_by_symbol_and_mode(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    with _journal(path) as connection:
        connection.executemany(
            "INSERT INTO execution_probe_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("1", "MAKER", "ETHUSDT", 2500, 0.01, 0.005, 0, "2026-01-01"),
                ("2", "TAKER", "SOLUSDT", 100, 0.2, 0.011, 0, "2026-01-02"),
                ("3", "TAKER", "SOLUSDT", 110, 0.2, 0.0121, 0, "2026-01-03"),
                ("4", "MAKER", "BTCUSDT", 100000, 0, 0, 1, "2026-01-04"),
            ],
        )

    report = audit_observed_fee_rates(path)

    assert report["promotion_allowed"] is False
    assert report["buckets"] == [
        {
            "symbol": "ETHUSDT",
            "mode": "MAKER",
            "observation_count": 1,
            "mean_fee_bps": "2.0000",
            "minimum_fee_bps": "2.0000",
            "maximum_fee_bps": "2.0000",
        },
        {
            "symbol": "SOLUSDT",
            "mode": "TAKER",
            "observation_count": 2,
            "mean_fee_bps": "5.50000",
            "minimum_fee_bps": "5.50000",
            "maximum_fee_bps": "5.50000",
        },
    ]


def test_audit_fails_closed_without_filled_observations(tmp_path: Path) -> None:
    path = tmp_path / "journal.sqlite3"
    with _journal(path):
        pass

    with pytest.raises(ValueError, match="no filled fee observations"):
        audit_observed_fee_rates(path)
