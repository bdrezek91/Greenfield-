"""Backtest the "druga proba scalpingu" liquidation-fade candidate against
this system's own historical Bronze/Silver data - run this on the VPS,
where the real data lake lives, before any live redeployment.

Example:
    python scripts/backtest_liquidation_fade.py \\
        --data-dir data --symbol BTCUSDT \\
        --start 2026-08-01T00:00:00+00:00 --end 2026-08-26T00:00:00+00:00
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from src.execution.demo_opportunity_scanner_v2 import LIQUIDATION_FADE_CANDIDATE_ID
from src.execution.demo_scalp_liquidation_backtest import (
    LiquidationFadeBacktestConfig,
    run_liquidation_fade_backtest,
)
from src.execution.demo_scalp_liquidation_signal import (
    FundingRegimeConfig,
    LiquidationCascadeConfig,
)

app = typer.Typer(add_completion=False)


@app.command()
def backtest(
    start: Annotated[str, typer.Option(help="ISO 8601, e.g. 2026-08-01T00:00:00+00:00")],
    end: Annotated[str, typer.Option(help="ISO 8601, e.g. 2026-08-26T00:00:00+00:00")],
    data_dir: Annotated[Path, typer.Option()] = Path("data"),
    symbol: Annotated[str, typer.Option()] = "BTCUSDT",
    stop_loss_bps: Annotated[int, typer.Option(min=1, max=99)] = 20,
    take_profit_bps: Annotated[int, typer.Option(min=1, max=99)] = 30,
    maximum_holding_seconds: Annotated[int, typer.Option(min=1)] = 600,
    cooldown_seconds: Annotated[int, typer.Option(min=0)] = 300,
    cascade_lookback_seconds: Annotated[float, typer.Option(min=1)] = 180.0,
    cascade_reference_window_seconds: Annotated[float, typer.Option(min=1)] = 1_800.0,
    cascade_minimum_notional_ratio: Annotated[float, typer.Option(min=1.01)] = 3.0,
    cascade_minimum_window_notional: Annotated[float, typer.Option(min=0)] = 50_000.0,
    extreme_funding_rate: Annotated[str, typer.Option()] = "0.0005",
    maker_fee: Annotated[
        str | None, typer.Option(help="Defaults to configs/instruments.yaml's Bybit maker fee")
    ] = None,
    taker_fee: Annotated[
        str | None, typer.Option(help="Defaults to configs/instruments.yaml's Bybit taker fee")
    ] = None,
    report_path: Annotated[Path | None, typer.Option()] = None,
) -> None:
    try:
        parsed_start = datetime.fromisoformat(start)
        parsed_end = datetime.fromisoformat(end)
    except ValueError as exc:
        raise typer.BadParameter(f"--start/--end must be ISO 8601: {exc}") from exc
    if parsed_start.tzinfo is None or parsed_end.tzinfo is None:
        raise typer.BadParameter("--start/--end must include a UTC offset")
    fee_kwargs = {}
    if maker_fee is not None:
        fee_kwargs["maker_fee"] = Decimal(maker_fee)
    if taker_fee is not None:
        fee_kwargs["taker_fee"] = Decimal(taker_fee)
    config = LiquidationFadeBacktestConfig(
        symbol=symbol,
        start=parsed_start,
        end=parsed_end,
        stop_loss_bps=Decimal(stop_loss_bps),
        take_profit_bps=Decimal(take_profit_bps),
        maximum_holding_seconds=maximum_holding_seconds,
        cooldown_seconds=cooldown_seconds,
        cascade_config=LiquidationCascadeConfig(
            lookback_seconds=cascade_lookback_seconds,
            reference_window_seconds=cascade_reference_window_seconds,
            minimum_notional_ratio=cascade_minimum_notional_ratio,
            minimum_window_notional=cascade_minimum_window_notional,
        ),
        funding_config=FundingRegimeConfig(extreme_funding_rate=Decimal(extreme_funding_rate)),
        **fee_kwargs,
    )
    report = run_liquidation_fade_backtest(data_dir, config)

    breakeven_gross = report.breakeven_win_rate(
        stop_loss_bps=config.stop_loss_bps, take_profit_bps=config.take_profit_bps
    )
    breakeven_net = report.breakeven_win_rate(
        stop_loss_bps=config.stop_loss_bps,
        take_profit_bps=config.take_profit_bps,
        fee_bps=config.round_trip_fee_bps,
    )
    summary = report.summary()
    summary["round_trip_fee_bps"] = float(config.round_trip_fee_bps)
    summary["breakeven_win_rate_gross"] = breakeven_gross
    summary["breakeven_win_rate_net_of_fees"] = breakeven_net
    summary["edge_over_breakeven_net_of_fees"] = (
        None if report.win_rate is None else report.win_rate - breakeven_net
    )
    typer.echo(json.dumps(summary, sort_keys=True, indent=2))

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "entry_at_utc": t.entry_at_utc.isoformat(),
                "direction": t.direction.value,
                "liquidated_side": t.liquidated_side.value if t.liquidated_side else None,
                "entry_price": t.entry_price,
                "exit_at_utc": t.exit_at_utc.isoformat(),
                "exit_price": t.exit_price,
                "exit_reason": t.exit_reason.value,
                "return_bps": t.return_bps,
                "fee_bps": t.fee_bps,
                "net_return_bps": t.net_return_bps,
            }
            for t in report.trades
        ]
        evidence = {
            "schema_version": 1,
            "candidate_id": LIQUIDATION_FADE_CANDIDATE_ID,
            "evaluation_scope": "COARSE_IN_SAMPLE_SCREEN",
            "fees_applied": True,
            "summary": summary,
            "trades": rows,
        }
        report_path.write_text(
            json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"wrote {len(rows)} trades to {report_path}", err=True)

    if report.trades_taken == 0:
        typer.echo(
            "no trades were taken in this window - either no qualifying cascades occurred, "
            "or the local data lake is missing history for this symbol/window",
            err=True,
        )


if __name__ == "__main__":
    app()
