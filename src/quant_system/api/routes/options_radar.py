from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.options_radar import (
    OptionsDailyScanDatesResponse,
    OptionsDailyScanResponse,
    OptionsDailyScanStatusResponse,
    OptionsDailyScanSymbolResponse,
    OptionsDailyScanTaskStateResponse,
    OptionsRefreshResponse,
)
from quant_system.options.daily_task import (
    OptionsDailyTaskRequest,
    queued_options_daily_task_status,
    run_options_daily_task,
    write_options_daily_task_status,
)
from quant_system.options.data_refresh import (
    refresh_earnings_calendar,
    refresh_options_universe,
    refresh_vix_history,
)
from quant_system.options.iv_history import resolve_options_market_session
from quant_system.options.radar import OptionsRadarCandidate, select_recommendations
from quant_system.options.radar_storage import RECOMMENDATION_LIMIT, RadarSnapshotStore
from quant_system.options.scan_lock import (
    RADAR_SCAN_LOCK_FILENAME,
    OptionsRadarScanLocked,
    options_radar_scan_lock,
)
from quant_system.options.seller_score import (
    latest_us_market_session,
    resolve_recommendation_quote,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/options/daily-scan/dates", response_model=OptionsDailyScanDatesResponse)
def options_daily_scan_dates(settings: SettingsDep) -> dict:
    return {"dates": RadarSnapshotStore(settings.options_radar.output_dir).list_dates()}


@router.get("/options/daily-scan/status", response_model=OptionsDailyScanStatusResponse)
def options_daily_scan_status(settings: SettingsDep) -> dict:
    status_path = settings.options_radar.output_dir / "daily_task_status.json"
    if not status_path.exists():
        return {"exists": False, "status_path": str(status_path), "status": None}
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"daily task status file is invalid JSON: {status_path}",
        ) from exc
    if not isinstance(status, dict):
        raise HTTPException(
            status_code=500,
            detail=f"daily task status file must contain an object: {status_path}",
        )
    status = _project_interrupted_options_task(settings, status)
    return {"exists": True, "status_path": str(status_path), "status": status}


def _project_interrupted_options_task(settings, status: dict) -> dict:
    if status.get("status") not in {"queued", "running"} or status.get("terminal") is True:
        return status
    lock_path = settings.options_radar.output_dir / RADAR_SCAN_LOCK_FILENAME
    if lock_path.exists():
        probe = options_radar_scan_lock(settings.options_radar.output_dir)
        try:
            probe.__enter__()
        except OptionsRadarScanLocked:
            return status
        else:
            latest_status = None
            try:
                status_path = settings.options_radar.output_dir / "daily_task_status.json"
                latest_payload = json.loads(status_path.read_text(encoding="utf-8"))
                if isinstance(latest_payload, dict):
                    latest_status = latest_payload
            except (OSError, json.JSONDecodeError):
                pass
            finally:
                probe.__exit__(None, None, None)
            if latest_status is not None and (
                latest_status.get("status") != status.get("status")
                or latest_status.get("updated_at") != status.get("updated_at")
            ):
                return latest_status
    now = _utc_now().isoformat()
    projected = dict(status)
    projected.update(
        {
            "status": "failed",
            "terminal": True,
            "current_step": "failed",
            "failed_step": status.get("current_step") or "unknown",
            "error": "OptionsRadarScanInterrupted: no active scan lock",
            "updated_at": now,
            "finished_at": now,
        }
    )
    return projected


@router.post("/options/refresh/universe", response_model=OptionsRefreshResponse)
def options_refresh_universe(settings: SettingsDep, payload: dict) -> dict:
    source = str(payload.get("source", "public"))
    _reject_sample_refresh(source)
    try:
        return refresh_options_universe(settings.options_radar.universe_path, source=source)
    except ValueError as exc:
        raise _refresh_request_error(str(exc)) from exc
    except Exception as exc:
        raise _refresh_runtime_error("universe", exc) from exc


@router.post("/options/refresh/earnings", response_model=OptionsRefreshResponse)
def options_refresh_earnings(settings: SettingsDep, payload: dict) -> dict:
    source = str(payload.get("source", "public"))
    _reject_sample_refresh(source)
    today = _optional_date(payload.get("today"))
    try:
        return refresh_earnings_calendar(
            universe_path=settings.options_radar.curated_universe_path,
            output_path=settings.options_radar.earnings_calendar_path,
            source=source,
            top=34,
            today=today,
        )
    except (TypeError, ValueError) as exc:
        raise _refresh_request_error(str(exc)) from exc
    except Exception as exc:
        raise _refresh_runtime_error("earnings", exc) from exc


@router.post("/options/refresh/vix", response_model=OptionsRefreshResponse)
def options_refresh_vix(settings: SettingsDep, payload: dict) -> dict:
    source = str(payload.get("source", "public"))
    _reject_sample_refresh(source)
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


