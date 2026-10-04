from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import OutputDirDep, SettingsDep
from quant_system.api.schemas.common import dataframe_records
from quant_system.api.schemas.options import (
    OptionsAlertsEvaluationResponse,
    OptionsBullPutSignalResponse,
    OptionsChainResponse,
    OptionsContractScoreResponse,
    OptionsEarningsCrushResponse,
    OptionsExpirationsResponse,
    OptionsFearScoreResponse,
    OptionsGreeksResponse,
    OptionsHedgeAdvisorResponse,
    OptionsImpliedVolatilityResponse,
    OptionsIvRankResponse,
    OptionsMarketSentimentResponse,
    OptionsResearchHealthCheckResponse,
    OptionsSimulationResponse,
    OptionsSnapshotResponse,
    OptionsStrategyBuildResponse,
    OptionsStrategyRankResponse,
    OptionsUnusualActivityResponse,
    OptionsVolSmileResponse,
    OptionsVolSurfaceResponse,
)
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
from quant_system.options.buy_side_market_data import (
    load_buy_side_market_inputs,
    resolve_buy_side_underlying_quote,
)
from quant_system.options.data_refresh import fetch_screener_events
from quant_system.options.dividend_events import load_dividend_events
from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.iv_history import resolve_options_market_session
from quant_system.options.iv_units import (
    IV_UNIT_PERCENT,
    frame_unit,
    to_percent,
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
    OptionsScreenerResult,
)
from quant_system.options.screener import run_options_screener
from quant_system.options.universe import OptionsUniverse

router = APIRouter()


@router.get("/options/expirations", response_model=OptionsExpirationsResponse)
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


@router.get("/options/chain", response_model=OptionsChainResponse)
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
    # The chain surface contract is percent, while provider frames and cache
    # reads carry the canonical ratio. Convert explicitly instead of leaking
    # the internal unit.
    unit = frame_unit(frame)
    contracts = dataframe_records(frame)
    if unit != IV_UNIT_PERCENT:
        for contract in contracts:
            contract["implied_volatility"] = to_percent(
                contract.get("implied_volatility"),
                unit=unit,
            )
    return {
        "ticker": ticker.upper().strip(),
        "source": "futu",
        "expiration": expiration,
        "option_type": option_type.upper(),
        "implied_volatility_unit": "percent",
        "contracts": contracts,
    }


@router.get("/options/snapshot/{ticker}", response_model=OptionsSnapshotResponse)
def options_snapshot(
    ticker: str,
    settings: SettingsDep,
    provider: str = "futu",
    expiration: str | None = None,
) -> dict:
    active_provider = _build_options_provider(settings, provider)
    try:
        return compute_options_snapshot(active_provider, ticker, expiration=expiration)
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_options_snapshot", "message": str(exc)},
        ) from exc


@router.get("/options/tools/vol-surface/{ticker}", response_model=OptionsVolSurfaceResponse)
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


@router.get("/options/tools/vol-smile/{ticker}", response_model=OptionsVolSmileResponse)
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


@router.post("/options/tools/greeks", response_model=OptionsGreeksResponse)
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


@router.post(
    "/options/tools/implied-volatility",
    response_model=OptionsImpliedVolatilityResponse,
)
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


@router.post("/options/tools/simulate", response_model=OptionsSimulationResponse)
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


@router.post(
    "/options/tools/strategy/build",
    response_model=OptionsStrategyBuildResponse,
)
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


@router.post(
    "/options/tools/score-contracts",
    response_model=OptionsContractScoreResponse,
)
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


@router.post(
    "/options/tools/strategy/rank",
    response_model=OptionsStrategyRankResponse,
)
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


@router.post(
    "/options/tools/bull-put-signal",
    response_model=OptionsBullPutSignalResponse,
)
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


@router.post("/options/tools/fear-score", response_model=OptionsFearScoreResponse)
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


@router.post("/options/tools/iv-rank", response_model=OptionsIvRankResponse)
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


@router.post(
    "/options/tools/market-sentiment",
    response_model=OptionsMarketSentimentResponse,
)
def options_market_sentiment(payload: dict, settings: SettingsDep) -> dict:
    vix = payload.get("vix")
    assumptions: list[str] = []
    if vix is None:
        from quant_system.options.vix_data import load_vix_history

        series, _vix3m = load_vix_history(settings.options_radar.vix_history_path)
        if not series.empty:
            last = series.dropna()
            if not last.empty:
                vix = float(last.iloc[-1])
                assumptions.append(
                    f"vix from local vix_history.csv last close {last.index.max().date()}"
                )
    try:
        result = compute_market_sentiment(
            vix=vix,
            put_call_ratio=payload.get("put_call_ratio"),
            advance_decline_ratio=payload.get("advance_decline_ratio"),
            percent_above_200dma=payload.get("percent_above_200dma"),
        )
    except ValueError as exc:
        if str(exc) == "insufficient_inputs":
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "insufficient_inputs",
                    "message": "market sentiment needs at least one real input",
                },
            ) from exc
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_market_sentiment_request", "message": str(exc)},
        ) from exc
    except TypeError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_market_sentiment_request", "message": str(exc)},
        ) from exc
    if assumptions:
        result["assumptions"] = list(result.get("assumptions") or []) + assumptions
    return result


