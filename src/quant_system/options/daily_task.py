from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.options.data_refresh import (
    refresh_dividend_events,
    refresh_earnings_calendar,
    refresh_options_universe,
    refresh_vix_history,
)
from quant_system.options.dividend_events import load_dividend_events
from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.market_regime import load_market_regime
from quant_system.options.models import OptionsScreenerConfig
from quant_system.options.radar import (
    CURATED_RECOMMENDATION_TICKERS,
    CURATED_RECOMMENDATION_UNIVERSE_SIZE,
    OptionsRadarConfig,
    OptionsRadarReport,
    run_options_radar,
)
from quant_system.options.radar_storage import (
    RECOMMENDATION_LIMIT,
    RadarSnapshotStore,
    persisted_recommendation_count,
)
from quant_system.options.rate_limiter import RateLimitedFutuProvider, TokenBucket
from quant_system.options.sample_provider import SampleOptionsProvider
from quant_system.options.scan_lock import options_radar_scan_lock
from quant_system.options.universe import OptionsUniverse


@dataclass(frozen=True)
class OptionsDailyTaskRequest:
    provider: Literal["futu", "sample"]
    top: int
    strategies: tuple[Literal["sell_put", "covered_call"], ...]
    run_date: str
    universe_source: Literal["existing", "public", "github", "sample"]
    earnings_source: Literal["public", "nasdaq", "yfinance", "sample"]
    vix_source: Literal["public", "sample"]
    universe_path: Path
    earnings_path: Path
    vix_path: Path
    output_dir: Path
    iv_history_dir: Path
    trigger: Literal["manual", "scheduled"]
    vix_lookback_days: int = 400
    dividend_source: Literal["public", "yfinance", "sample"] = "yfinance"
    # Canonical callers pass settings.options_radar.dividend_events_path; the
    # static default keeps older constructor calls additive.
    dividends_path: Path = Path("data/options_universe/dividend_events.csv")


@dataclass(frozen=True)
class OptionsDailyTaskDependencies:
    load_universe: Callable[..., list]
    refresh_universe: Callable[..., dict]
    refresh_earnings: Callable[..., dict]
    refresh_vix: Callable[..., dict]
    refresh_dividends: Callable[..., dict]
    load_dividend_events: Callable[..., dict[str, tuple[date | None, float]]]
    build_provider: Callable[..., object]
    build_screen_config: Callable[..., OptionsScreenerConfig]
    load_market_regime: Callable[..., object]
    load_earnings_calendar: Callable[..., EarningsCalendar]
    run_radar: Callable[..., OptionsRadarReport]
    write_snapshot: Callable[[Path, OptionsRadarReport], tuple[Path, Path]]


@dataclass(frozen=True)
class OptionsDailyTaskResult:
    status: str
    report: OptionsRadarReport
    status_path: Path


def queued_options_daily_task_status(
    request: OptionsDailyTaskRequest,
    *,
    queued_at: str | None = None,
) -> dict[str, object]:
    active_queued_at = queued_at or _utc_now()
    return {
        "status": "queued",
        "terminal": False,
        "current_step": "queued",
        "target_session": request.run_date,
        "run_date": request.run_date,
        "trigger": request.trigger,
        "provider": request.provider,
        "strategies": list(request.strategies),
        "queued_at": active_queued_at,
        "started_at": None,
        "updated_at": active_queued_at,
        "finished_at": None,
        "scanned_tickers": 0,
        "total_tickers": request.top,
        "steps": {},
    }


