"""Fail-closed public WebSocket preflight for Phase 3 venue collectors.

The probe opens no authenticated channel and submits no order.  It proves that
the target host can establish each collector's actual public WebSocket,
subscribe to one representative market-data channel, and receive a
venue-specific acknowledgement.  A successful TCP/TLS handshake alone is not
accepted because it would miss subscription-schema or product errors.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.data.binance_raw_collector import BINANCE_FUTURES_WS
from src.data.coinbase_raw_collector import COINBASE_PUBLIC_WS
from src.data.deribit_raw_collector import DERIBIT_PUBLIC_WS
from src.data.okx_raw_collector import OKX_PUBLIC_WS

SUPPORTED_VENUES = ("binance", "okx", "coinbase", "deribit")


@dataclass(frozen=True, slots=True)
class VenueProbeSpec:
    venue: str
    websocket_url: str
    subscription: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class VenueProbeResult:
    venue: str
    websocket_url: str
    passed: bool
    elapsed_seconds: float
    detail: str


@dataclass(frozen=True, slots=True)
class RawVenuePreflightReport:
    schema_version: int
    generated_at_utc: str
    qualified: bool
    expected_commit: str
    observed_commit: str
    working_tree_clean: bool
    venues: tuple[VenueProbeResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_raw_venue_preflight_report(
    path: Path,
    *,
    expected_commit: str,
    venue: str,
    now_ns: int | None = None,
    max_age_secs: float = 15 * 60,
) -> str:
    """Validate immutable venue evidence and return its content SHA-256."""

    normalized_venue = venue_probe_spec(venue).venue
    if max_age_secs <= 0:
        raise ValueError("max_age_secs must be positive")
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("venue preflight report must be a JSON object")
    if value.get("schema_version") != 1 or value.get("qualified") is not True:
        raise ValueError("venue preflight report is not qualified schema version 1 evidence")
    if (
        value.get("expected_commit") != expected_commit
        or value.get("observed_commit") != expected_commit
        or value.get("working_tree_clean") is not True
    ):
        raise ValueError("venue preflight report does not prove the clean source commit")
    generated = value.get("generated_at_utc")
    if not isinstance(generated, str):
        raise ValueError("venue preflight report lacks generated_at_utc")
    try:
        generated_at = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("venue preflight generated_at_utc is invalid") from exc
    if generated_at.tzinfo is None:
        raise ValueError("venue preflight generated_at_utc must include a timezone")
    current_ns = time.time_ns() if now_ns is None else now_ns
    age_secs = (current_ns - int(generated_at.timestamp() * 1_000_000_000)) / 1_000_000_000
    if age_secs < -60:
        raise ValueError("venue preflight report timestamp is in the future")
    if age_secs > max_age_secs:
        raise ValueError("venue preflight report is stale")
    venues = value.get("venues")
    if not isinstance(venues, list) or not any(
        isinstance(item, dict)
        and item.get("venue") == normalized_venue
        and item.get("passed") is True
        for item in venues
    ):
        raise ValueError(f"venue preflight did not qualify {normalized_venue}")
    return hashlib.sha256(raw).hexdigest()


def venue_probe_spec(venue: str) -> VenueProbeSpec:
    normalized = venue.strip().lower()
    if normalized == "binance":
        return VenueProbeSpec(
            venue=normalized,
            websocket_url=BINANCE_FUTURES_WS,
            subscription={
                "method": "SUBSCRIBE",
                "params": ["btcusdt@trade"],
                "id": 1,
            },
        )
    if normalized == "okx":
        return VenueProbeSpec(
            venue=normalized,
            websocket_url=OKX_PUBLIC_WS,
            subscription={
                "op": "subscribe",
                "args": [{"channel": "books", "instId": "BTC-USDT-SWAP"}],
            },
        )
    if normalized == "coinbase":
        return VenueProbeSpec(
            venue=normalized,
            websocket_url=COINBASE_PUBLIC_WS,
            subscription={
                "type": "subscribe",
                "product_ids": ["BTC-USD"],
                "channel": "ticker",
            },
        )
    if normalized == "deribit":
        channel = "ticker.BTC-PERPETUAL.100ms"
        return VenueProbeSpec(
            venue=normalized,
            websocket_url=DERIBIT_PUBLIC_WS,
            subscription={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "public/subscribe",
                "params": {"channels": [channel]},
            },
        )
    raise ValueError(f"unsupported venue: {venue!r}")


def acknowledgement_matches(spec: VenueProbeSpec, payload: Mapping[str, Any]) -> bool:
    """Recognize only an acknowledgement/data shape for the exact probe."""

    if spec.venue == "binance":
        return payload.get("id") == 1 and payload.get("result") is None
    if spec.venue == "okx":
        argument = payload.get("arg")
        return (
            payload.get("event") == "subscribe"
            and isinstance(argument, dict)
            and argument.get("channel") == "books"
            and argument.get("instId") == "BTC-USDT-SWAP"
        )
    if spec.venue == "coinbase":
        channel = payload.get("channel")
        if channel == "subscriptions":
            return True
        if channel != "ticker":
            return False
        events = payload.get("events")
        return isinstance(events, list) and bool(events)
    if spec.venue == "deribit":
        result = payload.get("result")
        return (
            payload.get("id") == 1
            and isinstance(result, list)
            and "ticker.BTC-PERPETUAL.100ms" in result
        )
    return False


def probe_public_websocket(
    spec: VenueProbeSpec, *, timeout_seconds: float = 10.0
) -> VenueProbeResult:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    started = time.monotonic()
    try:
        import websocket

        connection = websocket.create_connection(
            spec.websocket_url,
            timeout=timeout_seconds,
        )
        try:
            connection.send(json.dumps(dict(spec.subscription), separators=(",", ":")))
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                remaining = max(0.1, deadline - time.monotonic())
                connection.settimeout(remaining)
                raw = connection.recv()
                if not isinstance(raw, str):
                    continue
                payload = json.loads(raw)
                if isinstance(payload, dict) and acknowledgement_matches(spec, payload):
                    return VenueProbeResult(
                        spec.venue,
                        spec.websocket_url,
                        True,
                        time.monotonic() - started,
                        "public subscription acknowledged",
                    )
                if isinstance(payload, dict) and (
                    payload.get("event") == "error" or "error" in payload
                ):
                    raise RuntimeError("venue returned a subscription error")
            raise TimeoutError("no matching subscription acknowledgement")
        finally:
            connection.close()
    except Exception as exc:
        # A preflight is deliberately fail-closed across transport-library,
        # TLS, decoding and venue errors. KeyboardInterrupt/SystemExit still
        # propagate because they do not inherit from Exception.
        return VenueProbeResult(
            spec.venue,
            spec.websocket_url,
            False,
            time.monotonic() - started,
            f"{type(exc).__name__}: {exc}",
        )


Probe = Callable[[VenueProbeSpec], VenueProbeResult]


def run_raw_venue_preflight(
    *,
    repository_root: Path,
    expected_commit: str,
    venues: Iterable[str] = SUPPORTED_VENUES,
    probe: Probe | None = None,
) -> RawVenuePreflightReport:
    repo = Path(repository_root).resolve()
    observed_commit = _git(repo, "rev-parse", "HEAD")
    clean = _git(repo, "status", "--porcelain") == ""
    selected = tuple(venue.strip().lower() for venue in venues)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("venues must be nonempty and unique")
    specs = tuple(venue_probe_spec(venue) for venue in selected)
    runner = probe or (lambda spec: probe_public_websocket(spec))
    results = tuple(runner(spec) for spec in specs)
    exact_commit = len(expected_commit) == 40 and observed_commit == expected_commit and clean
    return RawVenuePreflightReport(
        schema_version=1,
        generated_at_utc=datetime.now(UTC).isoformat(),
        qualified=exact_commit and all(item.passed for item in results),
        expected_commit=expected_commit,
        observed_commit=observed_commit or "",
        working_tree_clean=clean,
        venues=results,
    )


def write_raw_venue_preflight_report(path: Path, report: RawVenuePreflightReport) -> None:
    """Create immutable evidence; an existing report is never overwritten."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    document = json.dumps(report.to_dict(), sort_keys=True, indent=2) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise FileExistsError(f"preflight report already exists: {destination}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _git(repository_root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ("git", *arguments),
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None