@router.post(
    "/options/tools/earnings-crush",
    response_model=OptionsEarningsCrushResponse,
)
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


@router.post(
    "/options/tools/hedge-advisor",
    response_model=OptionsHedgeAdvisorResponse,
)
def options_hedge_advisor(payload: dict) -> dict:
    try:
        return build_hedge_advisor(
            ticker=str(payload["ticker"]),
            shares=payload["shares"],
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


@router.post(
    "/options/tools/unusual-activity",
    response_model=OptionsUnusualActivityResponse,
)
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


@router.post("/options/tools/watchlist", response_model=OptionsWatchlistResponse)
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


@router.post(
    "/options/tools/alerts/evaluate",
    response_model=OptionsAlertsEvaluationResponse,
)
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


@router.post(
    "/options/tools/health-check",
    response_model=OptionsResearchHealthCheckResponse,
)
def options_health_check(payload: dict, output_dir: OutputDirDep) -> dict:
    try:
        ticker = str(payload.get("ticker") or "").strip().upper()
        profiles = _watchlist_store(output_dir).list()
        if ticker:
            profiles = [profile for profile in profiles if profile.get("ticker") == ticker]
        return research_health_check(
            profiles=profiles,
            stale_after_days=int(payload.get("stale_after_days", 14)),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_health_check_request", "message": str(exc)},
        ) from exc


@router.post("/options/screener", response_model=OptionsScreenerResult)
def options_screener(
    request: OptionsScreenerConfig,
    settings: SettingsDep,
) -> dict:
    active_provider = _build_options_provider(settings, request.provider)
    market_session = _server_market_session()
    market_regime = load_market_regime(
        settings.options_radar.vix_history_path,
        run_date=market_session.isoformat(),
    )
    try:
        ticker, _ = active_provider.normalize_symbol(request.ticker)
        is_etf = _is_curated_etf(settings, ticker)
        calendar = EarningsCalendar.load(settings.options_radar.earnings_calendar_path)
        dividend_event = (
            load_dividend_events(settings.options_radar.dividend_events_path).get(ticker)
            if request.strategy_type == "covered_call" else None
        )
        missing_earnings = not is_etf and calendar.next_earnings(ticker, market_session) is None
        missing_dividend = request.strategy_type == "covered_call" and (
            dividend_event is None
            or (dividend_event[0] is None and dividend_event[1] != 0.0)
            or (dividend_event[0] is not None and dividend_event[0] < market_session)
        )
        event_notes = []
        if missing_earnings or missing_dividend:
            try:
                earnings_date, fresh_dividend = fetch_screener_events(
                    ticker, earnings=missing_earnings, dividends=missing_dividend,
                )
                if earnings_date is not None and earnings_date >= market_session:
                    calendar = EarningsCalendar(
                        {**calendar.dates_by_ticker, ticker: [earnings_date]}
                    )
                    event_notes.append("Earnings date read from yfinance for the requested ticker.")
                if fresh_dividend is not None:
                    dividend_event = fresh_dividend
                    event_notes.append(
                        "Dividend evidence read from yfinance for the requested ticker."
                    )
            except RuntimeError as exc:
                event_notes.append(str(exc))
        result = run_options_screener(
            provider=active_provider,
            config=request,
            market_regime=market_regime,
            risk_free_rate=settings.options_radar.risk_free_rate,
            run_date=market_session.isoformat(),
            iv_history_dir=settings.options_radar.output_dir / "iv_history",
            earnings_calendar=calendar,
            is_etf=is_etf,
            dividend_event=dividend_event,
        )
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_options_screen", "message": str(exc)},
        ) from exc
    payload = result.model_dump(mode="json")
    payload["assumptions"] = [*payload.get("assumptions", []), *event_notes]
    return payload


