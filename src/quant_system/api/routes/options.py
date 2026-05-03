from __future__ import annotations

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.common import dataframe_records
from quant_system.data.providers.futu import FutuMarketDataProvider, FutuProviderError
from quant_system.options.models import OptionsScreenerConfig
from quant_system.options.screener import run_options_screener

router = APIRouter()


@router.get("/options/expirations")
def option_expirations(
    settings: SettingsDep,
    ticker: str,
    provider: str = "futu",
) -> dict:
    active_provider = _build_options_provider(settings, provider)
    try:
        frame = active_provider.fetch_option_expirations(ticker)
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    return {
        "ticker": ticker.upper().strip(),
        "source": "futu",
        "expirations": dataframe_records(frame),
    }


@router.get("/options/chain")
def option_chain(
    settings: SettingsDep,
    ticker: str,
    expiration: str,
    option_type: str = "ALL",
    provider: str = "futu",
) -> dict:
    active_provider = _build_options_provider(settings, provider)
    try:
        frame = active_provider.fetch_option_quotes(
            ticker,
            expiration=expiration,
            option_type=option_type,
        )
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    return {
        "ticker": ticker.upper().strip(),
        "source": "futu",
        "expiration": expiration,
        "option_type": option_type.upper(),
        "contracts": dataframe_records(frame),
    }


@router.post("/options/screener")
def options_screener(
    request: OptionsScreenerConfig,
    settings: SettingsDep,
) -> dict:
    active_provider = _build_options_provider(settings, request.provider)
    try:
        result = run_options_screener(provider=active_provider, config=request)
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_options_screen", "message": str(exc)},
        ) from exc
    return result.model_dump(mode="json")


def _build_options_provider(settings, provider: str) -> FutuMarketDataProvider:
    if provider != "futu":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_options_provider",
                "message": "Options Screener currently supports provider=futu only",
            },
        )
    if not settings.futu.options_enabled:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "futu_options_disabled",
                "message": "Futu options data is disabled in settings",
            },
        )
    return FutuMarketDataProvider(
        host=settings.futu.host,
        port=settings.futu.port,
        request_timeout_seconds=settings.futu.request_timeout_seconds,
    )


def _futu_http_exception(exc: FutuProviderError) -> HTTPException:
    status_code = 502
    if exc.code in {"opend_unavailable", "provider_timeout"}:
        status_code = 503
    elif exc.code in {"invalid_symbol", "unsupported_interval"}:
        status_code = 400
    elif exc.code == "permission_denied":
        status_code = 403
    elif exc.code == "no_data":
        status_code = 404
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message},
    )
