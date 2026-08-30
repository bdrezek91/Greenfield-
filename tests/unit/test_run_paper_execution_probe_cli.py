from typer.testing import CliRunner

from scripts.run_paper_execution_probe import app


def test_execution_probe_cli_builds_with_decimal_values_as_strings() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "--target-notional-quote" in result.stdout
    assert "--maximum-daily-loss-usd" in result.stdout
