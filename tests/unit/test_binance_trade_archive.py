from __future__ import annotations

import hashlib
import json
import zipfile
from types import SimpleNamespace

import pandas as pd

from src.data.binance_trade_archive import (
    BinanceTradeArchiveIdentity,
    normalize_binance_trade_archive,
    normalize_trade_chunk,
)


def test_normalize_trade_chunk_handles_spot_microseconds_and_signed_flow() -> None:
    raw = pd.DataFrame(
        {
            "id": ["1", "2"],
            "price": ["100", "101"],
            "qty": ["2", "3"],
            "quoteQty": ["200", "303"],
            "time": ["1782864000000000", "1782864000001000"],
            "isBuyerMaker": ["True", "False"],
            "isBestMatch": ["True", "True"],
        }
    )
    result = normalize_trade_chunk(
        raw, BinanceTradeArchiveIdentity("spot", "trades", "BTCUSDT", "2026-07")
    )
    assert result["timestamp"].dt.tz is not None
    assert result["signed_quantity"].tolist() == [-2.0, 3.0]
    assert result["quote_quantity"].tolist() == [200.0, 303.0]


def test_normalize_aggtrades_derives_quote_quantity() -> None:
    raw = pd.DataFrame(
        {
            "agg_trade_id": ["10"],
            "price": ["50"],
            "quantity": ["4"],
            "first_trade_id": ["11"],
            "last_trade_id": ["14"],
            "transact_time": ["1782864000000"],
            "is_buyer_maker": ["false"],
        }
    )
    result = normalize_trade_chunk(
        raw,
        BinanceTradeArchiveIdentity("futures/um", "aggTrades", "ETHUSDT", "2026-07"),
    )
    assert result["trade_id"].tolist() == [10]
    assert result["first_trade_id"].tolist() == [11]
    assert result["last_trade_id"].tolist() == [14]
    assert result["quote_quantity"].tolist() == [200.0]


def test_archive_normalization_is_streaming_evidenced_and_idempotent(tmp_path) -> None:
    data_dir = tmp_path / "data"
    source = (
        data_dir / "external/binance-public-data/spot/trades/BTCUSDT/BTCUSDT-trades-2026-07.zip"
    )
    source.parent.mkdir(parents=True)
    csv = (
        "id,price,qty,quoteQty,time,isBuyerMaker,isBestMatch\n"
        "1,100,2,200,1782864000000000,true,true\n"
        "2,101,3,303,1782864000001000,false,true\n"
    )
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("BTCUSDT-trades-2026-07.csv", csv)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    source.with_suffix(".zip.manifest.json").write_text(
        json.dumps(
            {
                "identity": "spot:monthly:trades:BTCUSDT:none:2026-07",
                "content_sha256": digest,
            }
        ),
        encoding="utf-8",
    )

    def disk(_path):
        return SimpleNamespace(free=10_000_000)
    output, changed, metadata = normalize_binance_trade_archive(
        source,
        data_dir=data_dir,
        minimum_free_bytes=1_000,
        chunksize=1,
        disk_usage=disk,
    )
    assert changed is True
    assert metadata["row_count"] == 2
    frame = pd.read_parquet(output)
    assert frame["signed_quantity"].tolist() == [-2.0, 3.0]

    reused, changed, repeated = normalize_binance_trade_archive(
        source,
        data_dir=data_dir,
        minimum_free_bytes=1_000,
        chunksize=1,
        disk_usage=disk,
    )
    assert reused == output
    assert changed is False
    assert repeated["output_sha256"] == metadata["output_sha256"]
