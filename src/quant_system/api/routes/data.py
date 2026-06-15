from __future__ import annotations

from fastapi import APIRouter

from quant_system.api.dependencies import OutputDirDep, SettingsDep
from quant_system.api.errors import provider_unavailable_400
from quant_system.api.schemas.common import dataframe_records
from quant_system.api.schemas.data import OHLCVResponse, SymbolsResponse
from quant_system.data.provider_factory import (
    DataProviderUnavailableError,
    build_ohlcv_provider,
)
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.data.storage import LocalDataStorage

router = APIRouter()

_DEFAULT_SAMPLE_SYMBOLS = ["SPY", "QQQ", "IWM", "TLT", "GLD"]
_DEFAULT_LIVE_SYMBOLS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "TLT",
    "GLD",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
]


@router.get("/symbols", response_model=SymbolsResponse)
def symbols(output_dir: OutputDirDep, settings: SettingsDep) -> dict:
    storage = LocalDataStorage(base_dir=output_dir)
    if storage.parquet_path.exists():
        frame = storage.load_ohlcv()
        local_symbols = sorted(frame["symbol"].dropna().astype(str).str.upper().unique())
        if local_symbols:
            return {"symbols": local_symbols, "source": "local"}
    # Reflect the actual active provider so the UI does not silently fall
    # back to the 5-ticker sample basket when Tiingo/Futu are available.
    _, active_source = build_ohlcv_provider(settings)
    base_label = active_source.split()[0]
    if base_label in {"tiingo", "futu"}:
        return {
            "symbols": _DEFAULT_LIVE_SYMBOLS,
            "source": f"{base_label} (default basket)",
        }
    return {"symbols": _DEFAULT_SAMPLE_SYMBOLS, "source": "sample"}


@router.get("/ohlcv", response_model=OHLCVResponse)
def ohlcv(
    symbol: str,
    start: str,
    end: str,
    output_dir: OutputDirDep,
    settings: SettingsDep,
    provider: str | None = None,
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
        try:
            active_provider, source = build_ohlcv_provider(settings, requested=provider)
        except DataProviderUnavailableError as exc:
            raise provider_unavailable_400(exc) from exc
        try:
            frame = active_provider.fetch_ohlcv([normalized_symbol], start=start, end=end)
        except Exception as exc:
            if provider is not None:
                raise provider_unavailable_400(
                    DataProviderUnavailableError(provider, exc.__class__.__name__)
                ) from exc
            frame = SampleOHLCVProvider().fetch_ohlcv(
                [normalized_symbol],
                start=start,
                end=end,
            )
            source = f"sample ({source} failed: {exc.__class__.__name__})"
    return {
        "symbol": normalized_symbol,
        "source": source,
        "rows": dataframe_records(
            frame[["timestamp", "open", "high", "low", "close", "volume"]]
        ),
    }
