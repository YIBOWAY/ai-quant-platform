from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import OutputDirDep, SettingsDep
from quant_system.api.schemas.common import dataframe_records
from quant_system.api.schemas.options_radar import (
    OptionsStrategyTemplatesResponse,
    OptionsWatchlistResponse,
)
from quant_system.data.providers.futu import FutuMarketDataProvider, FutuProviderError
from quant_system.options.buy_side_decision import (
    BuySideAssistantRequest,
    BuySideAssistantResponse,
    run_buy_side_decision,
)
from quant_system.options.local_research import (
    LocalWatchlistStore,
    build_bull_put_spread_signal,
    build_hedge_advisor,
    compute_fear_score,
    compute_iv_rank_dashboard,
    compute_market_sentiment,
    detect_unusual_options_activity,
    estimate_earnings_iv_crush,
    evaluate_local_alerts,
    rank_option_contracts,
    rank_strategy_templates,
    research_health_check,
)
from quant_system.options.local_tools import (
    build_strategy_from_template,
    build_vol_smile,
    build_vol_surface,
    calculate_greeks,
    compute_options_snapshot,
    implied_volatility,
    simulate_option_position,
    strategy_templates,
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


@router.get("/options/snapshot/{ticker}")
def options_snapshot(
    ticker: str,
    settings: SettingsDep,
    provider: str = "futu",
) -> dict:
    active_provider = _build_options_provider(settings, provider)
    try:
        return compute_options_snapshot(active_provider, ticker)
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_options_snapshot", "message": str(exc)},
        ) from exc


@router.get("/options/tools/vol-surface/{ticker}")
def options_vol_surface(
    ticker: str,
    settings: SettingsDep,
    provider: str = "futu",
    max_expirations: int = 4,
) -> dict:
    active_provider = _build_options_provider(settings, provider)
    try:
        return build_vol_surface(
            active_provider,
            ticker,
            max_expirations=max(1, min(max_expirations, 8)),
        )
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_vol_surface", "message": str(exc)},
        ) from exc


@router.get("/options/tools/vol-smile/{ticker}")
def options_vol_smile(
    ticker: str,
    settings: SettingsDep,
    provider: str = "futu",
    expiry: str | None = None,
) -> dict:
    active_provider = _build_options_provider(settings, provider)
    try:
        return build_vol_smile(active_provider, ticker, expiry=expiry)
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_vol_smile", "message": str(exc)},
        ) from exc


