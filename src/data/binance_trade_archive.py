"""Streaming normalization of checksum-verified Binance trade archives."""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.data.binance_public_archive import sha256_file

TRADE_SCHEMA = pa.schema(
    [
        pa.field("timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("exchange", pa.string(), nullable=False),
        pa.field("market", pa.string(), nullable=False),
        pa.field("dataset", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("trade_id", pa.int64(), nullable=False),
        pa.field("first_trade_id", pa.int64()),
        pa.field("last_trade_id", pa.int64()),
        pa.field("price", pa.float64(), nullable=False),
        pa.field("quantity", pa.float64(), nullable=False),
        pa.field("quote_quantity", pa.float64(), nullable=False),
        pa.field("buyer_is_maker", pa.bool_(), nullable=False),
        pa.field("best_match", pa.bool_()),
        pa.field("signed_quantity", pa.float64(), nullable=False),
    ]
)


@dataclass(frozen=True, slots=True)
class BinanceTradeArchiveIdentity:
    market: str
    dataset: str
    symbol: str
    period: str

    def __post_init__(self) -> None:
        if self.market not in {"spot", "futures/um"}:
            raise ValueError("unsupported Binance trade archive market")
        if self.dataset not in {"trades", "aggTrades"}:
            raise ValueError("unsupported Binance trade archive dataset")
        if self.symbol not in {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
            raise ValueError("unsupported Binance trade archive symbol")

    @property
    def normalized_market(self) -> str:
        return self.market.replace("/", "-")

    def output_path(self, data_dir: Path) -> Path:
        return Path(data_dir).joinpath(
            "silver",
            "binance-public-data",
            "v1",
            f"market={self.normalized_market}",
            f"dataset={self.dataset}",
            f"symbol={self.symbol}",
            f"period={self.period}",
            "part.parquet",
        )


def identity_from_archive_manifest(source: Path) -> BinanceTradeArchiveIdentity:
    manifest_path = source.with_suffix(source.suffix + ".manifest.json")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = str(raw.get("identity", ""))
    fields = identity.split(":")
    if len(fields) != 6:
        raise ValueError(f"invalid Binance archive identity: {identity}")
    market, cadence, dataset, symbol, interval, period = fields
    if cadence != "monthly" or interval != "none":
        raise ValueError("trade normalization requires a monthly non-kline archive")
    return BinanceTradeArchiveIdentity(market, dataset, symbol, period)


def normalize_binance_trade_archive(
    source: Path,
    *,
    data_dir: Path,
    minimum_free_bytes: int,
    chunksize: int = 500_000,
    disk_usage: Callable[[Path], Any] = shutil.disk_usage,
) -> tuple[Path, bool, dict[str, Any]]:
    """Stream one ZIP into deterministic Parquet and return output metadata."""
    source = Path(source)
    if chunksize < 1:
        raise ValueError("chunksize must be positive")
    identity = identity_from_archive_manifest(source)
    output = identity.output_path(data_dir)
    manifest_path = output.with_suffix(".manifest.json")
    source_sha256 = sha256_file(source)
    if output.exists() and manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("source_sha256") == source_sha256 and existing.get(
            "output_sha256"
        ) == sha256_file(output):
            return output, False, existing
        raise ValueError(f"existing normalized archive evidence mismatch: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".parquet.part")
    writer: pq.ParquetWriter | None = None
    rows = 0
    minimum_timestamp: pd.Timestamp | None = None
    maximum_timestamp: pd.Timestamp | None = None
    previous_key: tuple[pd.Timestamp, int] | None = None
    try:
        with zipfile.ZipFile(source) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError("Binance trade archive must contain exactly one CSV")
            with archive.open(members[0]) as csv_file:
                chunks = pd.read_csv(csv_file, dtype=str, chunksize=chunksize)
                for raw_chunk in chunks:
                    chunk = normalize_trade_chunk(raw_chunk, identity)
                    if chunk.empty:
                        continue
                    keys = list(zip(chunk["timestamp"], chunk["trade_id"], strict=True))
                    if previous_key is not None and keys[0] <= previous_key:
                        raise ValueError("Binance trade archive is not strictly ordered")
                    if any(right <= left for left, right in zip(keys, keys[1:], strict=False)):
                        raise ValueError("Binance trade archive has duplicate or unordered IDs")
                    previous_key = keys[-1]
                    chunk_min = chunk["timestamp"].iloc[0]
                    chunk_max = chunk["timestamp"].iloc[-1]
                    minimum_timestamp = (
                        chunk_min
                        if minimum_timestamp is None
                        else min(minimum_timestamp, chunk_min)
                    )
                    maximum_timestamp = (
                        chunk_max
                        if maximum_timestamp is None
                        else max(maximum_timestamp, chunk_max)
                    )
                    table = pa.Table.from_pandas(chunk, schema=TRADE_SCHEMA, preserve_index=False)
                    if writer is None:
                        writer = pq.ParquetWriter(
                            temp,
                            TRADE_SCHEMA,
                            compression="zstd",
                            use_dictionary=("exchange", "market", "dataset", "symbol"),
                        )
                    writer.write_table(table)
                    rows += len(chunk)
                    if int(disk_usage(output.parent).free) < minimum_free_bytes:
                        raise OSError("normalization free-space reserve breached")
        if writer is None or rows == 0:
            raise ValueError("Binance trade archive contains no data rows")
        writer.close()
        writer = None
        with temp.open("rb+") as value:
            os.fsync(value.fileno())
        temp.replace(output)
    finally:
        if writer is not None:
            writer.close()
        temp.unlink(missing_ok=True)
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "exchange": "binance",
        "market": identity.normalized_market,
        "dataset": identity.dataset,
        "symbol": identity.symbol,
        "period": identity.period,
        "source_path": str(source),
        "source_sha256": source_sha256,
        "output_path": str(output),
        "output_sha256": sha256_file(output),
        "row_count": rows,
        "min_timestamp_utc": minimum_timestamp.isoformat() if minimum_timestamp else None,
        "max_timestamp_utc": maximum_timestamp.isoformat() if maximum_timestamp else None,
        "normalized_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_json_atomic(manifest_path, metadata)
    return output, True, metadata


def normalize_trade_chunk(
    raw: pd.DataFrame,
    identity: BinanceTradeArchiveIdentity,
) -> pd.DataFrame:
    columns = {_canonical_column(name): name for name in raw.columns}
    if identity.dataset == "trades":
        trade_id = _required(raw, columns, "id", "trade_id")
        first_trade_id = pd.Series(pd.NA, index=raw.index, dtype="Int64")
        last_trade_id = pd.Series(pd.NA, index=raw.index, dtype="Int64")
        quantity = _required(raw, columns, "qty", "quantity")
        timestamp = _required(raw, columns, "time", "timestamp")
    else:
        trade_id = _required(raw, columns, "agg_trade_id", "aggregate_trade_id")
        first_trade_id = pd.to_numeric(
            _required(raw, columns, "first_trade_id"), errors="raise"
        ).astype("Int64")
        last_trade_id = pd.to_numeric(
            _required(raw, columns, "last_trade_id"), errors="raise"
        ).astype("Int64")
        quantity = _required(raw, columns, "quantity", "qty")
        timestamp = _required(raw, columns, "transact_time", "time", "timestamp")
    timestamp_numeric = pd.to_numeric(timestamp, errors="raise").astype("int64")
    unit = "us" if int(timestamp_numeric.abs().max()) >= 10**15 else "ms"
    parsed_timestamp = pd.to_datetime(timestamp_numeric, unit=unit, utc=True)
    price = pd.to_numeric(_required(raw, columns, "price"), errors="raise").astype("float64")
    parsed_quantity = pd.to_numeric(quantity, errors="raise").astype("float64")
    quote_source = _optional(raw, columns, "quote_qty", "quote_quantity")
    quote_quantity = (
        pd.to_numeric(quote_source, errors="raise").astype("float64")
        if quote_source is not None
        else price * parsed_quantity
    )
    buyer_is_maker = _parse_bool(_required(raw, columns, "is_buyer_maker", "buyer_is_maker"))
    best_source = _optional(raw, columns, "is_best_match", "best_match")
    best_match = (
        _parse_bool(best_source).astype("boolean")
        if best_source is not None
        else pd.Series(pd.NA, index=raw.index, dtype="boolean")
    )
    result = pd.DataFrame(
        {
            "timestamp": parsed_timestamp,
            "exchange": pd.Series("binance", index=raw.index, dtype="string"),
            "market": pd.Series(identity.normalized_market, index=raw.index, dtype="string"),
            "dataset": pd.Series(identity.dataset, index=raw.index, dtype="string"),
            "symbol": pd.Series(identity.symbol, index=raw.index, dtype="string"),
            "trade_id": pd.to_numeric(trade_id, errors="raise").astype("int64"),
            "first_trade_id": first_trade_id,
            "last_trade_id": last_trade_id,
            "price": price,
            "quantity": parsed_quantity,
            "quote_quantity": quote_quantity,
            "buyer_is_maker": buyer_is_maker,
            "best_match": best_match,
            "signed_quantity": parsed_quantity.where(~buyer_is_maker, -parsed_quantity),
        }
    )
    if (result["price"] <= 0).any() or (result["quantity"] <= 0).any():
        raise ValueError("Binance trade archive contains non-positive price/quantity")
    return result


def _canonical_column(value: object) -> str:
    result: list[str] = []
    for index, char in enumerate(str(value).strip()):
        if char.isupper() and index and result[-1] != "_":
            result.append("_")
        result.append(char.lower())
    return "".join(result).replace(" ", "_")


def _required(raw: pd.DataFrame, columns: dict[str, object], *names: str) -> pd.Series:
    value = _optional(raw, columns, *names)
    if value is None:
        raise ValueError(f"Binance trade archive missing required column: {names}")
    return value


def _optional(raw: pd.DataFrame, columns: dict[str, object], *names: str) -> pd.Series | None:
    for name in names:
        original = columns.get(name)
        if original is not None:
            return raw[original]
    return None


def _parse_bool(value: pd.Series) -> pd.Series:
    normalized = value.astype("string").str.strip().str.lower()
    if not normalized.isin({"true", "false"}).all():
        raise ValueError("Binance trade archive contains an invalid boolean")
    return normalized.eq("true")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temp.replace(path)