def write_options_daily_task_status(
    output_dir: Path,
    payload: dict[str, object],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "daily_task_status.json"
    temporary = status_path.with_name(f".{status_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(status_path)
    finally:
        temporary.unlink(missing_ok=True)
    return status_path


def run_options_daily_task(
    *,
    settings,
    request: OptionsDailyTaskRequest,
    dependencies: OptionsDailyTaskDependencies | None = None,
    lock_already_held: bool = False,
) -> OptionsDailyTaskResult:
    _validate_lock_authority(settings, request)
    active_dependencies = dependencies or default_options_daily_task_dependencies()
    lock = (
        nullcontext()
        if lock_already_held
        else options_radar_scan_lock(request.iv_history_dir.parent)
    )
    with lock:
        return _run_options_daily_task_locked(
            settings=settings,
            request=request,
            dependencies=active_dependencies,
        )


def _run_options_daily_task_locked(
    *,
    settings,
    request: OptionsDailyTaskRequest,
    dependencies: OptionsDailyTaskDependencies,
) -> OptionsDailyTaskResult:
    started_at = _utc_now()
    queued_at = _existing_queued_at(request) or started_at
    steps: dict[str, dict[str, Any]] = {}
    current_step = "universe"
    scanned_tickers = 0

    def persist_running(step: str) -> None:
        write_options_daily_task_status(
            request.output_dir,
            _task_status_payload(
                request=request,
                status="running",
                terminal=False,
                current_step=step,
                queued_at=queued_at,
                started_at=started_at,
                finished_at=None,
                scanned_tickers=scanned_tickers,
                steps=steps,
            ),
        )

    try:
        _validate_request(settings, request, dependencies)
        persist_running(current_step)
        if request.universe_source == "existing":
            universe = dependencies.load_universe(request.universe_path)
            steps["universe"] = {
                "kind": "universe",
                "source": "existing",
                "status": "loaded_existing",
                "row_count": len(universe),
                "output_path": str(request.universe_path),
                "fetched_at": _utc_now(),
            }
        else:
            steps["universe"] = dependencies.refresh_universe(
                request.universe_path,
                source=request.universe_source,
            )

        current_step = "earnings"
        persist_running(current_step)
        steps["earnings"] = dependencies.refresh_earnings(
            universe_path=request.universe_path,
            output_path=request.earnings_path,
            source=request.earnings_source,
            top=request.top,
            today=date.fromisoformat(request.run_date),
        )

        current_step = "dividends"
        persist_running(current_step)
        steps["dividends"] = dependencies.refresh_dividends(
            request.dividends_path,
            universe_path=request.universe_path,
            source=request.dividend_source,
            top=request.top,
        )

        current_step = "vix"
        persist_running(current_step)
        steps["vix"] = dependencies.refresh_vix(
            request.vix_path,
            source=request.vix_source,
            lookback_days=request.vix_lookback_days,
            end=date.fromisoformat(request.run_date),
        )

        current_step = "scan"
        persist_running(current_step)
        market_regime = dependencies.load_market_regime(
            request.vix_path,
            run_date=request.run_date,
        )
        universe = dependencies.load_universe(request.universe_path, top_n=request.top)

        def record_progress(processed: int, _total: int) -> None:
            nonlocal scanned_tickers
            scanned_tickers = processed
            persist_running("scan")

        report = dependencies.run_radar(
            provider=dependencies.build_provider(settings, request.provider),
            universe=universe,
            config=OptionsRadarConfig(
                base_screen_config=dependencies.build_screen_config(settings),
                strategies=request.strategies,
                universe_top_n=request.top,
                risk_free_rate=settings.options_radar.risk_free_rate,
                equity_risk_premium=settings.options_radar.equity_risk_premium,
            ),
            iv_history_dir=request.iv_history_dir,
            earnings_calendar=dependencies.load_earnings_calendar(request.earnings_path),
            run_date=request.run_date,
            market_regime=market_regime,
            dividend_events=dependencies.load_dividend_events(request.dividends_path),
            progress_callback=record_progress,
        )
        if report.status in {"available", "empty"} and report.as_of is None:
            raise ValueError("options_scan_quote_watermark_required")
        data_path, meta_path = dependencies.write_snapshot(request.output_dir, report)
        scan_status = (
            "data_unavailable"
            if report.scanned_tickers == 0 or report.status == "unavailable"
            else "completed"
        )
        scanned_tickers = min(
            report.scanned_tickers + len(report.failed_tickers),
            request.top,
        )
        # The user-visible candidate count is the number of recommendation rows
        # the snapshot actually persisted, so the task status, the API listing
        # and the snapshot meta all agree.
        persisted_candidates = persisted_recommendation_count(report)
        steps["scan"] = {
            "status": scan_status,
            "run_date": report.run_date,
            "provider": report.provider or request.provider,
            "as_of": report.as_of,
            "universe_size": report.universe_size,
            "scanned_tickers": report.scanned_tickers,
            "failed_tickers": len(report.failed_tickers),
            "candidate_count": persisted_candidates,
            "shortfall_count": max(RECOMMENDATION_LIMIT - persisted_candidates, 0),
            "shortfall_reasons": report.shortfall_reasons,
            "data_path": str(data_path),
            "meta_path": str(meta_path),
        }
        status = (
            "data_unavailable"
            if scan_status == "data_unavailable"
            else "completed_with_warnings"
            if report.failed_tickers
            else "completed"
        )
        finished_at = _utc_now()
        final_payload = _task_status_payload(
            request=request,
            status=status,
            terminal=True,
            current_step="completed",
            queued_at=queued_at,
            started_at=started_at,
            finished_at=finished_at,
            scanned_tickers=scanned_tickers,
            steps=steps,
            successful_tickers=report.scanned_tickers,
        )
        status_path = write_options_daily_task_status(request.output_dir, final_payload)
        return OptionsDailyTaskResult(status=status, report=report, status_path=status_path)
    except Exception as exc:
        finished_at = _utc_now()
        failed_payload = _task_status_payload(
            request=request,
            status="failed",
            terminal=True,
            current_step="failed",
            queued_at=queued_at,
            started_at=started_at,
            finished_at=finished_at,
            scanned_tickers=scanned_tickers,
            steps=steps,
        )
        failed_payload["failed_step"] = current_step
        failed_payload["error"] = f"{type(exc).__name__}: {exc}"
        write_options_daily_task_status(request.output_dir, failed_payload)
        raise


def default_options_daily_task_dependencies() -> OptionsDailyTaskDependencies:
    return OptionsDailyTaskDependencies(
        load_universe=OptionsUniverse.load,
        refresh_universe=refresh_options_universe,
        refresh_earnings=refresh_earnings_calendar,
        refresh_vix=refresh_vix_history,
        refresh_dividends=refresh_dividend_events,
        load_dividend_events=load_dividend_events,
        build_provider=build_options_radar_provider,
        build_screen_config=build_radar_screen_config,
        load_market_regime=load_market_regime,
        load_earnings_calendar=EarningsCalendar.load,
        run_radar=run_options_radar,
        write_snapshot=lambda output_dir, report: RadarSnapshotStore(output_dir).write(report),
    )


def build_options_radar_provider(
    settings,
    provider: Literal["futu", "sample"],
):
    if provider == "sample":
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
            max_tokens=1,
            refill_seconds=settings.options_radar.futu_request_pause_seconds,
        ),
    )


