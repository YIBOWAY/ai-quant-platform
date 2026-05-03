from __future__ import annotations

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import SettingsDep
from quant_system.options.radar import OptionsRadarCandidate
from quant_system.options.radar_storage import RadarSnapshotStore

router = APIRouter()


@router.get("/options/daily-scan/dates")
def options_daily_scan_dates(settings: SettingsDep) -> dict:
    return {"dates": RadarSnapshotStore(settings.options_radar.output_dir).list_dates()}


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
