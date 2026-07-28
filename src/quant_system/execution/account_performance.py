from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from quant_system.config.settings import Settings
from quant_system.data.equity_bar_cache import EquityBarCache
from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
    read_historical_prices,
)
from quant_system.execution.account import LedgerEntry, PaperAccount
from quant_system.trading_kernel import roll_position_on_fill

PerformanceRange = Literal["7d", "1m", "3m"]

_BENCHMARK_SYMBOLS = ("SPY", "QQQ")
_FILL_KINDS = {"fill", "rebalance_fill", "sleeve_execution_fill"}
_EXTERNAL_CASH_FLOW_KINDS = {"deposit", "withdrawal", "reset"}
_NEW_YORK = ZoneInfo("America/New_York")
_SESSION_CLOSE = time(hour=16)
_HISTORY_ANCHOR_DAYS = 14


@dataclass(frozen=True)
class _PriceRead:
    symbol: str
    source: str | None
    as_of: str | None
    closes: dict[date, float]
    error_code: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.closes) and self.error_code is None


@dataclass
class _ReplayPosition:
    quantity: float = 0.0
    avg_cost: float = 0.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_account_performance(
    *,
    account: PaperAccount | None,
    settings: Settings,
    cache_path: str | Path,
    range_key: PerformanceRange,
    benchmarks: list[str],
) -> dict[str, object]:
    """Build aligned paper-account and benchmark return series.

    The account ledger is the account authority. Historical marks are strict
    read-only Futu QFQ daily closes. Provider and cache failures are represented
    per series so one unavailable benchmark does not erase the other lines.
    """

    normalized_benchmarks = _normalize_benchmarks(benchmarks)
    requested_end = _last_completed_session(_utc_now())
    requested_start = _range_start(requested_end, range_key)
    expected_dates = _regular_us_market_sessions(
        start=requested_start,
        end=requested_end,
    )
    fetch_start = requested_start - timedelta(days=_HISTORY_ANCHOR_DAYS)
    warnings: list[str] = []
    try:
        cache: EquityBarCache | None = EquityBarCache(cache_path)
    except Exception:  # noqa: BLE001 - optional cache failure must not block live Futu
        cache = None
        warnings.append("paper_performance_cache_unavailable")

    symbols = list(normalized_benchmarks)
    for symbol in _ledger_symbols(account, requested_end):
        if symbol not in symbols:
            symbols.append(symbol)

    reads = {
        symbol: _read_symbol(
            settings=settings,
            cache=cache,
            symbol=symbol,
            start=fetch_start,
            end=requested_end,
        )
        for symbol in symbols
    }
    warnings.extend(
        f"{symbol}:{reads[symbol].error_code}"
        for symbol in normalized_benchmarks
        if reads[symbol].error_code is not None
    )

    primary_dates = _primary_market_dates(
        reads=reads,
        benchmarks=normalized_benchmarks,
        start=requested_start,
        end=requested_end,
    )
    benchmark_statuses = {
        symbol: _benchmark_status(
            price_read=reads[symbol],
            expected_dates=expected_dates,
            start=requested_start,
            end=requested_end,
        )
        for symbol in normalized_benchmarks
    }
    common_dates = _common_market_dates(
        reads=reads,
        benchmarks=normalized_benchmarks,
        primary_dates=primary_dates,
        start=requested_start,
        end=requested_end,
    )

    paper_series = _paper_series(
        account=account,
        dates=common_dates,
        reads=reads,
    )
    if paper_series["status"] == "unavailable" and paper_series["error_code"] is not None:
        warnings.append(f"paper:{paper_series['error_code']}")
    elif paper_series["status"] == "partial":
        warnings.append("paper:partial_coverage")
    aligned_dates = list(common_dates)
    if paper_series["status"] in {"available", "partial"} and paper_series["points"]:
        paper_dates = {date.fromisoformat(point["date"]) for point in paper_series["points"]}
        aligned_dates = [
            session_date
            for session_date in common_dates
            if session_date in paper_dates
        ]
        paper_series["points"] = [
            point
            for point in paper_series["points"]
            if date.fromisoformat(point["date"]) in set(aligned_dates)
        ]

    series: list[dict[str, object]] = [paper_series]
    for symbol in normalized_benchmarks:
        series.append(
            _benchmark_series(
                symbol=symbol,
                price_read=reads[symbol],
                dates=aligned_dates if aligned_dates else common_dates,
                status=benchmark_statuses[symbol],
            )
        )

    coverage_complete = bool(expected_dates) and paper_series["status"] == "available"
    coverage_complete = coverage_complete and all(
        benchmark_statuses[symbol] == "available" for symbol in normalized_benchmarks
    )
    coverage_complete = coverage_complete and aligned_dates == expected_dates

    return {
        "account_id": account.account_id if account is not None else "default",
        "account_exists": account is not None,
        "range": range_key,
        "granularity": "1d",
        "benchmarks": normalized_benchmarks,
        "requested_start": requested_start.isoformat(),
        "requested_end": requested_end.isoformat(),
        "actual_start": aligned_dates[0].isoformat() if aligned_dates else None,
        "actual_end": aligned_dates[-1].isoformat() if aligned_dates else None,
        "coverage_complete": coverage_complete,
        "series": series,
        "warnings": warnings,
    }


