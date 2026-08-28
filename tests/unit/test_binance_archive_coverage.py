from __future__ import annotations

import json
from pathlib import Path

from src.data.binance_archive_coverage import audit_binance_archive_coverage


def _json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_coverage_requires_all_six_trade_streams_and_three_gold_symbols(
    tmp_path: Path,
) -> None:
    for market in ("spot", "futures-um"):
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            _json(
                tmp_path
                / "external"
                / "binance-public-data"
                / market
                / "trades"
                / symbol
                / f"{symbol}-trades-2026-01.zip.manifest.json",
                {
                    "identity": (
                        f"{market.replace('-', '/')}:monthly:trades:"
                        f"{symbol}:none:2026-01"
                    )
                },
            )
            _json(
                tmp_path
                / "silver"
                / "binance-public-data"
                / "v1"
                / f"market={market}"
                / "dataset=trades"
                / f"symbol={symbol}"
                / "period=2026-01"
                / "part.manifest.json",
                {
                    "market": market,
                    "dataset": "trades",
                    "symbol": symbol,
                    "period": "2026-01",
                    "row_count": 10,
                },
            )
            _json(
                tmp_path
                / "gold"
                / "binance-public-data"
                / "v1"
                / f"symbol={symbol}"
                / "period=2026-01"
                / "manifest.json",
                {"parameters": {"symbol": symbol, "period": "2026-01"}},
            )

    report = audit_binance_archive_coverage(tmp_path)

    assert report["common_spot_perp_periods"]["trades"] == ["2026-01"]
    assert report["common_spot_perp_periods"]["aggTrades"] == []
    assert report["gold_complete_btc_eth_sol_periods"] == ["2026-01"]
    assert report["silver_rows"]["spot:trades:BTCUSDT"] == 10


def test_coverage_does_not_claim_incomplete_common_period(tmp_path: Path) -> None:
    _json(
        tmp_path
        / "silver"
        / "binance-public-data"
        / "v1"
        / "market=spot"
        / "dataset=trades"
        / "symbol=BTCUSDT"
        / "period=2026-01"
        / "part.manifest.json",
        {
            "market": "spot",
            "dataset": "trades",
            "symbol": "BTCUSDT",
            "period": "2026-01",
            "row_count": 1,
        },
    )

    report = audit_binance_archive_coverage(tmp_path)

    assert report["common_spot_perp_periods"]["trades"] == []
