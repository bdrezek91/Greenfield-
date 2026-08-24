from __future__ import annotations

from datetime import date

from src.data.historical_backfill import (
    build_historical_backfill_jobs,
    load_historical_backfill_config,
)


def test_default_plan_covers_three_venues_assets_and_six_timeframes() -> None:
    config = load_historical_backfill_config()
    jobs = build_historical_backfill_jobs(config, as_of=date(2026, 8, 24))

    klines = [job for job in jobs if job.dataset == "klines"]
    assert len(klines) == 3 * 3 * 6
    assert {job.symbol for job in jobs} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert {job.venue for job in klines} == {"bybit", "binance", "okx"}
    assert {job.timeframe for job in klines} == {"1m", "5m", "15m", "1h", "4h", "1d"}


def test_plan_is_tiered_and_clamped_to_symbol_history() -> None:
    config = load_historical_backfill_config()
    jobs = build_historical_backfill_jobs(config, as_of=date(2026, 8, 24))

    btc_1m = next(
        job
        for job in jobs
        if job.dataset == "klines"
        and job.venue == "bybit"
        and job.symbol == "BTCUSDT"
        and job.timeframe == "1m"
    )
    sol_1d = next(
        job
        for job in jobs
        if job.dataset == "klines"
        and job.venue == "okx"
        and job.symbol == "SOLUSDT"
        and job.timeframe == "1d"
    )
    assert btc_1m.start == date(2026, 2, 25)
    assert sol_1d.start == date(2021, 9, 1)
    assert sol_1d.venue_symbol == "SOL-USDT-SWAP"


def test_derivatives_plan_respects_provider_specific_windows() -> None:
    config = load_historical_backfill_config()
    jobs = build_historical_backfill_jobs(config, as_of=date(2026, 8, 24))

    funding = [job for job in jobs if job.dataset == "funding"]
    interest = [job for job in jobs if job.dataset == "open_interest"]
    assert len(funding) == 3
    assert len(interest) == 3
    assert all(job.venue == "bybit" for job in funding + interest)
    assert all(job.start == date(2026, 7, 25) for job in interest)
    assert all(job.timeframe == "5min" for job in interest)
