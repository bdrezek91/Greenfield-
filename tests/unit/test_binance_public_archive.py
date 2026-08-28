from __future__ import annotations

import hashlib
import io
from datetime import date
from types import SimpleNamespace

import pytest

import src.data.binance_public_archive as archive
from src.data.binance_public_archive import (
    BinanceArchiveJob,
    BinanceArchiveProbe,
    build_binance_archive_jobs,
    download_binance_archive,
    load_binance_archive_config,
    parse_checksum,
    select_downloads,
)


def test_config_covers_spot_futures_trades_and_derivatives() -> None:
    config = load_binance_archive_config()
    identities = {(item.market, item.name, item.interval) for item in config.datasets}
    assert ("spot", "trades", None) in identities
    assert ("spot", "aggTrades", None) in identities
    assert ("futures/um", "trades", None) in identities
    assert ("futures/um", "aggTrades", None) in identities
    assert ("futures/um", "fundingRate", None) in identities
    assert ("futures/um", "markPriceKlines", "1m") in identities
    assert ("futures/um", "metrics", None) in identities
    assert all(
        {symbol for symbol, _ in item.symbol_starts} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        for item in config.datasets
    )


def test_jobs_stop_at_last_closed_month_and_format_urls() -> None:
    config = load_binance_archive_config()
    jobs = build_binance_archive_jobs(config, as_of=date(2026, 8, 28))
    assert jobs
    monthly = [job for job in jobs if job.cadence == "monthly"]
    daily = [job for job in jobs if job.cadence == "daily"]
    assert max(job.period for job in monthly) == "2026-07"
    assert max(job.period for job in daily) == "2026-08-27"
    btc = next(
        job
        for job in jobs
        if job.market == "futures/um"
        and job.dataset == "markPriceKlines"
        and job.symbol == "BTCUSDT"
        and job.period == "2026-07"
    )
    assert btc.filename == "BTCUSDT-1m-2026-07.zip"
    assert btc.url == (
        "https://data.binance.vision/data/futures/um/monthly/markPriceKlines/"
        "BTCUSDT/1m/BTCUSDT-1m-2026-07.zip"
    )
    trades = next(
        job
        for job in jobs
        if job.market == "spot"
        and job.dataset == "trades"
        and job.symbol == "BTCUSDT"
        and job.period == "2026-07"
    )
    assert trades.filename == "BTCUSDT-trades-2026-07.zip"


def test_checksum_parser_is_fail_closed() -> None:
    digest = "a" * 64
    assert (
        parse_checksum(
            f"{digest}  BTCUSDT-trades-2026-07.zip\n",
            expected_filename="BTCUSDT-trades-2026-07.zip",
        )
        == digest
    )
    with pytest.raises(ValueError, match="unexpected"):
        parse_checksum(f"{digest}  wrong.zip", expected_filename="BTCUSDT-trades-2026-07.zip")
    with pytest.raises(ValueError, match="invalid"):
        parse_checksum(
            "xyz  BTCUSDT-trades-2026-07.zip", expected_filename="BTCUSDT-trades-2026-07.zip"
        )


def test_download_selection_honours_budget_and_recent_first() -> None:
    def value(month: str, size: int) -> BinanceArchiveProbe:
        job = BinanceArchiveJob(
            base_url="https://example.test",
            market="spot",
            dataset="trades",
            symbol="BTCUSDT",
            cadence="monthly",
            period=month,
        )
        return BinanceArchiveProbe(job, True, size, 200)

    selected = select_downloads(
        (value("2026-05", 60), value("2026-06", 50), value("2026-07", 40)),
        budget_bytes=90,
    )
    assert [item.job.period for item in selected] == ["2026-07", "2026-06"]


def test_download_is_atomic_checksum_verified_and_reusable(tmp_path, monkeypatch) -> None:
    payload = b"immutable-binance-archive"
    digest = hashlib.sha256(payload).hexdigest()
    job = BinanceArchiveJob(
        base_url="https://example.test",
        market="spot",
        dataset="trades",
        symbol="BTCUSDT",
        cadence="monthly",
        period="2026-07",
    )
    probe = BinanceArchiveProbe(job, True, len(payload), 200)

    monkeypatch.setattr(
        archive,
        "_read_url",
        lambda *_args, **_kwargs: f"{digest}  {job.filename}\n".encode(),
    )
    monkeypatch.setattr(
        archive.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(payload),
    )
    def disk(_path):
        return SimpleNamespace(free=10_000)
    path, changed = download_binance_archive(
        probe,
        data_dir=tmp_path,
        minimum_free_bytes=100,
        disk_usage=disk,
    )
    assert changed is True
    assert path.read_bytes() == payload
    assert path.with_suffix(".zip.manifest.json").exists()

    monkeypatch.setattr(
        archive.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("existing verified archive was downloaded again"),
    )
    reused, changed = download_binance_archive(
        probe,
        data_dir=tmp_path,
        minimum_free_bytes=100,
        disk_usage=disk,
    )
    assert reused == path
    assert changed is False


def test_download_fails_closed_when_reserve_would_be_breached(tmp_path, monkeypatch) -> None:
    job = BinanceArchiveJob(
        base_url="https://example.test",
        market="spot",
        dataset="trades",
        symbol="BTCUSDT",
        cadence="monthly",
        period="2026-07",
    )
    probe = BinanceArchiveProbe(job, True, 500, 200)
    digest = "a" * 64
    monkeypatch.setattr(
        archive,
        "_read_url",
        lambda *_args, **_kwargs: f"{digest}  {job.filename}\n".encode(),
    )
    with pytest.raises(OSError, match="capacity gate refused"):
        download_binance_archive(
            probe,
            data_dir=tmp_path,
            minimum_free_bytes=1_000,
            disk_usage=lambda _path: SimpleNamespace(free=1_200),
        )
