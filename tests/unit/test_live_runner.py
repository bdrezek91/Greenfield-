from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.backtesting.instruments import build_crypto_perpetual, load_instrument_specs
from src.execution.adapter import Fill
from src.execution.intent import OrderIntent
from src.execution.live_runner import LiveBar, LiveRunner, LiveRunnerConfig
from src.risk.engine import RiskConfig, RiskEngine


class FakeAdapter:
    def __init__(self) -> None:
        self.submitted: list[OrderIntent] = []
        self.reject_next = False

    def submit(self, intent: OrderIntent) -> Fill:
        self.submitted.append(intent)
        if self.reject_next:
            self.reject_next = False
            return Fill(
                intent=intent,
                filled_price=0.0,
                filled_quantity=0.0,
                filled_at=intent.created_at,
                rejected=True,
                reject_reason="simulated rejection",
            )
        return Fill(
            intent=intent,
            filled_price=intent.reference_price,
            filled_quantity=intent.quantity,
            filled_at=intent.created_at,
        )


def _instrument():
    specs = load_instrument_specs()
    return build_crypto_perpetual("BTCUSD", specs)


def _runner(
    adapter: FakeAdapter, risk_config: RiskConfig | None = None, **config_kwargs
) -> LiveRunner:
    config = LiveRunnerConfig(symbol="BTCUSD", **config_kwargs)
    risk_engine = RiskEngine(
        risk_config or RiskConfig(risk_per_trade=0.1, max_portfolio_risk=0.5)
    )
    return LiveRunner(
        config=config,
        instrument=_instrument(),
        risk_engine=risk_engine,
        execution_adapter=adapter,
        equity_fn=lambda: 100_000.0,
    )


def _bars(closes: list[float], start: datetime | None = None) -> list[LiveBar]:
    start = start or datetime(2024, 1, 1, tzinfo=UTC)
    return [LiveBar(timestamp=start + timedelta(hours=i), close=c) for i, c in enumerate(closes)]


# lookback=1 means momentum_signal evaluates from the second bar onward,
# comparing only the two most recent closes - deterministic and easy to
# reason about by hand, unlike a longer lookback where a sliding window
# can re-trigger entries unpredictably across many bars.
_LOOKBACK_1_KWARGS = {"momentum_lookback_bars": 1, "momentum_threshold": 0.01}


class TestLiveRunnerEntry:
    def test_stays_flat_below_momentum_threshold(self) -> None:
        adapter = FakeAdapter()
        runner = _runner(adapter, **_LOOKBACK_1_KWARGS)
        runner.run(_bars([100.0, 100.05]))  # 0.05% change, under the 1% threshold
        assert runner.is_flat
        assert adapter.submitted == []

    def test_enters_long_above_threshold(self) -> None:
        adapter = FakeAdapter()
        runner = _runner(adapter, **_LOOKBACK_1_KWARGS)
        runner.run(_bars([100.0, 105.0]))  # 5% up
        assert not runner.is_flat
        assert len(adapter.submitted) == 1
        assert adapter.submitted[0].side.value == "BUY"

    def test_enters_short_below_negative_threshold(self) -> None:
        adapter = FakeAdapter()
        runner = _runner(adapter, **_LOOKBACK_1_KWARGS)
        runner.run(_bars([100.0, 95.0]))  # 5% down
        assert not runner.is_flat
        assert adapter.submitted[0].side.value == "SELL"

    def test_rejected_entry_leaves_runner_flat(self) -> None:
        adapter = FakeAdapter()
        adapter.reject_next = True
        runner = _runner(adapter, **_LOOKBACK_1_KWARGS)
        runner.run(_bars([100.0, 105.0]))  # the only signal in this run gets rejected
        assert runner.is_flat
        assert len(adapter.submitted) == 1


class TestLiveRunnerExit:
    def test_exits_after_holding_period(self) -> None:
        adapter = FakeAdapter()
        runner = _runner(adapter, holding_period_bars=1, **_LOOKBACK_1_KWARGS)
        # Enter BUY at bar 1 (5% up), exit exactly one bar later at bar 2.
        runner.run(_bars([100.0, 105.0, 110.0]))
        assert runner.is_flat
        assert len(adapter.submitted) == 2
        assert adapter.submitted[0].side.value == "BUY"
        assert adapter.submitted[1].side.value == "SELL"  # opposite of the entry

    def test_no_new_entry_while_in_position(self) -> None:
        adapter = FakeAdapter()
        runner = _runner(adapter, holding_period_bars=100, **_LOOKBACK_1_KWARGS)
        runner.run(_bars([100.0, 105.0, 110.0, 115.0, 120.0]))
        assert not runner.is_flat
        assert len(adapter.submitted) == 1  # never re-entered while still holding


class TestLiveRunnerFillTracking:
    def test_records_entry_and_exit_in_fill_tracker(self) -> None:
        adapter = FakeAdapter()
        runner = _runner(adapter, holding_period_bars=1, **_LOOKBACK_1_KWARGS)
        runner.run(_bars([100.0, 105.0, 110.0]))
        summary = runner.tracker.summary()
        assert summary.n_intents == 2
        assert summary.n_rejected == 0


class TestLiveRunnerRiskEngineIntegration:
    def test_realized_pnl_flows_into_risk_engine_daily_loss(self) -> None:
        adapter = FakeAdapter()
        # A tiny max_daily_loss so a single bad round trip is enough to
        # block further entries for the rest of that UTC day.
        runner = _runner(
            adapter,
            risk_config=RiskConfig(
                risk_per_trade=0.1, max_portfolio_risk=0.5, max_daily_loss=0.001
            ),
            holding_period_bars=1,
            **_LOOKBACK_1_KWARGS,
        )
        # Enter BUY at 105, forced to exit one bar later at 50 - a large loss.
        # Then, still the same day, a fresh momentum signal (50 -> 55, then
        # 55 -> 200) tries to re-enter twice more.
        runner.run(_bars([100.0, 105.0, 50.0, 55.0, 200.0]))

        assert runner.is_flat
        # Only the original entry+exit reached the execution adapter - the
        # two later signals were blocked by the risk engine before
        # submission, proving the loss was actually recorded (a live_runner
        # bug that dropped realized PnL would show a 3rd/4th submission here).
        assert len(adapter.submitted) == 2
