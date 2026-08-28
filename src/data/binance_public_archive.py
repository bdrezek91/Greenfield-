"""Capacity-safe access to Binance's official monthly public-data archive.

The archive ZIP and its official checksum are retained unchanged as Bronze.
Normalization is deliberately a separate step so a parser change can always
be replayed from the original provider artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "binance_public_archive.yaml"
)
GIB = 1024**3
_MARKETS = {"spot", "futures/um"}
_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}


@dataclass(frozen=True, slots=True)
class BinanceArchiveDataset:
    market: str
    name: str
    cadence: str
    interval: str | None
    symbol_starts: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class BinanceArchiveConfig:
    version: int
    base_url: str
    minimum_free_bytes: int
    download_budget_bytes: int
    datasets: tuple[BinanceArchiveDataset, ...]


@dataclass(frozen=True, slots=True)
class BinanceArchiveJob:
    base_url: str
    market: str
    dataset: str
    symbol: str
    cadence: str
    period: str
    interval: str | None = None

    @property
    def filename(self) -> str:
        archive_kind = self.interval or self.dataset
        return f"{self.symbol}-{archive_kind}-{self.period}.zip"

    @property
    def url(self) -> str:
        interval = f"/{self.interval}" if self.interval else ""
        return (
            f"{self.base_url}/{self.market}/{self.cadence}/{self.dataset}/"
            f"{self.symbol}{interval}/{self.filename}"
        )

    @property
    def checksum_url(self) -> str:
        return f"{self.url}.CHECKSUM"

    @property
    def identity(self) -> str:
        interval = self.interval or "none"
        return f"{self.market}:{self.cadence}:{self.dataset}:{self.symbol}:{interval}:{self.period}"

    def target_path(self, data_dir: Path) -> Path:
        interval = (self.interval,) if self.interval else ()
        return Path(data_dir).joinpath(
            "external",
            "binance-public-data",
            self.market.replace("/", "-"),
            self.dataset,
            self.symbol,
            *interval,
            self.filename,
        )


@dataclass(frozen=True, slots=True)
class BinanceArchiveProbe:
    job: BinanceArchiveJob
    available: bool
    size_bytes: int | None
    status_code: int
    error: str | None = None


def load_binance_archive_config(
    path: Path = DEFAULT_CONFIG_PATH,
) -> BinanceArchiveConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("version", 0)) != 1:
        raise ValueError("Binance public archive config version must be 1")
    base_url = str(raw.get("base_url", "")).rstrip("/")
    if not base_url.startswith("https://"):
        raise ValueError("Binance public archive base_url must use HTTPS")
    minimum_free = _positive_number(raw.get("minimum_free_gib"), "minimum_free_gib")
    budget = _positive_number(raw.get("download_budget_gib"), "download_budget_gib")
    raw_datasets = raw.get("datasets")
    if not isinstance(raw_datasets, list) or not raw_datasets:
        raise ValueError("Binance public archive datasets are required")
    datasets: list[BinanceArchiveDataset] = []
    identities: set[tuple[str, str, str | None]] = set()
    for value in raw_datasets:
        if not isinstance(value, dict):
            raise ValueError("Binance public archive dataset must be a mapping")
        market = str(value.get("market", ""))
        name = str(value.get("name", ""))
        interval_value = value.get("interval")
        interval = str(interval_value) if interval_value is not None else None
        cadence = str(value.get("cadence", "monthly"))
        symbols = value.get("symbols")
        if market not in _MARKETS or not name or cadence not in {"monthly", "daily"}:
            raise ValueError("Binance public archive market/dataset is invalid")
        if not isinstance(symbols, dict) or set(symbols) != _SYMBOLS:
            raise ValueError("Binance public archive universe must be exactly BTC/ETH/SOL")
        identity = (market, name, interval)
        if identity in identities:
            raise ValueError(f"duplicate Binance public archive dataset: {identity}")
        identities.add(identity)
        starts = tuple(
            (str(symbol), _validate_period(str(start), cadence))
            for symbol, start in symbols.items()
        )
        datasets.append(
            BinanceArchiveDataset(
                market=market,
                name=name,
                cadence=cadence,
                interval=interval,
                symbol_starts=starts,
            )
        )
    return BinanceArchiveConfig(
        version=1,
        base_url=base_url,
        minimum_free_bytes=int(minimum_free * GIB),
        download_budget_bytes=int(budget * GIB),
        datasets=tuple(datasets),
    )


def build_binance_archive_jobs(
    config: BinanceArchiveConfig,
    *,
    as_of: date,
) -> tuple[BinanceArchiveJob, ...]:
    """Build jobs through the last fully closed UTC month."""
    jobs: list[BinanceArchiveJob] = []
    for dataset in config.datasets:
        end = (
            _previous_month(as_of.strftime("%Y-%m"))
            if dataset.cadence == "monthly"
            else (as_of - timedelta(days=1)).isoformat()
        )
        for symbol, start in dataset.symbol_starts:
            for period in _periods(start, end, dataset.cadence):
                jobs.append(
                    BinanceArchiveJob(
                        base_url=config.base_url,
                        market=dataset.market,
                        dataset=dataset.name,
                        symbol=symbol,
                        interval=dataset.interval,
                        cadence=dataset.cadence,
                        period=period,
                    )
                )
    return tuple(jobs)


def probe_binance_archives(
    jobs: Iterable[BinanceArchiveJob],
    *,
    workers: int = 12,
    timeout_seconds: float = 20.0,
) -> tuple[BinanceArchiveProbe, ...]:
    if workers < 1 or workers > 32:
        raise ValueError("workers must be in [1, 32]")

    def probe(job: BinanceArchiveJob) -> BinanceArchiveProbe:
        request = urllib.request.Request(job.url, method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                size_header = response.headers.get("Content-Length")
                size = int(size_header) if size_header is not None else None
                return BinanceArchiveProbe(job, True, size, int(response.status))
        except urllib.error.HTTPError as exc:
            return BinanceArchiveProbe(job, False, None, int(exc.code), str(exc))
        except (OSError, urllib.error.URLError) as exc:
            return BinanceArchiveProbe(job, False, None, 0, str(exc))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        return tuple(executor.map(probe, jobs))


def select_downloads(
    probes: Iterable[BinanceArchiveProbe],
    *,
    budget_bytes: int,
    newest_first: bool = True,
) -> tuple[BinanceArchiveProbe, ...]:
    if budget_bytes <= 0:
        raise ValueError("budget_bytes must be positive")
    available = [probe for probe in probes if probe.available and probe.size_bytes is not None]
    available.sort(key=lambda value: (value.job.period, value.job.identity), reverse=newest_first)
    selected: list[BinanceArchiveProbe] = []
    used = 0
    for probe in available:
        assert probe.size_bytes is not None
        if used + probe.size_bytes > budget_bytes:
            continue
        selected.append(probe)
        used += probe.size_bytes
    return tuple(selected)


def download_binance_archive(
    probe: BinanceArchiveProbe,
    *,
    data_dir: Path,
    minimum_free_bytes: int,
    timeout_seconds: float = 120.0,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> tuple[Path, bool]:
    """Download and verify one archive. Returns ``(path, downloaded)``."""
    if not probe.available or probe.size_bytes is None:
        raise ValueError("cannot download an unavailable or unsized archive")
    target = probe.job.target_path(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    checksum_text = _read_url(probe.job.checksum_url, timeout_seconds).decode("utf-8")
    expected = parse_checksum(checksum_text, expected_filename=probe.job.filename)
    if target.exists():
        if sha256_file(target) != expected:
            raise ValueError(f"existing Binance archive checksum mismatch: {target}")
        return target, False
    free = int(disk_usage(target.parent).free)
    required = probe.size_bytes + minimum_free_bytes
    if free < required:
        raise OSError(
            f"capacity gate refused {probe.job.identity}: free={free}, required={required}"
        )
    temp = target.with_suffix(target.suffix + ".part")
    try:
        request = urllib.request.Request(probe.job.url)
        with (
            urllib.request.urlopen(request, timeout=timeout_seconds) as response,
            temp.open("wb") as output,
        ):
            shutil.copyfileobj(response, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        actual = sha256_file(temp)
        if actual != expected:
            raise ValueError(
                "downloaded Binance archive checksum mismatch: "
                f"expected={expected}, actual={actual}"
            )
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    metadata = {
        "schema_version": 1,
        "identity": probe.job.identity,
        "source_url": probe.job.url,
        "checksum_url": probe.job.checksum_url,
        "content_sha256": expected,
        "size_bytes": target.stat().st_size,
        "downloaded_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_json_atomic(target.with_suffix(target.suffix + ".manifest.json"), metadata)
    return target, True


def parse_checksum(value: str, *, expected_filename: str) -> str:
    fields = value.strip().split()
    if len(fields) < 2 or fields[-1].lstrip("*") != expected_filename:
        raise ValueError("unexpected Binance checksum response")
    digest = fields[0].lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("invalid Binance SHA-256 checksum")
    return digest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probes_report(probes: Iterable[BinanceArchiveProbe]) -> dict[str, Any]:
    values = tuple(probes)
    available = tuple(value for value in values if value.available)
    known_sizes = tuple(value.size_bytes for value in available if value.size_bytes is not None)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "requested_archives": len(values),
        "available_archives": len(available),
        "missing_archives": sum(value.status_code == 404 for value in values),
        "probe_errors": sum(value.status_code not in {200, 404} for value in values),
        "known_size_bytes": sum(known_sizes),
        "archives": [
            {
                "identity": value.job.identity,
                "url": value.job.url,
                "available": value.available,
                "status_code": value.status_code,
                "size_bytes": value.size_bytes,
                "error": value.error,
            }
            for value in values
        ],
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    _write_json_atomic(path, report)


def _read_url(url: str, timeout_seconds: float) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout_seconds) as response:
        return response.read()


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temp.replace(path)


def _positive_number(value: Any, name: str) -> float:
    result = float(value or 0)
    if result <= 0:
        raise ValueError(f"Binance public archive {name} must be positive")
    return result


def _validate_period(value: str, cadence: str) -> str:
    pattern = "%Y-%m" if cadence == "monthly" else "%Y-%m-%d"
    try:
        parsed = datetime.strptime(value, pattern)
    except ValueError as exc:
        raise ValueError(f"invalid {cadence} archive period: {value}") from exc
    return parsed.strftime(pattern)


def _previous_month(value: str) -> str:
    current = datetime.strptime(value, "%Y-%m")
    if current.month == 1:
        return f"{current.year - 1:04d}-12"
    return f"{current.year:04d}-{current.month - 1:02d}"


def _periods(start: str, end: str, cadence: str) -> Iterable[str]:
    pattern = "%Y-%m" if cadence == "monthly" else "%Y-%m-%d"
    current = datetime.strptime(start, pattern)
    finish = datetime.strptime(end, pattern)
    while current <= finish:
        yield current.strftime(pattern)
        if cadence == "daily":
            current += timedelta(days=1)
        elif current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