def _normalize_benchmarks(benchmarks: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_symbol in benchmarks:
        symbol = raw_symbol.upper().strip()
        if symbol not in _BENCHMARK_SYMBOLS:
            raise ValueError("benchmarks may contain only SPY and QQQ")
        if symbol not in normalized:
            normalized.append(symbol)
    if not normalized:
        raise ValueError("at least one benchmark is required")
    return normalized


def _read_symbol(
    *,
    settings: Settings,
    cache: EquityBarCache | None,
    symbol: str,
    start: date,
    end: date,
) -> _PriceRead:
    try:
        snapshot = read_historical_prices(
            settings=settings,
            symbols=[symbol],
            start=start.isoformat(),
            end=end.isoformat(),
            provider="futu",
            interval="1d",
            adjustment="qfq",
            cache=cache,
        )
    except HistoricalPriceReadError as exc:
        return _PriceRead(
            symbol=symbol,
            source=exc.provider,
            as_of=None,
            closes={},
            error_code=exc.code,
        )
    except Exception:  # noqa: BLE001 - isolate provider failure to this series
        return _PriceRead(
            symbol=symbol,
            source="futu",
            as_of=None,
            closes={},
            error_code="historical_prices_provider_error",
        )
    return _snapshot_read(symbol, snapshot)


def _snapshot_read(symbol: str, snapshot: HistoricalPriceSnapshot) -> _PriceRead:
    rows = snapshot.series[0]["rows"] if snapshot.series else []
    closes = {
        date.fromisoformat(str(row["date"])): float(row["close"])
        for row in rows
    }
    if not closes:
        return _PriceRead(
            symbol=symbol,
            source=snapshot.source,
            as_of=snapshot.fetched_at,
            closes={},
            error_code="historical_prices_no_completed_sessions",
        )
    return _PriceRead(
        symbol=symbol,
        source=snapshot.source,
        as_of=snapshot.fetched_at,
        closes=closes,
    )


def _ledger_symbols(account: PaperAccount | None, requested_end: date) -> list[str]:
    if account is None:
        return []
    end_timestamp = _session_close_utc(requested_end)
    symbols: list[str] = []
    for entry in account.ledger:
        if entry.kind not in _FILL_KINDS or not entry.symbol:
            continue
        try:
            timestamp = _parse_timestamp(entry.timestamp)
        except ValueError:
            continue
        symbol = entry.symbol.upper().strip()
        if timestamp <= end_timestamp and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _primary_market_dates(
    *,
    reads: dict[str, _PriceRead],
    benchmarks: list[str],
    start: date,
    end: date,
) -> list[date]:
    observed_dates: set[date] = set()
    for symbol in benchmarks:
        price_read = reads[symbol]
        observed_dates.update(
            session_date
            for session_date in price_read.closes
            if start <= session_date <= end
        )
    return sorted(observed_dates)


def _common_market_dates(
    *,
    reads: dict[str, _PriceRead],
    benchmarks: list[str],
    primary_dates: list[date],
    start: date,
    end: date,
) -> list[date]:
    common = set(primary_dates)
    if not common:
        return []
    for symbol in benchmarks:
        price_read = reads[symbol]
        if not price_read.available:
            continue
        symbol_dates = {
            session_date
            for session_date in price_read.closes
            if start <= session_date <= end
        }
        common.intersection_update(symbol_dates)
    return sorted(common)


def _benchmark_status(
    *,
    price_read: _PriceRead,
    expected_dates: list[date],
    start: date,
    end: date,
) -> Literal["available", "partial", "unavailable"]:
    if not price_read.available:
        return "unavailable"
    dates = {
        session_date
        for session_date in price_read.closes
        if start <= session_date <= end
    }
    if not dates:
        return "unavailable"
    return "available" if dates.issuperset(expected_dates) else "partial"


def _benchmark_series(
    *,
    symbol: str,
    price_read: _PriceRead,
    dates: list[date],
    status: Literal["available", "partial", "unavailable"],
) -> dict[str, object]:
    usable_dates = [session_date for session_date in dates if session_date in price_read.closes]
    if status == "unavailable" or not usable_dates:
        return {
            "id": symbol,
            "kind": "benchmark",
            "label": symbol,
            "symbol": symbol,
            "status": "unavailable",
            "source": price_read.source,
            "as_of": price_read.as_of,
            "error_code": price_read.error_code
            or "historical_prices_no_completed_sessions",
            "points": [],
        }
    base_close = price_read.closes[usable_dates[0]]
    return {
        "id": symbol,
        "kind": "benchmark",
        "label": symbol,
        "symbol": symbol,
        "status": status,
        "source": price_read.source,
        "as_of": price_read.as_of,
        "error_code": None,
        "points": [
            {
                "date": session_date.isoformat(),
                "close": price_read.closes[session_date],
                "return_ratio": price_read.closes[session_date] / base_close - 1.0,
            }
            for session_date in usable_dates
        ],
    }


def _paper_series(
    *,
    account: PaperAccount | None,
    dates: list[date],
    reads: dict[str, _PriceRead],
) -> dict[str, object]:
    unavailable = {
        "id": "paper",
        "kind": "paper",
        "label": "模拟盘",
        "symbol": None,
        "status": "unavailable",
        "source": "paper_account_ledger",
        "as_of": None,
        "error_code": (
            "paper_account_missing"
            if account is None
            else "paper_market_calendar_unavailable"
        ),
        "points": [],
    }
    if account is None or not dates:
        return unavailable

    try:
        events = sorted(
            ((_parse_timestamp(entry.timestamp), entry) for entry in account.ledger),
            key=lambda item: item[0],
        )
    except ValueError:
        unavailable["error_code"] = "paper_ledger_timestamp_invalid"
        return unavailable
    if not events:
        unavailable["error_code"] = "paper_ledger_empty"
        return unavailable

    positions: dict[str, _ReplayPosition] = {}
    cash = 0.0
    event_index = 0
    has_account_state = False
    points: list[dict[str, object]] = []
    performance_index = 1.0
    previous_equity: float | None = None
    previous_session_date: date | None = None

    for session_date in dates:
        session_close = _session_close_utc(session_date)
        while event_index < len(events) and events[event_index][0] <= session_close:
            event_timestamp, entry = events[event_index]
            is_external_cash_flow = entry.kind in _EXTERNAL_CASH_FLOW_KINDS
            flow_mark_date = (
                session_date
                if event_timestamp >= session_close
                else previous_session_date
            )
            # Daily TWR splits at an external flow using an exact common close:
            # the current close for a close-stamped flow, otherwise the prior
            # completed session. A missing held-symbol mark fails closed.
            if (
                is_external_cash_flow
                and previous_equity is not None
                and flow_mark_date is not None
            ):
                pre_flow_equity = _state_equity(
                    cash=cash,
                    positions=positions,
                    reads=reads,
                    mark_date=flow_mark_date,
                )
                if pre_flow_equity is None:
                    unavailable["error_code"] = "paper_position_history_unavailable"
                    return unavailable
                if previous_equity <= 0 or pre_flow_equity <= 0:
                    unavailable["error_code"] = "paper_equity_non_positive"
                    return unavailable
                performance_index *= pre_flow_equity / previous_equity
            try:
                cash, _cash_flow = _apply_ledger_entry(
                    entry=entry,
                    cash=cash,
                    positions=positions,
                )
            except ValueError:
                unavailable["error_code"] = "paper_ledger_event_invalid"
                return unavailable
            if (
                is_external_cash_flow
                and previous_equity is not None
                and flow_mark_date is not None
            ):
                post_flow_equity = _state_equity(
                    cash=cash,
                    positions=positions,
                    reads=reads,
                    mark_date=flow_mark_date,
                )
                if post_flow_equity is None:
                    unavailable["error_code"] = "paper_position_history_unavailable"
                    return unavailable
                previous_equity = post_flow_equity
            has_account_state = True
            event_index += 1

        if not has_account_state:
            continue

        equity = _state_equity(
            cash=cash,
            positions=positions,
            reads=reads,
            mark_date=session_date,
        )
        if equity is None:
            unavailable["error_code"] = "paper_position_history_unavailable"
            return unavailable

        if previous_equity is not None:
            if previous_equity <= 0:
                unavailable["error_code"] = "paper_equity_non_positive"
                return unavailable
            period_return = equity / previous_equity - 1.0
            performance_index *= 1.0 + period_return
        points.append(
            {
                "date": session_date.isoformat(),
                "equity": equity,
                "return_ratio": performance_index - 1.0,
            }
        )
        previous_equity = equity
        previous_session_date = session_date

    if not points:
        unavailable["error_code"] = "paper_account_outside_requested_range"
        return unavailable
    return {
        "id": "paper",
        "kind": "paper",
        "label": "模拟盘",
        "symbol": None,
        "status": "available" if len(points) == len(dates) else "partial",
        "source": "paper_account_ledger+futu_qfq_1d",
        "as_of": _paper_as_of(account=account, reads=reads),
        "error_code": None,
        "points": points,
    }


def _apply_ledger_entry(
    *,
    entry: LedgerEntry,
    cash: float,
    positions: dict[str, _ReplayPosition],
) -> tuple[float, float]:
    cash_before = cash
    if entry.kind == "reset":
        positions.clear()
    if entry.kind in _FILL_KINDS:
        if (
            entry.symbol is None
            or entry.side not in {"buy", "sell"}
            or entry.quantity is None
            or entry.price is None
            or entry.gross_value is None
        ):
            raise ValueError("incomplete fill ledger entry")
        symbol = entry.symbol.upper().strip()
        current = positions.get(symbol, _ReplayPosition())
        quantity, avg_cost, _realized_delta, _cash_delta = roll_position_on_fill(
            side=entry.side,
            position_quantity=current.quantity,
            position_avg_cost=current.avg_cost,
            fill_quantity=float(entry.quantity),
            fill_price=float(entry.price),
            gross_value=float(entry.gross_value),
            commission=float(entry.commission),
        )
        if abs(quantity) < 1e-9:
            positions.pop(symbol, None)
        else:
            positions[symbol] = _ReplayPosition(
                quantity=quantity,
                avg_cost=avg_cost,
            )
    cash = float(entry.cash_after)
    cash_flow = (
        cash - cash_before if entry.kind in _EXTERNAL_CASH_FLOW_KINDS else 0.0
    )
    return cash, cash_flow


def _state_equity(
    *,
    cash: float,
    positions: dict[str, _ReplayPosition],
    reads: dict[str, _PriceRead],
    mark_date: date,
) -> float | None:
    market_value = 0.0
    for symbol, position in positions.items():
        if position.quantity <= 1e-9:
            continue
        price_read = reads.get(symbol)
        if price_read is None or not price_read.available:
            return None
        mark = price_read.closes.get(mark_date)
        if mark is None:
            return None
        market_value += position.quantity * mark
    return cash + market_value


def _paper_as_of(
    *,
    account: PaperAccount,
    reads: dict[str, _PriceRead],
) -> str:
    candidates = [account.updated_at]
    for entry in account.ledger:
        if entry.kind not in _FILL_KINDS or not entry.symbol:
            continue
        price_read = reads.get(entry.symbol.upper().strip())
        if price_read is not None and price_read.as_of is not None:
            candidates.append(price_read.as_of)
    return max(candidates, key=_parse_timestamp)


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    active = date(year, month, 1)
    while active.weekday() != weekday:
        active += timedelta(days=1)
    return active + timedelta(days=7 * (occurrence - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    active = (
        date(year, 12, 31)
        if month == 12
        else date(year, month + 1, 1) - timedelta(days=1)
    )
    while active.weekday() != weekday:
        active -= timedelta(days=1)
    return active


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _easter_date(year: int) -> date:
    # Anonymous Gregorian computus, matching the repository's NYSE calendar.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    correction = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * correction) // 451
    month = (h + correction - 7 * m + 114) // 31
    day = ((h + correction - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _regular_us_market_holidays(year: int) -> set[date]:
    holidays = {
        _observed_fixed_holiday(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_date(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(year, 12, 25),
    }
    if year >= 2022:
        holidays.add(_observed_fixed_holiday(year, 6, 19))
    return holidays


def _is_regular_us_market_holiday(active_date: date) -> bool:
    years = (active_date.year - 1, active_date.year, active_date.year + 1)
    return any(active_date in _regular_us_market_holidays(year) for year in years)


def _is_us_market_session(active_date: date) -> bool:
    return active_date.weekday() < 5 and not _is_regular_us_market_holiday(active_date)


def _regular_us_market_sessions(*, start: date, end: date) -> list[date]:
    sessions: list[date] = []
    active = start
    while active <= end:
        if _is_us_market_session(active):
            sessions.append(active)
        active += timedelta(days=1)
    return sessions


def _last_completed_session(now: datetime) -> date:
    normalized = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    local = normalized.astimezone(_NEW_YORK)
    candidate = local.date()
    if not _is_us_market_session(candidate) or local.time() < _SESSION_CLOSE:
        candidate -= timedelta(days=1)
    while not _is_us_market_session(candidate):
        candidate -= timedelta(days=1)
    return candidate


def _range_start(end: date, range_key: PerformanceRange) -> date:
    if range_key == "7d":
        return end - timedelta(days=6)
    return _subtract_months(end, 1 if range_key == "1m" else 3)


def _subtract_months(value: date, months: int) -> date:
    absolute_month = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(absolute_month, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _session_close_utc(session_date: date) -> datetime:
    return datetime.combine(
        session_date,
        _SESSION_CLOSE,
        tzinfo=_NEW_YORK,
    ).astimezone(UTC)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid ledger timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
