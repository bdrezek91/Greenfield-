from __future__ import annotations

from pathlib import Path

from src.execution.live_preflight import (
    LiveRiskBounds,
    check_api_credentials,
    check_experiment_history,
    check_risk_config,
    check_trading_mode,
    run_preflight,
)
from src.execution.mode import LIVE_CONFIRMATION_ENV_VAR, LIVE_CONFIRMATION_VALUE
from src.risk.engine import RiskConfig

_LIVE_ENV = {"TRADING_MODE": "LIVE", LIVE_CONFIRMATION_ENV_VAR: LIVE_CONFIRMATION_VALUE}
_CONSERVATIVE_RISK = RiskConfig(
    risk_per_trade=0.01,
    max_portfolio_risk=0.05,
    max_daily_loss=0.03,
    max_drawdown=0.2,
    max_leverage=3.0,
)


class TestCheckTradingMode:
    def test_fails_when_not_live(self) -> None:
        result = check_trading_mode({"TRADING_MODE": "PAPER"})
        assert result.passed is False

    def test_fails_when_confirmation_missing(self) -> None:
        result = check_trading_mode({"TRADING_MODE": "LIVE"})
        assert result.passed is False

    def test_passes_when_live_and_confirmed(self) -> None:
        result = check_trading_mode(_LIVE_ENV)
        assert result.passed is True


class TestCheckApiCredentials:
    def test_fails_when_missing(self) -> None:
        assert check_api_credentials({}).passed is False

    def test_fails_when_blank(self) -> None:
        env = {"KRAKEN_API_KEY": "  ", "KRAKEN_API_SECRET": "x"}
        assert check_api_credentials(env).passed is False

    def test_passes_when_both_set(self) -> None:
        env = {"KRAKEN_API_KEY": "key", "KRAKEN_API_SECRET": "secret"}
        assert check_api_credentials(env).passed is True


class TestCheckRiskConfig:
    def test_passes_for_conservative_config(self) -> None:
        assert check_risk_config(_CONSERVATIVE_RISK).passed is True

    def test_fails_for_backtest_default_style_config(self) -> None:
        # Mirrors src.strategies.base.BenchmarkStrategyConfig's actual
        # backtest-oriented defaults - exactly the config this check exists
        # to catch someone from accidentally taking live.
        aggressive = RiskConfig(
            risk_per_trade=0.1,
            max_portfolio_risk=0.5,
            max_daily_loss=0.5,
            max_drawdown=0.5,
            max_leverage=10.0,
        )
        result = check_risk_config(aggressive)
        assert result.passed is False
        assert "risk_per_trade" in result.detail
        assert "max_leverage" in result.detail

    def test_respects_custom_bounds(self) -> None:
        tight_bounds = LiveRiskBounds(max_leverage=1.0)
        result = check_risk_config(_CONSERVATIVE_RISK, bounds=tight_bounds)
        assert result.passed is False
        assert "max_leverage" in result.detail

    def test_boundary_equal_to_bound_passes(self) -> None:
        bounds = LiveRiskBounds()
        at_bound = RiskConfig(
            risk_per_trade=bounds.max_risk_per_trade,
            max_portfolio_risk=bounds.max_portfolio_risk,
            max_daily_loss=bounds.max_daily_loss,
            max_drawdown=bounds.max_drawdown,
            max_leverage=bounds.max_leverage,
        )
        assert check_risk_config(at_bound, bounds).passed is True


class TestCheckExperimentHistory:
    def test_fails_when_file_missing(self, tmp_path: Path) -> None:
        result = check_experiment_history(tmp_path / "nope.jsonl")
        assert result.passed is False

    def test_fails_when_below_minimum(self, tmp_path: Path) -> None:
        path = tmp_path / "experiments.jsonl"
        path.write_text('{"experiment_id": "EXP-000001"}\n')
        result = check_experiment_history(path, min_experiments=2)
        assert result.passed is False

    def test_passes_when_enough_recorded(self, tmp_path: Path) -> None:
        path = tmp_path / "experiments.jsonl"
        path.write_text('{"a": 1}\n{"a": 2}\n')
        result = check_experiment_history(path, min_experiments=2)
        assert result.passed is True

    def test_ignores_blank_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "experiments.jsonl"
        path.write_text('{"a": 1}\n\n{"a": 2}\n\n')
        result = check_experiment_history(path, min_experiments=2)
        assert result.passed is True


class TestRunPreflight:
    def test_all_pass_when_everything_conservative(self, tmp_path: Path) -> None:
        experiments = tmp_path / "experiments.jsonl"
        experiments.write_text('{"a": 1}\n')
        env = {**_LIVE_ENV, "KRAKEN_API_KEY": "k", "KRAKEN_API_SECRET": "s"}
        report = run_preflight(env, _CONSERVATIVE_RISK, experiments)
        assert report.all_passed is True
        assert report.failures() == ()

    def test_reports_all_failures_not_just_the_first(self, tmp_path: Path) -> None:
        report = run_preflight({}, _CONSERVATIVE_RISK, tmp_path / "missing.jsonl")
        assert report.all_passed is False
        failed_names = {c.name for c in report.failures()}
        assert "trading_mode" in failed_names
        assert "api_credentials" in failed_names
        assert "experiment_history" in failed_names