@router.post(
    "/options/daily-scan/run",
    response_model=OptionsDailyScanTaskStateResponse,
    status_code=202,
    responses={409: {"description": "An options scan is already running."}},
)
def options_daily_scan_run(
    settings: SettingsDep,
    background_tasks: BackgroundTasks,
) -> dict:
    target_session = resolve_options_market_session().isoformat()
    request = OptionsDailyTaskRequest(
        provider="futu",
        top=34,
        strategies=("sell_put", "covered_call"),
        run_date=target_session,
        universe_source="existing",
        earnings_source="public",
        vix_source="public",
        universe_path=settings.options_radar.curated_universe_path,
        earnings_path=settings.options_radar.earnings_calendar_path,
        vix_path=settings.options_radar.vix_history_path,
        output_dir=settings.options_radar.output_dir,
        iv_history_dir=settings.options_radar.output_dir / "iv_history",
        trigger="manual",
        dividend_source="public",
        dividends_path=settings.options_radar.dividend_events_path,
    )
    scan_lock = options_radar_scan_lock(request.output_dir)
    try:
        scan_lock.__enter__()
    except OptionsRadarScanLocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "options_scan_already_running",
                "message": "An options recommendation scan is already running.",
            },
        ) from exc
    try:
        queued = queued_options_daily_task_status(request)
        write_options_daily_task_status(request.output_dir, queued)
        background_tasks.add_task(
            _run_reserved_options_daily_task,
            settings,
            request,
            scan_lock,
        )
    except Exception:
        scan_lock.__exit__(None, None, None)
        raise
    return {
        key: queued[key]
        for key in (
            "status",
            "terminal",
            "current_step",
            "target_session",
            "trigger",
            "queued_at",
            "started_at",
            "finished_at",
            "scanned_tickers",
            "total_tickers",
        )
    }


def _run_reserved_options_daily_task(settings, request, scan_lock) -> None:
    try:
        run_options_daily_task(
            settings=settings,
            request=request,
            lock_already_held=True,
        )
    except Exception:
        logger.exception(
            "manual options recommendation scan failed target_session=%s",
            request.run_date,
        )
    finally:
        scan_lock.__exit__(None, None, None)


