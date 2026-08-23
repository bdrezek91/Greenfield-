"""scripts/collect_raw_deribit.py: config-driven startup and fail-closed
start-gate wiring, mirroring scripts/collect_raw_okx.py's behavior.

Only exercises paths that return before RawDeribitCollector.run_forever()
is reached - this is a startup-wiring test, not a network test.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from scripts.collect_raw_deribit import app

runner = CliRunner()


def test_invalid_instrument_is_rejected_before_any_connection(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("GREENFIELD_SOAK_ID", raising=False)
    monkeypatch.delenv("GREENFIELD_DEPLOY_COMMIT", raising=False)

    result = runner.invoke(
        app, ["--data-dir", str(tmp_path), "--instrument", "NOT-A-REAL-INSTRUMENT"]
    )

    assert result.exit_code != 0
    assert "instrument must be one of" in str(result.output)


def test_missing_soak_marker_refuses_to_start(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GREENFIELD_SOAK_ID", raising=False)
    monkeypatch.delenv("GREENFIELD_DEPLOY_COMMIT", raising=False)

    result = runner.invoke(app, ["--data-dir", str(tmp_path)])

    assert result.exit_code != 0
    assert "collector start gate refused connection" in str(result.output)
