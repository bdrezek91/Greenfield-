from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.data.raw_event import parse_bybit_message
from src.data.raw_store import AtomicRawWriter
from src.data.schema import empty_klines_frame
from src.data.schema_funding import empty_funding_frame
from src.data.storage import write_funding, write_klines
from src.engines.contracts import SetupAction
from src.execution.demo_scalp_liquidation_backtest import (
    LiquidationFadeBacktestConfig,
    LiquidationFadeExit,
    run_liquidation_fade_backtest,
)
from src.execution.demo_scalp_liquidation_signal import (
    FundingRegimeConfig,
    LiquidationCascadeConfig,
)

SYMBOL = "BTCUSDT"


def _write_liquidations(data_dir: Path, at: datetime, count: int = 3) -> None:
    events = []
    for i in range(count):
        timestamp = at - timedelta(seconds=(count - i) * 20)
        payload = json.dumps(
            {
                "topic": f"allLiquidation.{SYMBOL}",
                "type": "snapshot",
                "ts": int(timestamp.timestamp() * 1000),
                "data": [
                    {
                        "T": int(timestamp.timestamp() * 1000),
                        "s": SYMBOL,
                        "S": "Sell",  # forced sell -> longs liquidated -> fade to LONG
                        "v": "5.0",
                        "p": "80000",
                    }
                ],
            }
        )
        events.append(
            parse_bybit_message(
                payload,
                receive_ts_ns=int(timestamp.timestamp() * 1_000_000_000),
                connection_id="test-connection",
                receive_sequence=i + 1,
            )
        )
    AtomicRawWriter(data_dir).write(events)


def _write_candles(data_dir: Path, start: datetime, closes: list[float]) -> None:
    frame = empty_klines_frame()
    for i, close in enumerate(closes):
        ts = start + timedelta(minutes=5 * i)
        frame.loc[i] = {
            "timestamp": ts,
            "open": close,
            "high": close + 10,
            "low": close - 10,
            "close": close,
            "volume": 1.0,
            "turnover": close,
            "symbol": SYMBOL,
            "timeframe": "5m",
        }
    write_klines(frame, data_dir)


def _write_neutral_funding(data_dir: Path, start: datetime, hours: int = 2) -> None:
    frame = empty_funding_frame()
    for i in range(hours):
        frame.loc[i] = {
            "timestamp": start + timedelta(hours=i),
            "symbol": SYMBOL,
            "funding_rate": 0.0,
        }
    write_funding(frame, data_dir)


def _config(start: datetime, end: datetime, **overrides: object) -> LiquidationFadeBacktestConfig:
    defaults: dict[str, object] = dict(
        symbol=SYMBOL,
        start=start,
        end=end,
        cascade_config=LiquidationCascadeConfig(
            lookback_seconds=180,
            reference_window_seconds=1800,
            minimum_notional_ratio=2.0,
            minimum_window_notional=1.0,
        ),
    )
    defaults.update(overrides)
    return LiquidationFadeBacktestConfig(**defaults)  # type: ignore[arg-type]


def test_backtest_takes_a_trade_and_resolves_take_profit(tmp_path: Path) -> None:
    cascade_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    start = cascade_at - timedelta(minutes=10)
    end = cascade_at + timedelta(hours=1)
    _write_liquidations(tmp_path, cascade_at)
    # Entry candle at cascade_at close=80000; price rises to hit +30bps target.
    candle_start = start
    closes = [80000.0] * 3 + [80000.0, 80260.0] + [80260.0] * 10
    _write_candles(tmp_path, candle_start, closes)
    _write_neutral_funding(tmp_path, start - timedelta(hours=1))

    report = run_liquidation_fade_backtest(tmp_path, _config(start, end))

    assert report.cascades_detected >= 1
    assert report.trades_taken == 1
    trade = report.trades[0]
    assert trade.direction is SetupAction.LONG
    assert trade.exit_reason is LiquidationFadeExit.TAKE_PROFIT
    assert trade.return_bps == pytest.approx(30.0, abs=0.5)


def test_backtest_resolves_stop_loss_on_adverse_move(tmp_path: Path) -> None:
    cascade_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    start = cascade_at - timedelta(minutes=10)
    end = cascade_at + timedelta(hours=1)
    _write_liquidations(tmp_path, cascade_at)
    closes = [80000.0] * 3 + [80000.0, 79820.0] + [79820.0] * 10
    _write_candles(tmp_path, start, closes)
    _write_neutral_funding(tmp_path, start - timedelta(hours=1))

    report = run_liquidation_fade_backtest(tmp_path, _config(start, end))

    assert report.trades_taken == 1
    trade = report.trades[0]
    assert trade.exit_reason is LiquidationFadeExit.STOP_LOSS
    assert trade.return_bps == pytest.approx(-20.0, abs=0.5)


def test_backtest_vetoes_trade_when_funding_is_extremely_positive(tmp_path: Path) -> None:
    cascade_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    start = cascade_at - timedelta(minutes=10)
    end = cascade_at + timedelta(hours=1)
    _write_liquidations(tmp_path, cascade_at)
    closes = [80000.0] * 3 + [80000.0, 80260.0] + [80260.0] * 10
    _write_candles(tmp_path, start, closes)

    frame = empty_funding_frame()
    frame.loc[0] = {
        "timestamp": start - timedelta(hours=1),
        "symbol": SYMBOL,
        "funding_rate": 0.01,  # extreme positive -> vetoes the LONG fade
    }
    write_funding(frame, tmp_path)

    report = run_liquidation_fade_backtest(
        tmp_path, _config(start, end, funding_config=FundingRegimeConfig())
    )

    assert report.cascades_detected >= 1
    assert report.trades_taken == 0
    assert report.trades_vetoed_by_funding >= 1