def build_radar_screen_config(_settings) -> OptionsScreenerConfig:
    return OptionsScreenerConfig(
        ticker="SPY",
        strategy_type="sell_put",
        min_dte=5,
        max_dte=60,
        max_delta=0.35,
        min_premium=0.05,
        min_apr=0.0,
        max_spread_pct=0.05,
        min_open_interest=100,
        max_hv_iv=1.0,
        trend_filter=False,
        hv_iv_filter=False,
        provider="futu",
        top_n=1000,
        min_mid_price=0.05,
        min_avg_daily_volume=0,
        min_market_cap=0.0,
        avoid_earnings_within_days=0,
        include_rejected=True,
    )


def _validate_request(settings, request, dependencies: OptionsDailyTaskDependencies) -> None:
    if request.provider == "futu" and "sample" in {
        request.universe_source,
        request.earnings_source,
        request.vix_source,
        request.dividend_source,
    }:
        raise ValueError("sample_options_input_withdrawn")
    canonical_output = request.output_dir.expanduser().resolve(
        strict=False
    ) == settings.options_radar.output_dir.expanduser().resolve(strict=False)
    if not canonical_output:
        return
    if request.provider != "futu":
        raise ValueError("canonical_options_provider_must_be_futu")
    if request.top != CURATED_RECOMMENDATION_UNIVERSE_SIZE:
        raise ValueError("canonical_options_universe_size_required")
    if (
        request.universe_source != "existing"
        or request.universe_path.expanduser().resolve(strict=False)
        != settings.options_radar.curated_universe_path.expanduser().resolve(strict=False)
    ):
        raise ValueError("canonical_options_curated_universe_required")
    universe = dependencies.load_universe(request.universe_path)
    if tuple(item.ticker for item in universe) != CURATED_RECOMMENDATION_TICKERS:
        raise ValueError("canonical_options_curated_universe_mismatch")


def _validate_lock_authority(settings, request: OptionsDailyTaskRequest) -> None:
    canonical_output = request.output_dir.expanduser().resolve(
        strict=False
    ) == settings.options_radar.output_dir.expanduser().resolve(strict=False)
    if not canonical_output:
        return
    expected_iv_history = (request.output_dir / "iv_history").expanduser().resolve(
        strict=False
    )
    if request.iv_history_dir.expanduser().resolve(strict=False) != expected_iv_history:
        raise ValueError("canonical_options_iv_history_required")


def _task_status_payload(
    *,
    request: OptionsDailyTaskRequest,
    status: str,
    terminal: bool,
    current_step: str,
    queued_at: str,
    started_at: str,
    finished_at: str | None,
    scanned_tickers: int,
    steps: dict[str, dict[str, Any]],
    successful_tickers: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "terminal": terminal,
        "current_step": current_step,
        "target_session": request.run_date,
        "run_date": request.run_date,
        "trigger": request.trigger,
        "provider": request.provider,
        "strategies": list(request.strategies),
        "queued_at": queued_at,
        "started_at": started_at,
        "updated_at": _utc_now(),
        "finished_at": finished_at,
        "scanned_tickers": scanned_tickers,
        "total_tickers": request.top,
        "steps": steps,
    }
    if successful_tickers is not None:
        payload["successful_tickers"] = successful_tickers
    return payload


def _existing_queued_at(request: OptionsDailyTaskRequest) -> str | None:
    status_path = request.output_dir / "daily_task_status.json"
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not (
        isinstance(payload, dict)
        and payload.get("status") == "queued"
        and payload.get("target_session") == request.run_date
        and payload.get("trigger") == request.trigger
    ):
        return None
    queued_at = payload.get("queued_at")
    return queued_at if isinstance(queued_at, str) and queued_at else None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