def _is_curated_etf(settings, ticker: str) -> bool:
    try:
        universe = OptionsUniverse.load(settings.options_radar.curated_universe_path)
    except (OSError, ValueError):
        return False
    normalized = ticker.upper().strip()
    return any(
        item.ticker == normalized and item.source in {"core_etf", "sector_etf"} for item in universe
    )


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
    market_session = _server_market_session()
    if pd.Timestamp(request.target_date).date() <= market_session:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_buy_side_target_date",
                "message": "target date must be after the current market session",
            },
        )
    try:
        underlying_quote = resolve_buy_side_underlying_quote(
            active_provider.fetch_underlying_snapshot(request.ticker),
            ticker=request.ticker,
            market_session=market_session,
            observed_at=datetime.now(UTC).isoformat(),
        )
        spot_price = underlying_quote.spot_price
        if request.target_price <= spot_price:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_buy_side_target_price",
                    "message": "bullish target price must be above current spot",
                },
            )
        start_expiration, end_expiration = _buy_side_expiration_window(
            request,
            market_session=market_session,
        )
        option_chain = active_provider.fetch_option_quotes_range(
            request.ticker,
            start_expiration=start_expiration,
            end_expiration=end_expiration,
            option_type="ALL",
        )
        option_chain_observed_at = datetime.now(UTC).isoformat()
        market_inputs = load_buy_side_market_inputs(
            provider=active_provider,
            ticker=request.ticker,
            option_chain=option_chain,
            spot_price=spot_price,
            market_session=market_session,
            option_chain_observed_at=option_chain_observed_at,
            iv_history_dir=settings.options_radar.output_dir / "iv_history",
        )
        _validate_buy_side_scenario_horizon(
            request,
            market_inputs.option_chain,
            market_session=market_session,
        )
        market_regime = load_market_regime(
            settings.options_radar.vix_history_path,
            run_date=market_session.isoformat(),
        )
        result = run_buy_side_decision(
            market_inputs.option_chain,
            request.to_decision_request(
                spot_price=spot_price,
                iv_rank=market_inputs.iv_rank,
                historical_volatility=market_inputs.historical_volatility,
                as_of_date=market_session.isoformat(),
                iv_measure=market_inputs.iv_measure,
            ),
            market_regime=market_regime,
            max_recommendations=request.max_recommendations,
        )
    except FutuProviderError as exc:
        raise _futu_http_exception(exc) from exc
    except ValueError as exc:
        if str(exc).startswith("buy_side_volatility_data_unavailable"):
            code = "buy_side_volatility_data_unavailable"
        elif str(exc).startswith("buy_side_market_data_unavailable"):
            code = "buy_side_market_data_unavailable"
        else:
            code = "invalid_buy_side_assistant"
        raise HTTPException(
            status_code=(
                503
                if code
                in {
                    "buy_side_volatility_data_unavailable",
                    "buy_side_market_data_unavailable",
                }
                else 400
            ),
            detail={"code": code, "message": str(exc)},
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
            settings.futu.cache_dir / "options_cache.duckdb" if settings.futu.use_cache else None
        ),
    )


def _watchlist_store(output_dir) -> LocalWatchlistStore:
    return LocalWatchlistStore(output_dir / "options_tools" / "watchlist.json")


def _server_market_session(*, now: datetime | None = None) -> date:
    return resolve_options_market_session(now=now)


def _buy_side_expiration_window(
    request: BuySideAssistantRequest,
    *,
    market_session: date,
) -> tuple[str, str]:
    if request.preferred_dte_range is not None:
        min_dte, max_dte = request.preferred_dte_range
    elif request.view_type.startswith("long_term"):
        min_dte, max_dte = 180, 760
    elif request.view_type == "short_term_speculative_bullish":
        min_dte, max_dte = 7, 60
    else:
        min_dte, max_dte = 14, 120
    start_expiration = (
        (pd.Timestamp(market_session) + pd.Timedelta(days=min_dte)).date().isoformat()
    )
    end_expiration = (pd.Timestamp(market_session) + pd.Timedelta(days=max_dte)).date().isoformat()
    return start_expiration, end_expiration


def _validate_buy_side_scenario_horizon(
    request: BuySideAssistantRequest,
    option_chain: pd.DataFrame,
    *,
    market_session: date,
) -> None:
    calls = option_chain.loc[option_chain["option_type"].astype(str).str.upper() == "CALL"]
    dtes = [
        (date.fromisoformat(str(expiry)) - market_session).days
        for expiry in calls["expiry"].dropna().unique()
    ]
    if not dtes:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_buy_side_scenario", "message": "no call DTE"},
        )
    requested_days = [
        *request.scenario_days_passed,
        *(item.days_passed for item in request.user_scenarios),
    ]
    if max(requested_days, default=0) > min(dtes):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_buy_side_scenario",
                "message": "scenario horizon exceeds available option DTE",
            },
        )


def _futu_http_exception(exc: FutuProviderError) -> HTTPException:
    status_code = 502
    if exc.code in {
        "opend_unavailable",
        "provider_timeout",
        "provider_unavailable",
        "rate_limited",
    }:
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
