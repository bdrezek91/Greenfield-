"""Real-data coarse screen of Bybit vs Hyperliquid cross-exchange funding
edge, using the existing `src.engines.neutral_market` engine (no new
carry engine built for this) - GREENFIELD PROFITABILITY PIVOT item 5.

"Coarse" deliberately means gross edge only
(`derive_cross_exchange_funding_edge`'s `expected_gross_edge_bps`): entry
basis + a projected funding differential over `--horizon-hours`, with a
symmetric `--model-uncertainty-bps` band. It does NOT subtract fees,
exit costs, slippage, or orphan-leg risk - see
`src.engines.neutral.NeutralCostBreakdown`/`evaluate_neutral_opportunity`
for the full, cost-adjusted evaluation a real candidate would need to
clear next. This script only tells you whether the gross signal is even
worth that next step.

Only Bybit and Hyperliquid: Binance/OKX have no funding-rate client in
this project (see the data-inventory checkpoint in
docs/CLAUDE_CODE_CONTINUATION.md) so they cannot form a real executable
quote leg here.

Funding rates on the two venues have different cadences (Bybit: 8h:
`fundingIntervalHour`; Hyperliquid: 1h typically, but read from
`fundingIntervalHours` per response, not assumed) - both are normalized
to an hourly rate before `derive_cross_exchange_funding_edge` projects
them over a common `--horizon-hours` window, so `funding_periods` always
means the same thing (hours) on both legs.

Usage:
    python scripts/screen_cross_exchange_funding.py --symbols BTC,ETH,SOL
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import structlog
import typer

from src.data.bybit_ticker_client import BybitTickerClient
from src.data.hyperliquid_client import HyperliquidInfoClient
from src.engines.neutral_market import (
    ExecutablePerpetualQuote,
    derive_cross_exchange_funding_edge,
)

log = structlog.get_logger()
app = typer.Typer(add_completion=False)


def _bybit_quote(
    client: BybitTickerClient, coin: str, *, as_of: datetime
) -> ExecutablePerpetualQuote:
    ticker = client.get_ticker(f"{coin}USDT")
    funding_rate_hourly = float(ticker["fundingRate"]) / float(ticker["fundingIntervalHour"])
    return ExecutablePerpetualQuote(
        venue="bybit",
        symbol=coin,
        bid=float(ticker["bid1Price"]),
        ask=float(ticker["ask1Price"]),
        funding_rate_per_period=funding_rate_hourly,
        executable_capacity_notional=float(ticker["bid1Size"]) * float(ticker["bid1Price"]),
        received_at_utc=as_of,
    )


def _hyperliquid_quote(client: HyperliquidInfoClient, coin: str) -> ExecutablePerpetualQuote:
    predicted = client.get_predicted_fundings()
    venue_rates = dict(next(entry for entry in predicted if entry[0] == coin)[1])
    hl_predicted = venue_rates["HlPerp"]
    funding_rate_hourly = float(hl_predicted["fundingRate"]) / float(
        hl_predicted["fundingIntervalHours"]
    )
    book = client.get_l2_book(coin)
    bids, asks = book["levels"][0], book["levels"][1]
    return ExecutablePerpetualQuote(
        venue="hyperliquid",
        symbol=coin,
        bid=float(bids[0]["px"]),
        ask=float(asks[0]["px"]),
        funding_rate_per_period=funding_rate_hourly,
        executable_capacity_notional=float(bids[0]["sz"]) * float(bids[0]["px"]),
        received_at_utc=pd.to_datetime(int(book["time"]), unit="ms", utc=True).to_pydatetime(),
    )


@app.command()
def screen(
    symbols: str = typer.Option("BTC,ETH,SOL", help="Comma-separated coins, e.g. BTC,ETH,SOL."),
    horizon_hours: int = typer.Option(24, help="Funding-differential projection horizon."),
    model_uncertainty_bps: float = typer.Option(
        5.0, help="Symmetric uncertainty band around the gross-edge point estimate."
    ),
) -> None:
    coins = tuple(s.strip() for s in symbols.split(",") if s.strip())
    if not coins:
        raise typer.BadParameter("symbols must list at least one coin", param_hint="--symbols")

    bybit = BybitTickerClient()
    hyperliquid = HyperliquidInfoClient()

    for coin in coins:
        try:
            bybit_quote = _bybit_quote(bybit, coin, as_of=datetime.now(UTC))
            hl_quote = _hyperliquid_quote(hyperliquid, coin)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not kill the screen
            log.error("screen failed for symbol", symbol=coin, error=str(exc))
            continue
        # Evaluated strictly after both quotes were fetched (l2Book's own
        # "time" reflects Hyperliquid's server clock at response time,
        # which can be a moment later than any "now" captured before the
        # request went out - using a stale `as_of` here would spuriously
        # reject a perfectly fresh quote as "future").
        as_of = datetime.now(UTC)

        for long_venue, short_venue in (
            (hl_quote, bybit_quote),
            (bybit_quote, hl_quote),
        ):
            edge = derive_cross_exchange_funding_edge(
                long_venue,
                short_venue,
                as_of_utc=as_of,
                funding_periods=horizon_hours,
                model_uncertainty_bps=model_uncertainty_bps,
            )
            log.info(
                "coarse funding edge",
                symbol=coin,
                long_venue=long_venue.venue,
                short_venue=short_venue.venue,
                gross_edge_bps_low=round(edge.expected_gross_edge_bps.low, 3),
                gross_edge_bps_base=round(edge.expected_gross_edge_bps.base, 3),
                gross_edge_bps_high=round(edge.expected_gross_edge_bps.high, 3),
                entry_basis_bps=round(edge.entry_basis_bps, 3),
                funding_differential_bps=round(edge.funding_differential_bps, 3),
                capacity_notional=round(edge.capacity_notional, 2),
            )


if __name__ == "__main__":
    app()