@router.post("/options/tools/greeks")
def options_greeks(payload: dict) -> dict:
    try:
        return calculate_greeks(
            spot=float(payload["spot"]),
            strike=float(payload["strike"]),
            expiry_days=int(payload["expiry_days"]),
            iv=float(payload["iv"]),
            option_type=str(payload["option_type"]).lower(),  # type: ignore[arg-type]
            rate=float(payload.get("rate", 0.04)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_greeks_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/implied-volatility")
def options_implied_volatility(payload: dict) -> dict:
    try:
        iv = implied_volatility(
            market_price=float(payload["market_price"]),
            spot=float(payload["spot"]),
            strike=float(payload["strike"]),
            expiry_days=int(payload["expiry_days"]),
            option_type=str(payload["option_type"]).lower(),  # type: ignore[arg-type]
            rate=float(payload.get("rate", 0.04)),
        )
        return {"implied_volatility": iv}
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_implied_volatility_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/simulate")
def options_simulate(payload: dict) -> dict:
    try:
        return simulate_option_position(
            symbol=str(payload["symbol"]),
            spot=float(payload["spot"]),
            legs=list(payload["legs"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_simulation_request", "message": str(exc)},
        ) from exc


@router.get("/options/tools/strategy/templates", response_model=OptionsStrategyTemplatesResponse)
def options_strategy_templates() -> dict:
    return {"templates": strategy_templates()}


@router.post("/options/tools/strategy/build")
def options_strategy_build(payload: dict) -> dict:
    try:
        mode = str(payload.get("mode", "template"))
        if mode != "template":
            raise ValueError("only mode=template is supported locally")
        return build_strategy_from_template(
            template_id=str(payload["template_id"]),
            spot=float(payload["spot"]),
            expiry_days=int(payload["expiry_days"]),
            strikes=[float(item) for item in payload["strikes"]],
            iv=float(payload.get("iv", 0.30)),
            symbol=str(payload.get("symbol", "LOCAL")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_strategy_build_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/score-contracts")
def options_score_contracts(payload: dict) -> dict:
    try:
        return rank_option_contracts(
            contracts=list(payload["contracts"]),
            spot=float(payload["spot"]),
            objective=str(payload.get("objective", "balanced")),  # type: ignore[arg-type]
            top_n=int(payload["top_n"]) if "top_n" in payload else None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_contract_score_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/strategy/rank")
def options_strategy_rank(payload: dict) -> dict:
    try:
        return rank_strategy_templates(
            market_view=str(payload.get("market_view", "bullish")),
            spot=float(payload["spot"]),
            expiry_days=int(payload["expiry_days"]),
            strikes=[float(item) for item in payload["strikes"]],
            iv=float(payload.get("iv", 0.30)),
            symbol=str(payload.get("symbol", "LOCAL")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_strategy_rank_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/bull-put-signal")
def options_bull_put_signal(payload: dict) -> dict:
    try:
        return build_bull_put_spread_signal(
            contracts=list(payload["contracts"]),
            spot=float(payload["spot"]),
            fear_score=float(payload["fear_score"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_bull_put_signal_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/fear-score")
def options_fear_score(payload: dict) -> dict:
    try:
        return compute_fear_score(
            vix=payload.get("vix"),
            iv_rank=payload.get("iv_rank"),
            rsi_14=payload.get("rsi_14"),
            options_volume_anomaly=payload.get("options_volume_anomaly"),
            put_call_ratio=payload.get("put_call_ratio"),
            consecutive_down_days=payload.get("consecutive_down_days"),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_fear_score_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/iv-rank")
def options_iv_rank(payload: dict) -> dict:
    try:
        return compute_iv_rank_dashboard(
            ticker=str(payload["ticker"]),
            current_iv=payload.get("current_iv"),
            history=list(payload.get("history", [])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_iv_rank_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/market-sentiment")
def options_market_sentiment(payload: dict) -> dict:
    try:
        return compute_market_sentiment(
            vix=payload.get("vix"),
            put_call_ratio=payload.get("put_call_ratio"),
            advance_decline_ratio=payload.get("advance_decline_ratio"),
            percent_above_200dma=payload.get("percent_above_200dma"),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_market_sentiment_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/earnings-crush")
def options_earnings_crush(payload: dict) -> dict:
    try:
        return estimate_earnings_iv_crush(
            ticker=str(payload["ticker"]),
            current_iv=float(payload["current_iv"]),
            historical_pre_post_iv=list(payload.get("historical_pre_post_iv", [])),
            implied_move_pct=payload.get("implied_move_pct"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_earnings_crush_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/hedge-advisor")
def options_hedge_advisor(payload: dict) -> dict:
    try:
        return build_hedge_advisor(
            ticker=str(payload["ticker"]),
            shares=int(payload["shares"]),
            cost_basis=float(payload["cost_basis"]),
            spot=float(payload["spot"]),
            purpose=str(payload.get("purpose", "protect")),
            contracts=list(payload.get("contracts", [])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_hedge_advisor_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/unusual-activity")
def options_unusual_activity(payload: dict) -> dict:
    try:
        return detect_unusual_options_activity(
            list(payload["contracts"]),
            min_volume_oi_ratio=float(payload.get("min_volume_oi_ratio", 2.0)),
            min_volume=float(payload.get("min_volume", 100)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_unusual_activity_request", "message": str(exc)},
        ) from exc


@router.get("/options/tools/watchlist", response_model=OptionsWatchlistResponse)
def options_watchlist(output_dir: OutputDirDep) -> dict:
    return {"watchlist": _watchlist_store(output_dir).list()}


@router.post("/options/tools/watchlist")
def options_watchlist_add(payload: dict, output_dir: OutputDirDep) -> dict:
    try:
        watchlist = _watchlist_store(output_dir).add(
            str(payload["ticker"]),
            tags=list(payload.get("tags", [])),
        )
        return {"watchlist": watchlist}
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_watchlist_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/alerts/evaluate")
def options_alerts_evaluate(payload: dict) -> dict:
    try:
        return evaluate_local_alerts(
            alerts=list(payload["alerts"]),
            context=dict(payload["context"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_alert_evaluation_request", "message": str(exc)},
        ) from exc


@router.post("/options/tools/health-check")
def options_health_check(payload: dict) -> dict:
    try:
        return research_health_check(
            profiles=list(payload.get("profiles", [])),
            today=payload.get("today"),
            stale_after_days=int(payload.get("stale_after_days", 14)),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_health_check_request", "message": str(exc)},
        ) from exc


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
        option_quotes_cache_path=(
            settings.futu.cache_dir / "options_cache.duckdb"
            if settings.futu.use_cache
            else None
        ),
    )


def _watchlist_store(output_dir) -> LocalWatchlistStore:
    return LocalWatchlistStore(output_dir / "options_tools" / "watchlist.json")


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
    if exc.code in {"opend_unavailable", "provider_timeout", "rate_limited"}:
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
