from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.raw_venue_preflight import (
    SUPPORTED_VENUES,
    VenueProbeResult,
    VenueProbeSpec,
    acknowledgement_matches,
    run_raw_venue_preflight,
    venue_probe_spec,
    write_raw_venue_preflight_report,
)


def test_exact_acknowledgements_are_required() -> None:
    assert acknowledgement_matches(
        venue_probe_spec("binance"), {"result": None, "id": 1}
    )
    assert acknowledgement_matches(
        venue_probe_spec("okx"),
        {
            "event": "subscribe",
            "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
        },
    )
    assert acknowledgement_matches(
        venue_probe_spec("coinbase"), {"channel": "subscriptions", "events": []}
    )
    assert acknowledgement_matches(
        venue_probe_spec("deribit"),
        {"id": 1, "result": ["ticker.BTC-PERPETUAL.100ms"]},
    )


@pytest.mark.parametrize("venue", SUPPORTED_VENUES)
def test_unrelated_or_error_payload_does_not_match(venue: str) -> None:
    assert not acknowledgement_matches(venue_probe_spec(venue), {"error": "no"})


def test_preflight_requires_clean_exact_commit_and_every_venue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = "a" * 40
    monkeypatch.setattr(
        "src.data.raw_venue_preflight._git",
        lambda _repo, *args: commit if args == ("rev-parse", "HEAD") else "",
    )

    def passing(spec: VenueProbeSpec) -> VenueProbeResult:
        return VenueProbeResult(spec.venue, spec.websocket_url, True, 0.1, "ack")

    report = run_raw_venue_preflight(
        repository_root=tmp_path,
        expected_commit=commit,
        probe=passing,
    )
    assert report.qualified
    assert tuple(item.venue for item in report.venues) == SUPPORTED_VENUES

    failed = run_raw_venue_preflight(
        repository_root=tmp_path,
        expected_commit=commit,
        probe=lambda spec: VenueProbeResult(
            spec.venue,
            spec.websocket_url,
            spec.venue != "deribit",
            0.1,
            "ack" if spec.venue != "deribit" else "timeout",
        ),
    )
    assert not failed.qualified


def test_dirty_or_wrong_commit_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.data.raw_venue_preflight._git",
        lambda _repo, *args: "b" * 40 if args == ("rev-parse", "HEAD") else "dirty",
    )
    report = run_raw_venue_preflight(
        repository_root=tmp_path,
        expected_commit="a" * 40,
        venues=("okx",),
        probe=lambda spec: VenueProbeResult(
            spec.venue, spec.websocket_url, True, 0.1, "ack"
        ),
    )
    assert not report.qualified
    assert not report.working_tree_clean


def test_report_is_immutable(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    from src.data.raw_venue_preflight import RawVenuePreflightReport

    value = RawVenuePreflightReport(
        1,
        "2026-08-26T00:00:00+00:00",
        True,
        "a" * 40,
        "a" * 40,
        True,
        (VenueProbeResult("okx", "wss://example", True, 0.1, "ack"),),
    )
    write_raw_venue_preflight_report(report_path, value)
    assert json.loads(report_path.read_text(encoding="utf-8"))["qualified"] is True
    with pytest.raises(FileExistsError):
        write_raw_venue_preflight_report(report_path, value)


def test_invalid_venue_sets_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nonempty and unique"):
        run_raw_venue_preflight(
            repository_root=tmp_path,
            expected_commit="a" * 40,
            venues=(),
        )
    with pytest.raises(ValueError, match="unsupported venue"):
        venue_probe_spec("unknown")
