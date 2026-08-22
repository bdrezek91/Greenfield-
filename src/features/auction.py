"""ATAS-like footprint, imbalance, Volume Profile, VWAP, and AVWAP."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from src.data.normalized_event import NormalizedMarketEvent
from src.features.order_flow import OrderFlowError


@dataclass(frozen=True, slots=True)
class VolumeProfile:
    poc: float
    vah: float
    val: float
    total_volume: float
    value_area_volume: float
    value_area_fraction: float


def footprint_frame(
    rows: list[NormalizedMarketEvent],
    *,
    symbol: str,
    bucket_ms: int,
    price_tick: str,
    imbalance_ratio: float = 3.0,
) -> pd.DataFrame:
    if bucket_ms <= 0 or imbalance_ratio <= 0:
        raise ValueError("bucket_ms and imbalance_ratio must be positive")
    tick = Decimal(price_tick)
    if not tick.is_finite() or tick <= 0:
        raise ValueError("price_tick must be positive and finite")
    records = []
    for row in rows:
        _validate_trade(row, symbol)
        price = Decimal(row.price or "")
        level = (price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick
        records.append(
            {
                "bucket": row.event_ts_ms // bucket_ms * bucket_ms,
                "price_level_decimal": level,
                "side": row.side,
                "size_decimal": Decimal(row.size or ""),
                "receive_ns": row.receive_ts_ns,
            }
        )
    if not records:
        return pd.DataFrame()
    output = []
    frame = pd.DataFrame(records)
    for bucket, bucket_rows in frame.groupby("bucket", sort=True):
        levels: dict[Decimal, dict[str, Decimal | int]] = {}
        for record in bucket_rows.to_dict(orient="records"):
            level = record["price_level_decimal"]
            values = levels.setdefault(
                level, {"buy": Decimal(0), "sell": Decimal(0), "receive_ns": 0}
            )
            values[str(record["side"])] += record["size_decimal"]
            values["receive_ns"] = max(int(values["receive_ns"]), int(record["receive_ns"]))
        ordered = sorted(levels)
        buy_flags = []
        sell_flags = []
        for level in ordered:
            lower_sell = Decimal(levels.get(level - tick, {}).get("sell", 0))
            upper_buy = Decimal(levels.get(level + tick, {}).get("buy", 0))
            buy = Decimal(levels[level]["buy"])
            sell = Decimal(levels[level]["sell"])
            buy_ratio = float(buy / lower_sell) if lower_sell > 0 else 0.0
            sell_ratio = float(sell / upper_buy) if upper_buy > 0 else 0.0
            buy_flags.append(buy_ratio >= imbalance_ratio)
            sell_flags.append(sell_ratio >= imbalance_ratio)
            receive_ns = int(levels[level]["receive_ns"])
            output.append(
                {
                    "bucket": int(bucket),
                    "price_level": float(level),
                    "timestamp": pd.Timestamp(
                        max((int(bucket) + bucket_ms) * 1_000_000, receive_ns),
                        unit="ns",
                        tz="UTC",
                    ),
                    "max_source_timestamp": pd.Timestamp(receive_ns, unit="ns", tz="UTC"),
                    "buy_volume": float(buy),
                    "sell_volume": float(sell),
                    "total_volume": float(buy + sell),
                    "delta": float(buy - sell),
                    "diagonal_buy_ratio": buy_ratio,
                    "diagonal_sell_ratio": sell_ratio,
                }
            )
        buy_runs = _stack_runs(buy_flags)
        sell_runs = _stack_runs(sell_flags)
        offset = len(output) - len(ordered)
        for index in range(len(ordered)):
            output[offset + index]["stacked_buy_levels"] = buy_runs[index]
            output[offset + index]["stacked_sell_levels"] = sell_runs[index]
    return pd.DataFrame(output).drop(columns="bucket")


def volume_profile(
    footprint: pd.DataFrame, *, value_area_fraction: float = 0.70
) -> VolumeProfile:
    if not 0 < value_area_fraction <= 1:
        raise ValueError("value_area_fraction must be in (0, 1]")
    if footprint.empty or not {"price_level", "total_volume"}.issubset(footprint.columns):
        raise ValueError("footprint requires price_level and total_volume")
    grouped = footprint.groupby("price_level")["total_volume"].sum().sort_index()
    if (grouped < 0).any() or float(grouped.sum()) <= 0:
        raise ValueError("profile volume must be positive")
    prices = list(grouped.index)
    volumes = [float(value) for value in grouped]
    poc_index = max(range(len(prices)), key=lambda index: (volumes[index], -index))
    selected = {poc_index}
    accumulated = volumes[poc_index]
    target = sum(volumes) * value_area_fraction
    lower, upper = poc_index - 1, poc_index + 1
    while accumulated < target and (lower >= 0 or upper < len(prices)):
        lower_volume = volumes[lower] if lower >= 0 else -1.0
        upper_volume = volumes[upper] if upper < len(prices) else -1.0
        if upper_volume > lower_volume:
            selected.add(upper)
            accumulated += upper_volume
            upper += 1
        else:
            selected.add(lower)
            accumulated += lower_volume
            lower -= 1
    return VolumeProfile(
        poc=float(prices[poc_index]),
        vah=float(prices[max(selected)]),
        val=float(prices[min(selected)]),
        total_volume=float(sum(volumes)),
        value_area_volume=float(accumulated),
        value_area_fraction=value_area_fraction,
    )


def anchored_vwap_frame(
    rows: list[NormalizedMarketEvent],
    *,
    symbol: str,
    anchor_ts_ms: int | None = None,
) -> pd.DataFrame:
    filtered = []
    for row in rows:
        _validate_trade(row, symbol)
        if anchor_ts_ms is None or row.event_ts_ms >= anchor_ts_ms:
            filtered.append(row)
    filtered.sort(
        key=lambda row: (
            row.event_ts_ms,
            row.receive_ts_ns,
            row.receive_sequence,
            row.row_index,
        )
    )
    cumulative_volume = Decimal(0)
    cumulative_notional = Decimal(0)
    output = []
    for event_ts_ms, group in _group_by_event_timestamp(filtered):
        max_receive = 0
        for row in group:
            size, price = Decimal(row.size or ""), Decimal(row.price or "")
            cumulative_volume += size
            cumulative_notional += size * price
            max_receive = max(max_receive, row.receive_ts_ns)
        output.append(
            {
                "timestamp": pd.Timestamp(
                    max(event_ts_ms * 1_000_000, max_receive), unit="ns", tz="UTC"
                ),
                "max_source_timestamp": pd.Timestamp(max_receive, unit="ns", tz="UTC"),
                "vwap": float(cumulative_notional / cumulative_volume),
                "cumulative_volume": float(cumulative_volume),
            }
        )
    return pd.DataFrame(output)


def _group_by_event_timestamp(rows: list[NormalizedMarketEvent]):
    index = 0
    while index < len(rows):
        end = index + 1
        while end < len(rows) and rows[end].event_ts_ms == rows[index].event_ts_ms:
            end += 1
        yield rows[index].event_ts_ms, rows[index:end]
        index = end


def _stack_runs(flags: list[bool]) -> list[int]:
    output = [0] * len(flags)
    start = 0
    while start < len(flags):
        if not flags[start]:
            start += 1
            continue
        end = start
        while end < len(flags) and flags[end]:
            end += 1
        run = end - start
        for index in range(start, end):
            output[index] = run
        start = end
    return output


def _validate_trade(row: NormalizedMarketEvent, symbol: str) -> None:
    if row.record_type != "trade" or row.symbol != symbol:
        raise OrderFlowError("auction features accept one normalized trade stream")
