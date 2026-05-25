from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import SettingsDep
from quant_system.data.providers.futu import FutuMarketDataProvider, FutuProviderError
from quant_system.options.data_refresh import (
    refresh_earnings_calendar,
    refresh_options_universe,
    refresh_vix_history,
)
from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.market_regime import load_market_regime
from quant_system.options.models import OptionsScreenerConfig, StrategyType
from quant_system.options.radar import (
    OptionsRadarCandidate,
    OptionsRadarConfig,
    run_options_radar,
)
from quant_system.options.radar_storage import RadarSnapshotStore
from quant_system.options.rate_limiter import RateLimitedFutuProvider, TokenBucket
from quant_system.options.sample_provider import SampleOptionsProvider
from quant_system.options.universe import OptionsUniverse

router = APIRouter()


@router.get("/options/daily-scan/dates")
def options_daily_scan_dates(settings: SettingsDep) -> dict:
    return {"dates": RadarSnapshotStore(settings.options_radar.output_dir).list_dates()}


@router.post("/options/refresh/universe")
def options_refresh_universe(settings: SettingsDep, payload: dict) -> dict:
    source = str(payload.get("source", "public"))
    try:
        return refresh_options_universe(settings.options_radar.universe_path, source=source)
    except ValueError as exc:
        raise _refresh_request_error(str(exc)) from exc
    except Exception as exc:
        raise _refresh_runtime_error("universe", exc) from exc


@router.post("/options/refresh/earnings")
def options_refresh_earnings(settings: SettingsDep, payload: dict) -> dict:
    source = str(payload.get("source", "public"))
    top = int(payload.get("top", settings.options_radar.universe_top_n))
    today = _optional_date(payload.get("today"))
    try:
        return refresh_earnings_calendar(
            universe_path=settings.options_radar.universe_path,
            output_path=settings.options_radar.earnings_calendar_path,
            source=source,
            top=top,
            today=today,
        )
    except (TypeError, ValueError) as exc:
        raise _refresh_request_error(str(exc)) from exc
    except Exception as exc:
        raise _refresh_runtime_error("earnings", exc) from exc


@router.post("/options/refresh/vix")
def options_refresh_vix(settings: SettingsDep, payload: dict) -> dict:
    source = str(payload.get("source", "public"))
    lookback_days = int(payload.get("lookback_days", 400))
    end = _optional_date(payload.get("end"))
    try:
        return refresh_vix_history(
            settings.options_radar.vix_history_path,
            source=source,
            lookback_days=lookback_days,
            end=end,
        )
    except (TypeError, ValueError) as exc:
        raise _refresh_request_error(str(exc)) from exc
    except Exception as exc:
        raise _refresh_runtime_error("vix", exc) from exc


@router.post("/options/daily-scan/run")
def options_daily_scan_run(settings: SettingsDep, payload: dict) -> dict:
    provider_name = str(payload.get("provider", settings.options_radar.provider)).lower().strip()
    if provider_name not in {"sample", "futu"}:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_radar_provider",
                "message": "provider must be sample or futu",
            },
        )
    top = int(payload.get("top", min(settings.options_radar.universe_top_n, 10)))
    strategies = _parse_strategies(payload.get("strategies"))
    run_date = payload.get("run_date")
    try:
        universe = OptionsUniverse.load(settings.options_radar.universe_path, top_n=max(top, 1))
        provider = _build_radar_provider(settings, provider_name)
        report = run_options_radar(
            provider=provider,
            universe=universe,
            config=OptionsRadarConfig(
                base_screen_config=_build_radar_screen_config(settings),
                strategies=strategies,
                universe_top_n=max(top, 1),
                top_per_ticker=5,
            ),
            iv_history_dir=settings.options_radar.output_dir / "iv_history",
            earnings_calendar=EarningsCalendar.load(settings.options_radar.earnings_calendar_path),
            run_date=str(run_date) if run_date else None,
            market_regime=load_market_regime(
                settings.options_radar.vix_history_path,
                run_date=run_date,
            ),
        )
        data_path, meta_path = RadarSnapshotStore(settings.options_radar.output_dir).write(report)
    except FutuProviderError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except (TypeError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_radar_scan_request", "message": str(exc)},
        ) from exc
    return {
        "run_date": report.run_date,
        "provider": provider_name,
        "universe_size": report.universe_size,
        "scanned_tickers": report.scanned_tickers,
        "failed_tickers": report.failed_tickers,
        "candidate_count": len(report.candidates),
        "data_path": str(data_path),
        "meta_path": str(meta_path),
    }


@router.get("/options/daily-scan/symbol/{ticker}")
def options_daily_scan_symbol(
    settings: SettingsDep,
    ticker: str,
    date: str | None = None,
    top: int = 100,
) -> dict:
    store = RadarSnapshotStore(settings.options_radar.output_dir)
    active_date = date or store.latest_date()
    if active_date is None:
        raise _missing_snapshot()
    try:
        report = store.read(active_date)
    except FileNotFoundError as exc:
        raise _missing_snapshot() from exc
    normalized = ticker.upper().strip()
    candidates = [
        candidate
        for candidate in report.candidates
        if candidate.ticker.upper().strip() == normalized
    ][: max(top, 0)]
    return {
        "ticker": normalized,
        "run_date": report.run_date,
        "candidate_count": len(candidates),
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
    }


