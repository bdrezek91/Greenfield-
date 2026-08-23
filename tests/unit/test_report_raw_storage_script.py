"""scripts/report_raw_storage.py: CLI wiring for the read-only raw-lake
storage report."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from scripts.report_raw_storage import app
from src.data.raw_event import parse_bybit_message
from src.data.raw_store import AtomicRawWriter

runner = CliRunner()


def test_report_command_writes_a_summary_and_prints_totals(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": 1_700_000_000_000,
            "data": {
                "s": "BTCUSDT",
                "b": [["100", "1"]],
                "a": [["101", "1"]],
                "u": 1,
                "seq": 1,
            },
        },
        separators=(",", ":"),
    )
    event = parse_bybit_message(
        payload, receive_ts_ns=1_700_000_000_000_000_001, receive_sequence=1, connection_id="c"
    )
    AtomicRawWriter(tmp_path).write([event])

    result = runner.invoke(app, ["--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "parts=1" in result.output
    assert (tmp_path / "reports" / "raw_storage.json").is_file()