@router.get(
    "/options/daily-scan/symbol/{ticker}",
    response_model=OptionsDailyScanSymbolResponse,
)
def options_daily_scan_symbol(
    settings: SettingsDep,
    ticker: str,
    date: str | None = None,
    top: int = 20,
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
    freshness = _snapshot_freshness(
        report.run_date,
        report.as_of,
        report.candidates,
    )
    status = report.status
    shortfall_reasons = dict(report.shortfall_reasons)
    if freshness["is_stale"] and status in {"available", "empty"}:
        status = "unavailable"
        shortfall_reasons["snapshot_stale"] = 1
    diversified = select_recommendations(report.candidates)
    if len(diversified) < len(report.candidates):
        shortfall_reasons["ticker_concentration_limit"] = (
            len(report.candidates) - len(diversified)
        )
    candidates = (
        [
            candidate
            for candidate in diversified
            if candidate.ticker.upper().strip() == normalized
        ][: min(max(top, 0), 20)]
        if status == "available"
        else []
    )
    return {
        "ticker": normalized,
        "run_date": report.run_date,
        "provider": report.provider,
        "as_of": report.as_of,
        "status": status,
        "shortfall_count": max(RECOMMENDATION_LIMIT - len(candidates), 0),
        "shortfall_reasons": shortfall_reasons,
        "universe_size": report.universe_size,
        "scanned_tickers": report.scanned_tickers,
        "failed_tickers": report.failed_tickers,
        "is_stale": freshness["is_stale"],
        "snapshot_age_days": freshness["snapshot_age_days"],
        "candidate_count": len(candidates),
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
    }


@router.get("/options/daily-scan", response_model=OptionsDailyScanResponse)
def options_daily_scan(
    settings: SettingsDep,
    date: str | None = None,
    strategy: str = "all",
    sector: str | None = None,
    top: int = 20,
    dte_bucket: str | None = None,
) -> dict:
    store = RadarSnapshotStore(settings.options_radar.output_dir)
    active_date = date or store.latest_date()
    if active_date is None:
        return {
            "run_date": "",
            "provider": None,
            "as_of": None,
            "status": "unavailable",
            "risk_free_rate": None,
            "shortfall_count": RECOMMENDATION_LIMIT,
            "shortfall_reasons": {"no_snapshot": 1},
            "universe_size": 0,
            "scanned_tickers": 0,
            "failed_tickers": [],
            "is_stale": False,
            "snapshot_age_days": 0,
            "expired_candidate_count": 0,
            "candidate_count": 0,
            "candidates": [],
        }
    try:
        report = store.read(active_date)
    except FileNotFoundError as exc:
        raise _missing_snapshot() from exc
    freshness = _snapshot_freshness(
        report.run_date,
        report.as_of,
        report.candidates,
    )
    status = report.status
    shortfall_reasons = dict(report.shortfall_reasons)
    if freshness["is_stale"] and status in {"available", "empty"}:
        status = "unavailable"
        shortfall_reasons["snapshot_stale"] = 1
    diversified = select_recommendations(report.candidates)
    if len(diversified) < len(report.candidates):
        shortfall_reasons["ticker_concentration_limit"] = (
            len(report.candidates) - len(diversified)
        )
    candidates = (
        [
            candidate
            for candidate in diversified
            if _matches(candidate, strategy=strategy, sector=sector, dte_bucket=dte_bucket)
        ][: min(max(top, 0), 20)]
        if status == "available"
        else []
    )
    return {
        "run_date": report.run_date,
        "provider": report.provider,
        "as_of": report.as_of,
        "status": status,
        "risk_free_rate": report.risk_free_rate,
        "shortfall_count": max(RECOMMENDATION_LIMIT - len(candidates), 0),
        "shortfall_reasons": shortfall_reasons,
        "universe_size": report.universe_size,
        "scanned_tickers": report.scanned_tickers,
        "failed_tickers": report.failed_tickers,
        **freshness,
        "candidate_count": len(candidates),
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
        "5-21": (5, 21),
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
        "days_to_expiry": option.days_to_expiry,
        "mid": option.mid,
        "annualized_yield": option.annualized_yield,
        "gross_annualized_yield": candidate.gross_annualized_yield,
        "pop": candidate.pop,
        "otm_pct": candidate.otm_pct,
        "extrinsic_value": candidate.extrinsic_value,
        "breakeven": candidate.breakeven,
        "take_profit_50_price": candidate.take_profit_50_price,
        "manage_at_21_dte": candidate.manage_at_21_dte,
        "expected_value": candidate.expected_value,
        "excess_annualized_ev": candidate.excess_annualized_ev,
        "liquidity_factor": candidate.liquidity_factor,
        "recommendation_score": candidate.recommendation_score,
        "recommendation_score_model": candidate.recommendation_score_model,
        "hard_gate_passed": candidate.hard_gate_passed,
        "quote_as_of": candidate.quote_as_of,
        "implied_volatility": option.implied_volatility,
        "iv_rank": candidate.iv_rank,
        "iv_measure": candidate.iv_measure,
        "iv_history_samples": candidate.iv_history_samples,
        "iv_rank_status": candidate.iv_rank_status,
        "delta": option.delta,
        "open_interest": option.open_interest,
        "spread_pct": option.spread_pct,
        "earnings_date": option.earnings_date,
        "earnings_in_window": candidate.earnings_in_window,
        "ex_dividend_date": candidate.ex_dividend_date,
        "ex_dividend_in_window": candidate.ex_dividend_in_window,
        "dividend_per_share": candidate.dividend_per_share,
        "global_score": candidate.global_score,
        "market_regime": candidate.market_regime,
        "market_regime_penalty": candidate.market_regime_penalty,
    }


def _snapshot_freshness(
    run_date: str,
    as_of: str | None,
    candidates: list[OptionsRadarCandidate],
    *,
    now: datetime | None = None,
) -> dict:
    active_now = now or _utc_now()
    normalized_now = (
        active_now.replace(tzinfo=UTC) if active_now.tzinfo is None else active_now.astimezone(UTC)
    )
    local_today = normalized_now.astimezone(ZoneInfo("America/New_York")).date()
    current_session = latest_us_market_session(local_today)
    try:
        resolution = resolve_recommendation_quote(
            run_date=run_date,
            quote_as_of=as_of,
            observed_at=normalized_now.isoformat(),
        )
    except ValueError:
        resolution = None
    quote_session = resolution.quote_session if resolution is not None else None
    is_stale = bool(
        resolution is None or resolution.reason is not None or quote_session != current_session
    )
    age_days = max((current_session - quote_session).days, 0) if quote_session is not None else 0
    expired_count = 0
    for candidate in candidates:
        try:
            if date.fromisoformat(candidate.candidate.expiry) < local_today:
                expired_count += 1
        except ValueError:
            continue
    return {
        "is_stale": is_stale,
        "snapshot_age_days": age_days,
        "expired_candidate_count": expired_count,
    }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value))


def _reject_sample_refresh(source: str) -> None:
    if source.lower().strip() == "sample":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "sample_options_input_withdrawn",
                "message": "sample option inputs cannot be persisted through the product API",
            },
        )


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
