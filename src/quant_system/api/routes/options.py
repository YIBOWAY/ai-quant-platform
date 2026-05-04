from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.common import dataframe_records
from quant_system.data.providers.futu import FutuMarketDataProvider, FutuProviderError
from quant_system.options.buy_side_decision import (
    BuySideAssistantRequest,
    BuySideAssistantResponse,
    run_buy_side_decision,
)
from quant_system.options.market_regime import load_market_regime
from quant_system.options.models import (
    OptionsScreenerConfig,
)
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
    market_regime = load_market_regime(settings.options_radar.vix_history_path)
    try:
        result = run_options_screener(
            provider=active_provider,
            config=request,
            market_regime=market_regime,
        )
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_options_screen", "message": str(exc)},
        ) from exc
    return result.model_dump(mode="json")


@router.post(
    "/options/buy-side/assistant",
    response_model=BuySideAssistantResponse,
    responses={
        400: {"description": "Unsupported provider or invalid parameter combination."},
        403: {"description": "Futu quote permission is insufficient."},
        404: {"description": "Ticker not found or no option chain is available."},
        422: {"description": "Invalid thesis input."},
        503: {"description": "Futu OpenD or provider is unavailable."},
    },
)
def buy_side_assistant(
    request: BuySideAssistantRequest,
    settings: SettingsDep,
) -> BuySideAssistantResponse:
    active_provider = _build_options_provider(settings, request.provider)
    try:
        spot_price = request.spot_price or _resolve_spot_price(
            active_provider,
            request.ticker,
        )
        start_expiration, end_expiration = _buy_side_expiration_window(request)
        option_chain = active_provider.fetch_option_quotes_range(
            request.ticker,
            start_expiration=start_expiration,
            end_expiration=end_expiration,
            option_type="CALL",
        )
        market_regime = load_market_regime(
            settings.options_radar.vix_history_path,
            run_date=request.as_of_date,
        )
        result = run_buy_side_decision(
            option_chain,
            request.to_decision_request(spot_price=spot_price),
            market_regime=market_regime,
            max_recommendations=request.max_recommendations,
        )
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_buy_side_assistant", "message": str(exc)},
        ) from exc
    return BuySideAssistantResponse.model_validate(result.model_dump(mode="json"))


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


def _resolve_spot_price(provider: FutuMarketDataProvider, ticker: str) -> float:
    snapshot = provider.fetch_underlying_snapshot(ticker)
    for key in ("last", "close", "price"):
        value = snapshot.get(key)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    raise FutuProviderError("no_data", f"no usable underlying price for {ticker}")


def _buy_side_expiration_window(request: BuySideAssistantRequest) -> tuple[str, str]:
    as_of = (
        pd.Timestamp(request.as_of_date).date()
        if request.as_of_date
        else pd.Timestamp.today().date()
    )
    if request.preferred_dte_range is not None:
        min_dte, max_dte = request.preferred_dte_range
    elif request.view_type.startswith("long_term"):
        min_dte, max_dte = 180, 760
    elif request.view_type == "short_term_speculative_bullish":
        min_dte, max_dte = 7, 60
    else:
        min_dte, max_dte = 14, 120
    start_expiration = (pd.Timestamp(as_of) + pd.Timedelta(days=min_dte)).date().isoformat()
    end_expiration = (pd.Timestamp(as_of) + pd.Timedelta(days=max_dte)).date().isoformat()
    return start_expiration, end_expiration


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