@router.get("/options/daily-scan")
def options_daily_scan(
    settings: SettingsDep,
    date: str | None = None,
    strategy: str = "all",
    sector: str | None = None,
    top: int = 50,
    dte_bucket: str | None = None,
) -> dict:
    store = RadarSnapshotStore(settings.options_radar.output_dir)
    active_date = date or store.latest_date()
    if active_date is None:
        raise _missing_snapshot()
    try:
        report = store.read(active_date)
    except FileNotFoundError as exc:
        raise _missing_snapshot() from exc
    candidates = [
        candidate
        for candidate in report.candidates
        if _matches(candidate, strategy=strategy, sector=sector, dte_bucket=dte_bucket)
    ][: max(top, 0)]
    return {
        "run_date": report.run_date,
        "universe_size": report.universe_size,
        "scanned_tickers": report.scanned_tickers,
        "failed_tickers": report.failed_tickers,
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
    }


def _missing_snapshot() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "no_radar_snapshot",
            "message": "No options radar snapshot is available for the requested date.",
        },
    )


def _matches(
    candidate: OptionsRadarCandidate,
    *,
    strategy: str,
    sector: str | None,
    dte_bucket: str | None,
) -> bool:
    if strategy != "all" and candidate.strategy != strategy:
        return False
    if sector and (candidate.sector or "").lower() != sector.lower():
        return False
    if dte_bucket:
        dte = candidate.candidate.days_to_expiry
        if dte is None:
            return False
        low, high = _parse_dte_bucket(dte_bucket)
        return low <= dte <= high
    return True


def _parse_dte_bucket(value: str) -> tuple[int, int]:
    mapping = {
        "7-21": (7, 21),
        "21-45": (21, 45),
        "45-60": (45, 60),
    }
    return mapping.get(value, (0, 10_000))


def _candidate_payload(candidate: OptionsRadarCandidate) -> dict:
    option = candidate.candidate
    return {
        "ticker": candidate.ticker,
        "sector": candidate.sector,
        "strategy": candidate.strategy,
        "symbol": option.symbol,
        "expiry": option.expiry,
        "strike": option.strike,
        "mid": option.mid,
        "annualized_yield": option.annualized_yield,
        "implied_volatility": option.implied_volatility,
        "iv_rank": candidate.iv_rank,
        "delta": option.delta,
        "open_interest": option.open_interest,
        "spread_pct": option.spread_pct,
        "earnings_date": option.earnings_date,
        "earnings_in_window": candidate.earnings_in_window,
        "global_score": candidate.global_score,
        "rating": option.rating,
        "notes": option.notes,
        "market_regime": candidate.market_regime,
        "market_regime_penalty": candidate.market_regime_penalty,
    }


def _parse_strategies(value: object) -> tuple[StrategyType, ...]:
    if value is None:
        return ("sell_put", "covered_call")
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    else:
        raw_items = [str(item).strip() for item in list(value)]  # type: ignore[arg-type]
    parsed = tuple(item for item in raw_items if item)
    invalid = [item for item in parsed if item not in {"sell_put", "covered_call"}]
    if invalid:
        raise ValueError(f"unsupported strategies: {', '.join(invalid)}")
    return parsed or ("sell_put", "covered_call")  # type: ignore[return-value]


def _build_radar_provider(settings, provider_name: str):
    if provider_name == "sample":
        return SampleOptionsProvider()
    futu_provider = FutuMarketDataProvider(
        host=settings.futu.host,
        port=settings.futu.port,
        request_timeout_seconds=settings.futu.request_timeout_seconds,
        option_quotes_cache_path=(
            settings.futu.cache_dir / "options_cache.duckdb"
            if settings.futu.use_cache
            else None
        ),
    )
    futu_provider.snapshot_batch_size = settings.options_radar.snapshot_batch_size
    return RateLimitedFutuProvider(
        futu_provider,
        bucket=TokenBucket(
            max_tokens=settings.options_radar.futu_rate_limit_per_30s,
            refill_seconds=30,
        ),
    )


def _optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value))


def _refresh_request_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "invalid_options_refresh_request", "message": message},
    )


def _refresh_runtime_error(kind: str, error: Exception) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": f"{kind}_refresh_failed",
            "message": f"{type(error).__name__}: {error}",
        },
    )


def _build_radar_screen_config(settings) -> OptionsScreenerConfig:
    return OptionsScreenerConfig(
        ticker="SPY",
        strategy_type="sell_put",
        min_dte=settings.options_radar.min_dte_for_radar,
        max_dte=settings.options_radar.max_dte_for_radar,
        max_delta=0.8,
        min_premium=0.10,
        min_apr=0.0,
        max_spread_pct=0.25,
        min_open_interest=20,
        max_hv_iv=1.0,
        trend_filter=True,
        hv_iv_filter=False,
        provider="futu",
        top_n=100,
        min_mid_price=0.10,
        min_avg_daily_volume=100_000,
        min_market_cap=0.0,
        avoid_earnings_within_days=7,
    )
