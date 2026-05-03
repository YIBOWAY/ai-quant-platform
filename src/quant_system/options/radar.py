from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.iv_history import IvHistoryStore, compute_iv_rank
from quant_system.options.market_regime import (
    VixRegimeSnapshot,
    seller_regime_penalty,
)
from quant_system.options.models import (
    OptionsScreenerCandidate,
    OptionsScreenerConfig,
    StrategyType,
)
from quant_system.options.screener import run_options_screener
from quant_system.options.universe import UniverseEntry

RATING_WEIGHTS = {"Strong": 100.0, "Watch": 30.0, "Avoid": 0.0}


@dataclass(frozen=True)
class OptionsRadarConfig:
    base_screen_config: OptionsScreenerConfig = field(default_factory=OptionsScreenerConfig)
    strategies: tuple[StrategyType, ...] = ("sell_put", "covered_call")
    universe_top_n: int = 100
    top_per_ticker: int = 5


@dataclass(frozen=True)
class OptionsRadarCandidate:
    ticker: str
    sector: str | None
    strategy: StrategyType
    candidate: OptionsScreenerCandidate
    iv_rank: float | None
    earnings_in_window: bool
    global_score: float
    market_regime: str | None = None
    market_regime_penalty: float = 0.0


@dataclass(frozen=True)
class OptionsRadarReport:
    run_date: str
    started_at: str
    finished_at: str
    universe_size: int
    scanned_tickers: int
    failed_tickers: list[tuple[str, str]]
    candidates: list[OptionsRadarCandidate]


class OptionsRadarReportModel(BaseModel):
    run_date: str
    started_at: str
    finished_at: str
    universe_size: int
    scanned_tickers: int
    failed_tickers: list[tuple[str, str]]


def run_options_radar(
    *,
    provider,
    universe: list[UniverseEntry],
    config: OptionsRadarConfig,
    iv_history_dir: str | Path,
    earnings_calendar: EarningsCalendar,
    run_date: str | None = None,
    market_regime: VixRegimeSnapshot | None = None,
) -> OptionsRadarReport:
    active_run_date = run_date or _ny_date()
    started_at = _utc_now()
    candidates: list[OptionsRadarCandidate] = []
    failed: list[tuple[str, str]] = []
    scanned_tickers = 0
    selected_universe = universe[: config.universe_top_n]
    iv_store = IvHistoryStore(iv_history_dir)
    today = date.fromisoformat(active_run_date)

    for entry in selected_universe:
        ticker_failed = False
        ticker_candidates: list[OptionsRadarCandidate] = []
        for strategy in config.strategies:
            screen_config = config.base_screen_config.model_copy(
                update={
                    "ticker": entry.ticker,
                    "strategy_type": strategy,
                    "expiration": None,
                    "top_n": config.top_per_ticker,
                }
            )
            try:
                result = run_options_screener(provider=provider, config=screen_config)
            except Exception as exc:
                failed.append((entry.ticker, type(exc).__name__))
                ticker_failed = True
                break

            earnings_date = earnings_calendar.next_earnings(entry.ticker, today)
            earnings_in_window = (
                earnings_calendar.is_within(
                    entry.ticker,
                    today,
                    config.base_screen_config.avoid_earnings_within_days,
                )
                if config.base_screen_config.avoid_earnings_within_days > 0
                else False
            )
            for candidate in result.candidates[: config.top_per_ticker]:
                iv_rank = compute_iv_rank(
                    entry.ticker,
                    candidate.implied_volatility,
                    history_dir=iv_history_dir,
                )
                regime_penalty = (
                    seller_regime_penalty(strategy, market_regime.volatility_regime)
                    if market_regime is not None
                    else 0.0
                )
                enriched = candidate.model_copy(
                    update={
                        "iv_rank": iv_rank,
                        "earnings_date": earnings_date.isoformat()
                        if earnings_date is not None
                        else None,
                    }
                )
                ticker_candidates.append(
                    OptionsRadarCandidate(
                        ticker=entry.ticker,
                        sector=entry.sector,
                        strategy=strategy,
                        candidate=enriched,
                        iv_rank=iv_rank,
                        earnings_in_window=earnings_in_window,
                        global_score=compute_global_score(
                            rating=enriched.rating,
                            annualized_yield=enriched.annualized_yield,
                            iv_rank=iv_rank,
                            earnings_in_window=earnings_in_window,
                            spread_pct=enriched.spread_pct,
                            regime_penalty=regime_penalty,
                        ),
                        market_regime=(
                            market_regime.volatility_regime
                            if market_regime is not None
                            else None
                        ),
                        market_regime_penalty=regime_penalty,
                    )
                )
            _record_atm_iv(
                iv_store=iv_store,
                ticker=entry.ticker,
                run_date=active_run_date,
                candidates=result.candidates,
            )

        if not ticker_failed:
            scanned_tickers += 1
            candidates.extend(ticker_candidates)

    candidates = sorted(
        candidates,
        key=lambda item: (
            -item.global_score,
            -(item.candidate.annualized_yield or 0.0),
            item.candidate.spread_pct if item.candidate.spread_pct is not None else 999.0,
        ),
    )
    return OptionsRadarReport(
        run_date=active_run_date,
        started_at=started_at,
        finished_at=_utc_now(),
        universe_size=len(selected_universe),
        scanned_tickers=scanned_tickers,
        failed_tickers=failed,
        candidates=candidates,
    )


def compute_global_score(
    *,
    rating: str,
    annualized_yield: float | None,
    iv_rank: float | None,
    earnings_in_window: bool,
    spread_pct: float | None,
    regime_penalty: float = 0.0,
) -> float:
    apr_score = _clip((annualized_yield or 0.0) * 100, 0, 60)
    iv_rank_score = 0.4 * _clip(iv_rank or 0.0, 0, 100)
    earnings_penalty = 50.0 if earnings_in_window else 0.0
    spread_penalty = 100.0 if spread_pct is not None and spread_pct > 0.10 else 0.0
    return round(
        RATING_WEIGHTS.get(rating, 0.0)
        + apr_score
        + iv_rank_score
        - earnings_penalty
        - spread_penalty
        + regime_penalty,
        4,
    )


def _record_atm_iv(
    *,
    iv_store: IvHistoryStore,
    ticker: str,
    run_date: str,
    candidates: list[OptionsScreenerCandidate],
) -> None:
    candidates_with_iv = [
        candidate
        for candidate in candidates
        if candidate.implied_volatility is not None and candidate.moneyness is not None
    ]
    if not candidates_with_iv:
        return
    chosen = min(
        candidates_with_iv,
        key=lambda candidate: (
            abs((candidate.days_to_expiry or 30) - 30),
            abs((candidate.moneyness or 1.0) - 1.0),
        ),
    )
    if chosen.implied_volatility is not None:
        iv_store.append(ticker, current_iv=chosen.implied_volatility, run_date=run_date)


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ny_date() -> str:
    # A daily BJT post-close scan should still label output by the US trading date.
    return datetime.now(UTC).date().isoformat()
