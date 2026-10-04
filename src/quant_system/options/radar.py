"""Curated seller-options recommendation scan.

The generic screener supplies raw real-quote candidates. This module applies
the fixed recommendation hard gates to every raw row, computes the physical
expected value (extrinsic premium minus the closed-form lognormal expected
payout) annualized and multiplied by liquidity, then applies per-ticker limits
and one global Top-20 cap. ``global_score`` remains the legacy seller
composite for the read-only opportunity ledger; recommendation ordering uses
``recommendation_score`` only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from quant_system.data.providers.futu import FutuProviderError
from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.iv_history import (
    IV_MEASURE_ATM30_STRADDLE_V1,
    IvHistoryStore,
    compute_iv_rank,
    load_atm30_straddle_iv,
    resolve_trusted_underlying_quote,
)
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
from quant_system.options.seller_score import (
    DEFAULT_EQUITY_RISK_PREMIUM,
    evaluate_seller_recommendation,
    historical_volatility_from_ratio,
    latest_us_market_session,
    resolve_recommendation_quote,
    score_seller_contract,
)
from quant_system.options.universe import UniverseEntry

CURATED_RECOMMENDATION_UNIVERSE_SIZE = 34
MAX_RECOMMENDATIONS_PER_TICKER = 2
CURATED_RECOMMENDATION_TICKERS = (
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "SOXX",
    "SMH",
    "IGV",
    "XLY",
    "XLP",
    "XLF",
    "XLV",
    "XLE",
    "AVGO",
    "AMD",
    "TSM",
    "MU",
    "SNDK",
    "CRM",
    "ORCL",
    "COST",
    "KO",
    "MCD",
    "JPM",
    "GS",
    "BRK.B",
    "LLY",
    "UNH",
    "XOM",
    "CVX",
)


@dataclass(frozen=True)
class OptionsRadarConfig:
    base_screen_config: OptionsScreenerConfig = field(default_factory=OptionsScreenerConfig)
    strategies: tuple[StrategyType, ...] = ("sell_put", "covered_call")
    universe_top_n: int = 100
    max_recommendations: int = 20
    risk_free_rate: float | None = None
    equity_risk_premium: float = DEFAULT_EQUITY_RISK_PREMIUM


@dataclass(frozen=True)
class OptionsRadarCandidate:
    ticker: str
    sector: str | None
    strategy: StrategyType
    candidate: OptionsScreenerCandidate
    iv_rank: float | None
    earnings_in_window: bool
    global_score: float
    iv_history_samples: int
    iv_rank_status: Literal["warming", "ready"]
    iv_measure: str = IV_MEASURE_ATM30_STRADDLE_V1
    market_regime: str | None = None
    market_regime_penalty: float = 0.0
    gross_annualized_yield: float | None = None
    pop: float | None = None
    otm_pct: float | None = None
    ex_dividend_date: str | None = None
    ex_dividend_in_window: bool = False
    dividend_per_share: float | None = None
    extrinsic_value: float | None = None
    breakeven: float | None = None
    take_profit_50_price: float | None = None
    manage_at_21_dte: str | None = None
    expected_value: float | None = None
    excess_annualized_ev: float | None = None
    liquidity_factor: float | None = None
    recommendation_score: float | None = None
    recommendation_score_model: str | None = None
    hard_gate_passed: bool = False
    quote_as_of: str | None = None


@dataclass(frozen=True)
class OptionsRadarReport:
    run_date: str
    started_at: str
    finished_at: str
    universe_size: int
    scanned_tickers: int
    failed_tickers: list[tuple[str, str]]
    candidates: list[OptionsRadarCandidate]
    provider: str | None = None
    as_of: str | None = None
    status: Literal["available", "empty", "unavailable"] = "empty"
    risk_free_rate: float | None = None
    equity_risk_premium: float | None = None
    shortfall_count: int = 0
    shortfall_reasons: dict[str, int] = field(default_factory=dict)
    expected_universe_size: int = 0


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
    dividend_events: dict[str, tuple[date | None, float]] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> OptionsRadarReport:
    active_run_date = run_date or _ny_date()
    started_at = _utc_now()
    provider_name = getattr(provider, "provider_name", None)
    selected_universe = universe[: config.universe_top_n]
    expected_universe_size = max(config.universe_top_n, 0)
    if config.risk_free_rate is None:
        finished_at = _utc_now()
        return OptionsRadarReport(
            run_date=active_run_date,
            started_at=started_at,
            finished_at=finished_at,
            universe_size=expected_universe_size,
            expected_universe_size=expected_universe_size,
            scanned_tickers=0,
            failed_tickers=[],
            candidates=[],
            provider=provider_name,
            as_of=None,
            status="unavailable",
            risk_free_rate=None,
            equity_risk_premium=config.equity_risk_premium,
            shortfall_count=config.max_recommendations,
            shortfall_reasons={"risk_free_rate_missing": 1},
        )
    candidates: list[OptionsRadarCandidate] = []
    failed: list[tuple[str, str]] = []
    shortfall_reasons: dict[str, int] = {}
    observed_quote_times: list[tuple[datetime, str]] = []
    scanned_tickers = 0
    iv_store = IvHistoryStore(iv_history_dir)
    scan_date = date.fromisoformat(active_run_date)
    today = latest_us_market_session(scan_date)
    session_gap_days = max((scan_date - today).days, 0)

    total_tickers = len(selected_universe)
    for processed_tickers, entry in enumerate(selected_universe, start=1):
        ticker_failed = False
        ticker_candidates: list[OptionsRadarCandidate] = []
        screened_batches: list[
            tuple[StrategyType, list[OptionsScreenerCandidate], str]
        ] = []
        try:
            underlying_snapshot = provider.fetch_underlying_snapshot(entry.ticker)
            underlying_quote = resolve_trusted_underlying_quote(
                underlying_snapshot,
                ticker=entry.ticker,
                market_session=today,
                observed_at=_utc_now(),
            )
            iv_observation = load_atm30_straddle_iv(
                provider,
                ticker=entry.ticker,
                spot_price=underlying_quote.spot_price,
                market_session=today,
            )
        except Exception as exc:
            failed.append((entry.ticker, _failure_label(exc)))
            if progress_callback is not None:
                progress_callback(processed_tickers, total_tickers)
            continue

        for strategy in config.strategies:
            screen_config = config.base_screen_config.model_copy(
                update={
                    "ticker": entry.ticker,
                    "strategy_type": strategy,
                    "expiration": None,
                    "min_dte": max(
                        config.base_screen_config.min_dte - session_gap_days,
                        0,
                    ),
                    "top_n": 1000,
                    "include_rejected": True,
                }
            )
            try:
                result = run_options_screener(
                    provider=provider,
                    config=screen_config,
                    market_regime=market_regime,
                    apply_top_n=False,
                    iv_observation=iv_observation,
                    run_date=active_run_date,
                )
            except Exception as exc:
                failed.append((entry.ticker, _failure_label(exc)))
                ticker_failed = True
                break
            screened_batches.append((strategy, result.candidates, _utc_now()))
        if ticker_failed:
            if progress_callback is not None:
                progress_callback(processed_tickers, total_tickers)
            continue

        local_quote_times: list[tuple[datetime, str]] = []
        raw_candidate_count = sum(len(batch[1]) for batch in screened_batches)
        for _strategy, raw_candidates, quote_received_at in screened_batches:
            for candidate in raw_candidates:
                resolution = resolve_recommendation_quote(
                    run_date=active_run_date,
                    quote_as_of=candidate.quote_as_of,
                    observed_at=quote_received_at,
                )
                if (
                    resolution.reason is None
                    and resolution.quote_at_utc is not None
                    and resolution.canonical_as_of is not None
                ):
                    local_quote_times.append(
                        (resolution.quote_at_utc, resolution.canonical_as_of)
                    )
        if raw_candidate_count == 0 and iv_observation.quote_as_of is not None:
            atm_quote_at = _parse_quote_instant(iv_observation.quote_as_of)
            if atm_quote_at is not None:
                local_quote_times.append((atm_quote_at, iv_observation.quote_as_of))

        try:
            if provider_name == "futu" and local_quote_times:
                iv_store.append(
                    entry.ticker,
                    current_iv=iv_observation.current_iv,
                    run_date=active_run_date,
                    quote_as_of=iv_observation.quote_as_of,
                    provider="futu",
                    measure=iv_observation.measure,
                )
            effective_history = iv_store.read_values(
                entry.ticker,
                measure=iv_observation.measure,
                as_of_session=today,
            )
            effective_current_iv = effective_history[-1] if effective_history else None
            shared_iv_rank = compute_iv_rank(
                entry.ticker,
                effective_current_iv,
                history_dir=iv_history_dir,
                measure=iv_observation.measure,
                as_of_session=today,
            )
        except Exception as exc:
            failed.append((entry.ticker, _failure_label(exc)))
            if progress_callback is not None:
                progress_callback(processed_tickers, total_tickers)
            continue

        earnings_date = earnings_calendar.next_earnings(entry.ticker, today)
        dividend_event = (dividend_events or {}).get(entry.ticker.upper())
        for strategy, raw_candidates, quote_received_at in screened_batches:
            for candidate in raw_candidates:
                iv_rank = shared_iv_rank
                regime_penalty = (
                    seller_regime_penalty(strategy, market_regime.volatility_regime)
                    if market_regime is not None
                    else 0.0
                )
                seller_score = score_seller_contract(
                    annualized_yield=candidate.annualized_yield,
                    spread_pct=candidate.spread_pct,
                    open_interest=candidate.open_interest,
                    volume=candidate.volume,
                    delta=candidate.delta,
                    hv_iv_ratio=candidate.hv_iv_ratio,
                    iv_rank=iv_rank,
                    market_regime_penalty=regime_penalty,
                )
                enriched = candidate.model_copy(
                    update={
                        "iv_rank": iv_rank,
                        "earnings_date": earnings_date.isoformat()
                        if earnings_date is not None
                        else None,
                        "seller_score": seller_score,
                    }
                )
                quote_resolution = resolve_recommendation_quote(
                    run_date=active_run_date,
                    quote_as_of=enriched.quote_as_of,
                    observed_at=quote_received_at,
                )
                if quote_resolution.canonical_as_of is not None:
                    enriched = enriched.model_copy(
                        update={
                            "quote_as_of": quote_resolution.canonical_as_of,
                            "days_to_expiry": (
                                date.fromisoformat(enriched.expiry)
                                - quote_resolution.expected_session
                            ).days,
                        }
                    )
                evaluation = evaluate_seller_recommendation(
                    strategy_type=strategy,
                    strike=enriched.strike,
                    underlying_price=enriched.underlying_price,
                    mid=enriched.mid,
                    spread_pct=enriched.spread_pct,
                    open_interest=enriched.open_interest,
                    delta=enriched.delta,
                    days_to_expiry=enriched.days_to_expiry,
                    implied_volatility=enriched.implied_volatility,
                    iv_rank=iv_rank,
                    risk_free_rate=config.risk_free_rate,
                    run_date=active_run_date,
                    expiry=enriched.expiry,
                    earnings_date=(
                        earnings_date.isoformat() if earnings_date is not None else None
                    ),
                    is_etf=entry.source in {"core_etf", "sector_etf"},
                    ex_dividend_date=(
                        dividend_event[0].isoformat()
                        if dividend_event is not None and dividend_event[0] is not None
                        else None
                    ),
                    dividend_per_share=(dividend_event[1] if dividend_event is not None else None),
                    quote_as_of=enriched.quote_as_of,
                    observed_at=quote_received_at,
                    historical_volatility=historical_volatility_from_ratio(
                        enriched.hv_iv_ratio,
                        enriched.implied_volatility,
                    ),
                    equity_risk_premium=config.equity_risk_premium,
                )
                if not evaluation.hard_gate_passed:
                    for reason in evaluation.rejection_reasons:
                        shortfall_reasons[reason] = shortfall_reasons.get(reason, 0) + 1
                    continue
                ticker_candidates.append(
                    OptionsRadarCandidate(
                        ticker=entry.ticker,
                        sector=entry.sector,
                        strategy=strategy,
                        candidate=enriched,
                        iv_rank=iv_rank,
                        earnings_in_window=False,
                        global_score=compute_global_score(
                            seller_composite=seller_score.composite,
                            earnings_in_window=False,
                        ),
                        iv_history_samples=len(effective_history),
                        iv_rank_status=(
                            "ready" if shared_iv_rank is not None else "warming"
                        ),
                        market_regime=(
                            market_regime.volatility_regime if market_regime is not None else None
                        ),
                        market_regime_penalty=regime_penalty,
                        gross_annualized_yield=evaluation.gross_annualized_yield,
                        pop=evaluation.pop,
                        otm_pct=evaluation.otm_pct,
                        ex_dividend_date=evaluation.ex_dividend_date,
                        ex_dividend_in_window=evaluation.ex_dividend_in_window,
                        dividend_per_share=evaluation.dividend_per_share,
                        extrinsic_value=evaluation.extrinsic_value,
                        breakeven=evaluation.breakeven,
                        take_profit_50_price=evaluation.take_profit_50_price,
                        manage_at_21_dte=evaluation.manage_at_21_dte,
                        expected_value=evaluation.expected_value,
                        excess_annualized_ev=evaluation.excess_annualized_ev,
                        liquidity_factor=evaluation.liquidity_factor,
                        recommendation_score=evaluation.recommendation_score,
                        recommendation_score_model=evaluation.recommendation_score_model,
                        hard_gate_passed=True,
                        quote_as_of=evaluation.quote_as_of,
                    )
                )
        observed_quote_times.extend(local_quote_times)
        scanned_tickers += 1
        candidates.extend(ticker_candidates)
        if progress_callback is not None:
            progress_callback(processed_tickers, total_tickers)

    diversified = select_recommendations(candidates, limit=len(candidates))
    if len(diversified) < len(candidates):
        shortfall_reasons["ticker_concentration_limit"] = len(candidates) - len(diversified)
    candidates = diversified[: max(config.max_recommendations, 0)]
    if failed:
        shortfall_reasons["ticker_scan_failed"] = len(failed)
    incomplete_count = max(expected_universe_size - scanned_tickers, 0)
    if incomplete_count or failed:
        shortfall_reasons["universe_scan_incomplete"] = max(
            incomplete_count,
            len(failed),
        )
    shortfall_count = max(config.max_recommendations - len(candidates), 0)
    if shortfall_count:
        shortfall_reasons["eligible_contracts_below_limit"] = shortfall_count
    finished_at = _utc_now()
    status: Literal["available", "empty", "unavailable"]
    if provider_name == "futu" and observed_quote_times and candidates:
        status = "available"
    elif provider_name == "futu" and observed_quote_times and scanned_tickers:
        status = "empty"
    else:
        status = "unavailable"
        if provider_name == "futu" and scanned_tickers and not observed_quote_times:
            shortfall_reasons["quote_evidence_missing"] = 1
    return OptionsRadarReport(
        run_date=active_run_date,
        started_at=started_at,
        finished_at=finished_at,
        universe_size=expected_universe_size,
        expected_universe_size=expected_universe_size,
        scanned_tickers=scanned_tickers,
        failed_tickers=failed,
        candidates=candidates,
        provider=provider_name,
        as_of=(
            min(observed_quote_times, key=lambda item: item[0])[1] if observed_quote_times else None
        ),
        status=status,
        risk_free_rate=config.risk_free_rate,
        equity_risk_premium=config.equity_risk_premium,
        shortfall_count=shortfall_count,
        shortfall_reasons=dict(sorted(shortfall_reasons.items())),
    )


def _failure_label(exc: Exception) -> str:
    if isinstance(exc, FutuProviderError):
        return f"FutuProviderError:{exc.code}"
    return type(exc).__name__


def compute_global_score(
    *,
    seller_composite: float,
    earnings_in_window: bool,
) -> float:
    earnings_penalty = -15.0 if earnings_in_window else 0.0
    extra_spread_penalty = 0.0
    return _clip(
        seller_composite + earnings_penalty + extra_spread_penalty,
        0.0,
        100.0,
    )


def _radar_sort_key(item: OptionsRadarCandidate) -> tuple:
    return (
        -(item.recommendation_score if item.recommendation_score is not None else float("-inf")),
        -(item.gross_annualized_yield or 0.0),
        item.candidate.spread_pct if item.candidate.spread_pct is not None else 999.0,
    )


def select_recommendations(
    candidates: list[OptionsRadarCandidate], *, limit: int = 20,
) -> list[OptionsRadarCandidate]:
    """Keep each ticker's two best contracts, then the global score order."""
    counts: dict[str, int] = {}
    selected = []
    for candidate in sorted(candidates, key=_radar_sort_key):
        ticker = candidate.ticker.upper().strip()
        if counts.get(ticker, 0) >= MAX_RECOMMENDATIONS_PER_TICKER:
            continue
        counts[ticker] = counts.get(ticker, 0) + 1
        selected.append(candidate)
    return selected[: max(limit, 0)]


def _clip(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _parse_quote_instant(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ny_date() -> str:
    # A daily BJT post-close scan should still label output by the US trading date.
    return datetime.now(UTC).date().isoformat()
