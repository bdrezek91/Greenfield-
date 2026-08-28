"""Coverage evidence for Binance public archive Bronze, Silver, and Gold."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def audit_binance_archive_coverage(data_dir: Path) -> dict[str, Any]:
    root = Path(data_dir)
    bronze = _bronze_periods(root)
    silver, silver_rows = _silver_periods(root)
    gold = _gold_periods(root)
    common_trade_periods: dict[str, list[str]] = {}
    for dataset in ("trades", "aggTrades"):
        identities = [
            f"{market}:{dataset}:{symbol}"
            for market in ("spot", "futures-um")
            for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
        ]
        period_sets = [set(silver.get(identity, [])) for identity in identities]
        common_trade_periods[dataset] = sorted(set.intersection(*period_sets))
    gold_complete = sorted(
        period
        for period, symbols in gold.items()
        if symbols == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    )
    return {
        "schema_version": 1,
        "bronze_downloaded_periods": bronze,
        "silver_normalized_periods": silver,
        "silver_rows": silver_rows,
        "common_spot_perp_periods": common_trade_periods,
        "gold_symbols_by_period": {
            period: sorted(symbols) for period, symbols in sorted(gold.items())
        },
        "gold_complete_btc_eth_sol_periods": gold_complete,
        "limitations": [
            "coverage lists retained local artifacts, not provider-wide availability",
            "missing periods are not forward-filled or synthesized",
            "Gold is OOS-eligible only after independent quality and lineage gates",
        ],
    }


def _bronze_periods(root: Path) -> dict[str, list[str]]:
    base = root / "external" / "binance-public-data"
    periods: dict[str, set[str]] = defaultdict(set)
    for manifest in base.rglob("*.zip.manifest.json") if base.exists() else ():
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        fields = str(raw.get("identity", "")).split(":")
        if len(fields) != 6:
            raise ValueError(f"invalid Binance Bronze manifest identity: {manifest}")
        market, _, dataset, symbol, _, period = fields
        periods[f"{market.replace('/', '-')}:{dataset}:{symbol}"].add(period)
    return {identity: sorted(values) for identity, values in sorted(periods.items())}


def _silver_periods(root: Path) -> tuple[dict[str, list[str]], dict[str, int]]:
    base = root / "silver" / "binance-public-data" / "v1"
    periods: dict[str, set[str]] = defaultdict(set)
    rows: dict[str, int] = defaultdict(int)
    for manifest in base.rglob("part.manifest.json") if base.exists() else ():
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        required = {"market", "dataset", "symbol", "period", "row_count"}
        if not required.issubset(raw):
            raise ValueError(f"incomplete Binance Silver manifest: {manifest}")
        identity = f"{raw['market']}:{raw['dataset']}:{raw['symbol']}"
        periods[identity].add(str(raw["period"]))
        rows[identity] += int(raw["row_count"])
    return (
        {identity: sorted(values) for identity, values in sorted(periods.items())},
        dict(sorted(rows.items())),
    )


def _gold_periods(root: Path) -> dict[str, set[str]]:
    base = root / "gold" / "binance-public-data" / "v1"
    periods: dict[str, set[str]] = defaultdict(set)
    for manifest in base.rglob("manifest.json") if base.exists() else ():
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        parameters = raw.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"incomplete Binance Gold manifest: {manifest}")
        period = str(parameters.get("period", ""))
        symbol = str(parameters.get("symbol", ""))
        if not period or symbol not in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
            raise ValueError(f"invalid Binance Gold identity: {manifest}")
        periods[period].add(symbol)
    return periods
