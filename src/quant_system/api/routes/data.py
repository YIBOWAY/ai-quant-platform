from __future__ import annotations

from fastapi import APIRouter

from quant_system.api.dependencies import OutputDirDep
from quant_system.api.schemas.common import dataframe_records
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.data.storage import LocalDataStorage

router = APIRouter()

_DEFAULT_SAMPLE_SYMBOLS = ["SPY", "QQQ", "IWM", "TLT", "GLD"]


@router.get("/symbols")
def symbols(output_dir: OutputDirDep) -> dict:
    storage = LocalDataStorage(base_dir=output_dir)
    if storage.parquet_path.exists():
        frame = storage.load_ohlcv()
        local_symbols = sorted(frame["symbol"].dropna().astype(str).str.upper().unique())
        if local_symbols:
            return {"symbols": local_symbols, "source": "local"}
    return {"symbols": _DEFAULT_SAMPLE_SYMBOLS, "source": "sample"}


@router.get("/ohlcv")
def ohlcv(
    symbol: str,
    start: str,
    end: str,
    output_dir: OutputDirDep,
) -> dict:
    normalized_symbol = symbol.upper().strip()
    storage = LocalDataStorage(base_dir=output_dir)
    frame = None
    source = "sample"
    if storage.parquet_path.exists():
        local = storage.load_ohlcv(symbols=[normalized_symbol], start=start, end=end)
        if not local.empty:
            frame = local
            source = "local"
    if frame is None:
        frame = SampleOHLCVProvider().fetch_ohlcv([normalized_symbol], start=start, end=end)
    return {
        "symbol": normalized_symbol,
        "source": source,
        "rows": dataframe_records(
            frame[["timestamp", "open", "high", "low", "close", "volume"]]
        ),
    }
