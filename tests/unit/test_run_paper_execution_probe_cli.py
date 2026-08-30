from click.utils import strip_ansi
from typer.testing import CliRunner

from scripts.run_paper_execution_probe import app


def test_execution_probe_cli_builds_with_decimal_values_as_strings() -> None:
    result = CliRunner().invoke(app, ["--help"], color=False)

    assert result.exit_code == 0
    output = strip_ansi(result.stdout)
    assert "--target-notional-quote" in output
    assert "--maximum-daily-loss-usd" in output
