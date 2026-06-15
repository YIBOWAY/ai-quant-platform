from __future__ import annotations

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import SettingsDep
from quant_system.api.errors import provider_unavailable_400
from quant_system.api.schemas.common import dataframe_records
from quant_system.api.schemas.market_data import MarketDataHistoryResponse
from quant_system.data.provider_factory import (
    DataProviderUnavailableError,
    build_ohlcv_provider,
)
from quant_system.data.providers.futu import FutuProviderError
from quant_system.data.providers.sample import SampleOHLCVProvider

router = APIRouter()


@router.get("/market-data/history", response_model=MarketDataHistoryResponse)
def market_data_history(
    settings: SettingsDep,
    ticker: str,
    start: str,
    end: str,
    freq: str = "1d",
    provider: str | None = None,
) -> dict:
    symbol = ticker.upper().strip()
    requested_provider = provider or settings.data.default_data_provider
    if _is_intraday(freq) and requested_provider != "futu":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_interval",
                "provider": requested_provider,
                "interval": freq,
                "message": f"{requested_provider} provider only supports daily OHLCV",
            },
        )
    try:
        active_provider, source = build_ohlcv_provider(settings, requested=provider)
    except DataProviderUnavailableError as exc:
        raise provider_unavailable_400(exc) from exc
    try:
        frame = active_provider.fetch_ohlcv([symbol], start=start, end=end, interval=freq)
    except FutuProviderError as exc:
        if provider is None and not _is_intraday(freq):
            frame = SampleOHLCVProvider().fetch_ohlcv(
                [symbol],
                start=start,
                end=end,
                interval=freq,
            )
            source = f"sample ({source} failed: {exc.code})"
        else:
            raise HTTPException(
                status_code=_status_for_futu_error(exc.code),
                detail={"code": exc.code, "message": exc.message},
            ) from exc
    except Exception as exc:
        if provider is None and not _is_intraday(freq):
            frame = SampleOHLCVProvider().fetch_ohlcv(
                [symbol],
                start=start,
                end=end,
                interval=freq,
            )
            source = f"sample ({source} failed: {exc.__class__.__name__})"
        else:
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "market_data_provider_failed",
                    "message": f"{source} provider failed: {exc.__class__.__name__}",
                },
            ) from exc

    return {
        "symbol": symbol,
        "ticker": symbol,
        "source": source,
        "frequency": freq,
        "row_count": len(frame),
        "rows": dataframe_records(
            frame[["timestamp", "open", "high", "low", "close", "volume"]]
        ),
        "metadata": {
            "provider": source,
            "requested_provider": requested_provider,
            "fetched_at": (
                frame["knowledge_ts"].max().isoformat()
                if "knowledge_ts" in frame.columns and not frame.empty
                else None
            ),
        },
    }


def _status_for_futu_error(code: str) -> int:
    if code in {"opend_unavailable", "provider_timeout"}:
        return 503
    if code in {"invalid_symbol", "unsupported_interval"}:
        return 400
    if code == "permission_denied":
        return 403
    if code == "no_data":
        return 404
    return 502


def _is_intraday(freq: str) -> bool:
    return freq.lower().strip() != "1d"
