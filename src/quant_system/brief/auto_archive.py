"""Server-side daily brief auto-archive builder.

Rebuilds the ``brief_snapshot_v1`` payload from the platform's own HTTP API
(the same backend sources the /brief live page reads) so a LaunchAgent can
archive today's issue without a browser. Fail-closed: if the paper account,
equity curve, or performance master cannot be read, no issue is written.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx

from quant_system.brief.models import (
    BriefAccountPosition,
    BriefAccountSnapshot,
    BriefAiNewsItem,
    BriefArchivePayload,
    BriefEquityPoint,
    BriefHermesLogEntry,
    BriefMarketSnapshot,
    BriefPerformancePoint,
    BriefPerformanceSeries,
    BriefPerformanceSnapshot,
    BriefPriceSource,
    BriefSourceState,
    BriefSourceWatermark,
)

BRIEF_TIME_ZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
MARKET_SYMBOLS = ("SPY", "QQQ", "SOXX", "IGV")

Locale = Literal["en", "zh"]

_COPY = {
    "en": {
        "title": "Daily Morning Brief",
        "quote": (
            "Market data is incomplete; waiting for fresh SPY, QQQ, SOXX, and "
            "IGV daily bars before forming a full market read."
        ),
        "lede": (
            "This morning, paper equity prints at {equity} with a {paper_return} "
            "{range_label} paper return. Platform market note: {market_note} "
            "{asia_radar_note} It has set {digest_count} AI intelligence items in type."
        ),
        "range_label": "7-day",
        "asia_unavailable": "Asia Radar is unavailable today.",
        "asia_coverage": "Asia Radar covers {count} markets as of {as_of}.",
        "asia_full": (
            "Asia Radar (as of {as_of}): {winners} lead while {laggards} lag, "
            "with a {spread} YTD spread between the top-three and bottom-three baskets."
        ),
        "semis_inline": "; semis (SOXX) and software (IGV) moved roughly in line",
        "semis_stronger": "; semis (SOXX) outperformed software (IGV) by {diff}",
        "software_stronger": "; software (IGV) outperformed semis (SOXX) by {diff}",
        "market_note": (
            "{up_count}/4 watched ETFs are up today; {strongest} leads "
            "({strongest_change}) while {weakest} lags ({weakest_change}){relative}."
        ),
        "run_backtest": "Platform recorded backtest",
        "run_factor": "Platform recorded factor analysis",
        "run_replication": "Platform recorded strategy replication",
        "run_paper": "Platform recorded paper run",
        "run_backtest_sample": "SAMPLE · demo backtest (not real)",
        "run_factor_sample": "SAMPLE · demo factor analysis",
        "run_replication_sample": "SAMPLE · demo strategy replication",
        "run_paper_sample": "SAMPLE · demo paper run",
        "scan_entry": "Options daily scan {status} · {strategies}",
        "printed": "Morning brief printed · same-day facts",
    },
    "zh": {
        "title": "每日晨报",
        "quote": (
            "市场涨跌数据暂不完整；待 SPY、QQQ、SOXX、IGV "
            "四组日线全部刷新后再形成完整判断。"
        ),
        "lede": (
            "今晨，模拟盘权益报 {equity}，{range_label}收益 {paper_return}；"
            "平台市场手记：{market_note} {asia_radar_note} "
            "另整理 {digest_count} 条 AI 业内情报。"
        ),
        "range_label": "近 7 日",
        "asia_unavailable": "亚洲雷达数据暂不可用。",
        "asia_coverage": "亚洲雷达覆盖 {count} 个市场（截至 {as_of}）。",
        "asia_full": (
            "亚洲雷达（截至 {as_of}）：{winners} 领跑、{laggards} 落后，"
            "YTD 前三后三篮子分化 {spread}。"
        ),
        "semis_inline": "；半导体（SOXX）与软件（IGV）涨跌接近",
        "semis_stronger": "；半导体（SOXX）相对软件（IGV）偏强 {diff}",
        "software_stronger": "；软件（IGV）相对半导体（SOXX）偏强 {diff}",
        "market_note": (
            "今日四个观察指数中 {up_count}/4 收涨，{strongest} 最强"
            "（{strongest_change}），{weakest} 最弱（{weakest_change}）{relative}。"
        ),
        "run_backtest": "平台记录回测",
        "run_factor": "平台记录因子分析",
        "run_replication": "平台记录策略复现",
        "run_paper": "平台记录模拟盘运行",
        "run_backtest_sample": "SAMPLE · 演示数据 · 非真实回测",
        "run_factor_sample": "SAMPLE · 演示因子分析",
        "run_replication_sample": "SAMPLE · 演示策略复现",
        "run_paper_sample": "SAMPLE · 演示模拟盘运行",
        "scan_entry": "期权每日扫描{status} · {strategies}",
        "printed": "晨报已排印 · 当日事实",
    },
}


class AutoArchiveUnavailable(RuntimeError):
    """Raised when a blocking source is unavailable; nothing is archived."""


@dataclass(frozen=True)
class AutoArchiveSnapshot:
    payload: BriefArchivePayload
    source_watermark: BriefSourceWatermark
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _FetchResult:
    data: dict[str, Any] | None
    error: str | None


def build_auto_archive_snapshot(
    *,
    base_url: str = DEFAULT_BASE_URL,
    locale: Locale = "zh",
    today: date | None = None,
    client: httpx.Client | None = None,
    timeout_seconds: float = 30.0,
) -> AutoArchiveSnapshot:
    """Collect backend facts and build a validated brief_snapshot_v1 payload."""
    issue_date = today or datetime.now(tz=BRIEF_TIME_ZONE).date()
    copy = _COPY[locale]
    owns_client = client is None
    http = client or httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=timeout_seconds,
        headers={"accept": "application/json"},
    )
    try:
        account = _fetch(http, "/api/paper/account")
        curve = _fetch(http, "/api/paper/account/equity-curve?days=7")
        performance = _fetch(http, "/api/paper/account/performance?range=3m")
        histories = {
            symbol: _fetch(
                http,
                "/api/market-data/history?"
                f"ticker={symbol}&start={_market_start(issue_date)}&end={issue_date}&freq=1d",
            )
            for symbol in MARKET_SYMBOLS
        }
        asia_radar = _fetch(http, "/api/asia-radar/summary?provider=futu")
        news = _fetch(http, "/api/news/items?mode=selected&take=6&preference=auto")
        runs = _fetch(http, "/api/runs/recent?limit=8")
        options_status = _fetch(http, "/api/options/daily-scan/status")
    finally:
        if owns_client:
            http.close()

    for blocking, label in (
        (account, "paper account"),
        (curve, "paper equity curve"),
        (performance, "paper account performance"),
    ):
        if blocking.error is not None or blocking.data is None:
            raise AutoArchiveUnavailable(
                f"brief auto-archive blocked: {label} unavailable ({blocking.error})"
            )

    captured_at = datetime.now(tz=BRIEF_TIME_ZONE)
    warnings: list[str] = []

    account_snapshot, account_entry = _map_account(account.data)
    equity_points, equity_entry = _map_equity_curve(curve.data)
    performance_snapshot, performance_entry = _map_performance(performance.data)

    market_snapshots: list[BriefMarketSnapshot] = []
    market_entries: list[BriefSourceState] = []
    market_move: list[dict[str, Any]] = []
    for symbol in MARKET_SYMBOLS:
        result = histories[symbol]
        snapshot, move, entry = _map_market(symbol, result)
        market_snapshots.append(snapshot)
        market_move.append(move)
        market_entries.append(entry)
        if result.error:
            warnings.append(f"market {symbol}: {result.error}")

    market_note = _build_market_note(market_move, copy)
    asia_radar_note, asia_entry = _map_asia_radar(asia_radar, copy)
    news_items, news_entry = _map_ai_news(news)
    log_entries, research_entry = _map_hermes_log(
        runs, options_status, locale, copy, captured_at
    )

    warnings.extend(
        error
        for error in (
            asia_radar.error and f"asia radar: {asia_radar.error}",
            news.error and f"ai news: {news.error}",
            runs.error and f"recent runs: {runs.error}",
            options_status.error and f"options scan status: {options_status.error}",
        )
        if error
    )

    paper_return = _paper_period_return(performance.data)
    lede = copy["lede"].format(
        equity=_format_money(account_snapshot.equity),
        paper_return=_format_signed_return(paper_return),
        range_label=copy["range_label"],
        market_note=market_note,
        asia_radar_note=asia_radar_note,
        digest_count=len(news_items),
    )

    payload = BriefArchivePayload(
        schema_version="brief_snapshot_v1",
        title=copy["title"],
        issue_date=issue_date,
        locale=locale,
        generated_at=captured_at,
        lede=lede,
        account=account_snapshot,
        paper_equity=equity_points,
        markets=market_snapshots,
        market_note=market_note,
        ai_news=news_items,
        hermes_log=log_entries,
        warnings=warnings,
        performance=performance_snapshot,
    )
    watermark = BriefSourceWatermark(
        captured_at=captured_at,
        sources=[
            account_entry,
            equity_entry,
            performance_entry,
            research_entry,
            news_entry,
            asia_entry,
            *market_entries,
        ],
    )
    return AutoArchiveSnapshot(
        payload=payload,
        source_watermark=watermark,
        warnings=warnings,
    )


def _fetch(client: httpx.Client, path: str) -> _FetchResult:
    try:
        response = client.get(path)
    except httpx.HTTPError as exc:
        return _FetchResult(data=None, error=f"{type(exc).__name__}: {exc}")
    if response.status_code != 200:
        return _FetchResult(
            data=None,
            error=f"HTTP {response.status_code} from {path.split('?')[0]}",
        )
    try:
        data = response.json()
    except ValueError:
        return _FetchResult(data=None, error=f"invalid JSON from {path.split('?')[0]}")
    if not isinstance(data, dict):
        return _FetchResult(data=None, error=f"unexpected payload from {path.split('?')[0]}")
    # Payload-level error detection: an HTTP 200 envelope that still carries an
    # explicit error marker is treated as unavailable, never as data.
    api_error = data.get("apiError")
    if isinstance(api_error, str) and api_error.strip():
        return _FetchResult(data=None, error=api_error.strip())
    return _FetchResult(data=data, error=None)


def _market_start(issue_date: date) -> date:
    return date.fromordinal(issue_date.toordinal() - 14)


def _finite(value: Any, fallback: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else fallback


def _iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _source_status(
    error: str | None, stale: bool = False
) -> Literal["available", "stale", "unavailable"]:
    if error:
        return "unavailable"
    return "stale" if stale else "available"


def _map_account(
    data: dict[str, Any],
) -> tuple[BriefAccountSnapshot, BriefSourceState]:
    price_source = data.get("price_source") or {}
    positions = [
        BriefAccountPosition(
            symbol=str(position.get("symbol") or ""),
            quantity=_finite(position.get("quantity")),
            avg_cost=_finite(position.get("avg_cost")),
            last_price=_finite(position.get("last_price")),
            market_value=_finite(position.get("market_value")),
            weight=_finite(position.get("weight")),
            unrealized_pnl=_finite(position.get("unrealized_pnl")),
            price_kind=str(position.get("price_kind") or "unavailable"),
            price_as_of=_iso(position.get("price_as_of")),
            previous_close=(
                _finite(position["previous_close"])
                if isinstance(position.get("previous_close"), (int, float))
                else None
            ),
            day_change_ratio=(
                _finite(position["day_change_ratio"])
                if isinstance(position.get("day_change_ratio"), (int, float))
                else None
            ),
            day_change_source=position.get("day_change_source") or None,
            day_change_as_of=_iso(position.get("day_change_as_of")),
        )
        for position in data.get("positions") or []
        if str(position.get("symbol") or "").strip()
    ]
    snapshot = BriefAccountSnapshot(
        account_id=str(data.get("account_id") or "unavailable"),
        base_currency=str(data.get("base_currency") or "USD"),
        equity=_finite(data.get("equity")),
        cash=_finite(data.get("cash")),
        pnl_abs=_finite(data.get("pnl_abs")),
        pnl_pct=_finite(data.get("pnl_pct")),
        invested_pct=_finite(data.get("invested_pct")),
        price_source=BriefPriceSource(
            kind=str(price_source.get("kind") or "unavailable"),
            as_of=_iso(price_source.get("as_of")),
        ),
        positions=positions,
    )
    entry = BriefSourceState(
        name="paper_account",
        status=_source_status(None, bool(data.get("stale"))),
        as_of=_iso(price_source.get("as_of")),
        detail=str(price_source.get("kind") or "unavailable"),
    )
    return snapshot, entry


def _map_equity_curve(
    data: dict[str, Any],
) -> tuple[list[BriefEquityPoint], BriefSourceState]:
    points = [
        BriefEquityPoint(
            timestamp=_iso(point.get("timestamp")) or datetime.now(tz=BRIEF_TIME_ZONE),
            equity=_finite(point.get("equity")),
            cash=_finite(point.get("cash")),
            market_value=_finite(point.get("market_value")),
            source=str(point.get("source") or "ledger"),
        )
        for point in data.get("points") or []
        if _iso(point.get("timestamp")) is not None
        and isinstance(point.get("equity"), (int, float))
        and isinstance(point.get("cash"), (int, float))
        and isinstance(point.get("market_value"), (int, float))
    ][-24:]
    entry = BriefSourceState(
        name="paper_equity",
        # The account endpoint stays reachable even before the first trading
        # day; its curve payload can legitimately contain zero points. That is
        # "unavailable", not "available" — and a single-point series anchors
        # to its real timestamp, never to "now".
        status="available" if points else "unavailable",
        as_of=points[-1].timestamp if points else None,
        detail=f"{len(points)} points",
    )
    return points, entry


def _map_performance(
    data: dict[str, Any],
) -> tuple[BriefPerformanceSnapshot, BriefSourceState]:
    series = [
        BriefPerformanceSeries(
            id=str(item.get("id") or ""),
            kind="paper" if item.get("kind") == "paper" else "benchmark",
            label=str(item.get("label") or item.get("id") or ""),
            symbol=item.get("symbol") or None,
            status=(
                item.get("status")
                if item.get("status") in {"available", "partial", "unavailable"}
                else "unavailable"
            ),
            source=item.get("source") or None,
            as_of=_iso(item.get("as_of")),
            error_code=item.get("error_code") or None,
            points=[
                BriefPerformancePoint(
                    date=date.fromisoformat(str(point.get("date"))),
                    return_ratio=_finite(point.get("return_ratio")),
                    equity=(
                        _finite(point["equity"])
                        if isinstance(point.get("equity"), (int, float))
                        else None
                    ),
                    close=(
                        _finite(point["close"])
                        if isinstance(point.get("close"), (int, float))
                        else None
                    ),
                )
                for point in item.get("points") or []
                if _valid_date(point.get("date"))
            ],
        )
        for item in data.get("series") or []
    ]
    snapshot = BriefPerformanceSnapshot(
        selected_range="7d",
        master_range="3m",
        granularity="1d",
        benchmarks=(
            [b for b in data.get("benchmarks") or [] if b in ("SPY", "QQQ")]
            or ["SPY", "QQQ"]
        ),
        # performance is a blocking source: a 200 payload without the requested
        # window is malformed, not "empty coverage" — fail the archive instead
        # of crashing on KeyError mid-build.
        requested_start=_required_date(data, "requested_start", "paper_performance"),
        requested_end=_required_date(data, "requested_end", "paper_performance"),
        actual_start=(
            date.fromisoformat(str(data["actual_start"]))
            if data.get("actual_start")
            else None
        ),
        actual_end=(
            date.fromisoformat(str(data["actual_end"])) if data.get("actual_end") else None
        ),
        coverage_complete=bool(data.get("coverage_complete")),
        series=series,
        warnings=[str(w) for w in data.get("warnings") or []],
    )
    as_of = max(
        (s.as_of for s in series if s.as_of is not None),
        default=None,
    )
    entry = BriefSourceState(
        name="paper_performance",
        status="available" if snapshot.coverage_complete else "stale",
        as_of=as_of,
        detail=f"range=3m · {len(series)} series",
    )
    return snapshot, entry


def _valid_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value))
    except ValueError:
        return False
    return True


def _required_date(data: dict[str, Any], key: str, source_label: str) -> date:
    value = data.get(key)
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise AutoArchiveUnavailable(
            f"brief auto-archive blocked: {source_label} payload missing a valid {key}"
        ) from None


def _map_market(
    symbol: str,
    result: _FetchResult,
) -> tuple[BriefMarketSnapshot, dict[str, Any], BriefSourceState]:
    data = result.data or {}
    rows = [
        row
        for row in data.get("rows") or []
        if isinstance(row.get("close"), (int, float)) and math.isfinite(row["close"])
    ]
    latest = rows[-1] if rows else None
    previous = rows[-2] if len(rows) >= 2 else None
    change_pct = None
    if latest is not None and previous is not None and previous.get("close"):
        change_pct = latest["close"] / previous["close"] - 1
    source = data.get("source") or None
    snapshot = BriefMarketSnapshot(
        symbol=symbol,
        last=_finite(latest["close"]) if latest else None,
        change_pct=change_pct,
        source=None if result.error else source,
        as_of=_iso(latest.get("timestamp")) if latest else None,
    )
    move = {"symbol": symbol, "change_pct": change_pct}
    entry = BriefSourceState(
        name=f"market_{symbol}",
        status=_source_status(result.error),
        as_of=_iso(latest.get("timestamp")) if latest else None,
        detail=result.error or source,
    )
    return snapshot, move, entry


def _format_percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _format_money(value: float) -> str:
    return f"${value:,.2f}"


def _format_signed_return(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "--"
    return f"{'▲' if value >= 0 else '▼'} {abs(value):.2f}%"


def _format_market_change(change_pct: float | None) -> str:
    if change_pct is None:
        return "--"
    return f"{'▲' if change_pct >= 0 else '▼'} {_format_percent(abs(change_pct))}"


def _semis_vs_software_note(
    moves: list[dict[str, Any]],
    copy: dict[str, str],
) -> str:
    soxx = next((m for m in moves if m["symbol"] == "SOXX"), None)
    igv = next((m for m in moves if m["symbol"] == "IGV"), None)
    if not soxx or not igv or soxx["change_pct"] is None or igv["change_pct"] is None:
        return ""
    diff = soxx["change_pct"] - igv["change_pct"]
    if abs(diff) < 0.002:
        return copy["semis_inline"]
    if diff > 0:
        return copy["semis_stronger"].format(diff=_format_percent(abs(diff)))
    return copy["software_stronger"].format(diff=_format_percent(abs(diff)))


def _build_market_note(moves: list[dict[str, Any]], copy: dict[str, str]) -> str:
    complete = [m for m in moves if m["change_pct"] is not None]
    if len(complete) < 4:
        return copy["quote"]
    strongest = max(complete, key=lambda m: m["change_pct"])
    weakest = min(complete, key=lambda m: m["change_pct"])
    up_count = sum(1 for m in complete if m["change_pct"] >= 0)
    return copy["market_note"].format(
        up_count=up_count,
        strongest=strongest["symbol"],
        strongest_change=_format_market_change(strongest["change_pct"]),
        weakest=weakest["symbol"],
        weakest_change=_format_market_change(weakest["change_pct"]),
        relative=_semis_vs_software_note(complete, copy),
    )


def _map_asia_radar(
    result: _FetchResult,
    copy: dict[str, str],
) -> tuple[str, BriefSourceState]:
    summary = result.data or {}
    available = (
        result.error is None
        and summary.get("status") == "available"
    )
    if not available:
        note = copy["asia_unavailable"]
    else:
        top = summary.get("top_ytd_symbol")
        bottom = summary.get("bottom_ytd_symbol")
        spread = summary.get("spread_pct")
        if not top or not bottom or spread is None:
            note = copy["asia_coverage"].format(
                count=summary.get("market_count", 0),
                as_of=summary.get("as_of"),
            )
        else:
            note = copy["asia_full"].format(
                as_of=summary.get("as_of"),
                winners="/".join(summary.get("winner_symbols") or []),
                laggards="/".join(summary.get("laggard_symbols") or []),
                spread=f"{abs(float(spread)):.1f}%",
            )
    entry = BriefSourceState(
        name="asia_radar",
        status="available" if available else "unavailable",
        as_of=_iso(summary.get("as_of")) or _iso(summary.get("fetched_at")),
        detail=result.error
        or f"{summary.get('provider', 'futu')}/{summary.get('provenance', 'unknown')}",
        provider="futu",
        served_from=summary.get("provenance") or None,
    )
    return note, entry


def _map_ai_news(result: _FetchResult) -> tuple[list[BriefAiNewsItem], BriefSourceState]:
    data = result.data or {}
    warnings = [str(w) for w in data.get("warnings") or []]
    items = [
        BriefAiNewsItem(
            id=str(item.get("id") or ""),
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            source=str(item.get("source") or ""),
            published_at=_iso(item.get("published_at")),
            summary=item.get("summary") or None,
            category=item.get("category") or None,
            score=(
                _finite(item["score"])
                if isinstance(item.get("score"), (int, float))
                else None
            ),
        )
        for item in data.get("items") or []
        if str(item.get("id") or "").strip()
        and str(item.get("title") or "").strip()
        and str(item.get("url") or "").strip()
        and str(item.get("source") or "").strip()
    ][:6]
    if result.error:
        items = []
    provider = str(data.get("provider") or "unknown")
    served_from = str(data.get("served_from") or "primary")
    short_warnings = "; ".join(w.strip() for w in warnings[:2] if w.strip())
    detail = result.error or f"{provider}/{served_from}"
    if not result.error and short_warnings:
        detail = f"{detail}; {short_warnings}"
    entry = BriefSourceState(
        name="ai_news",
        status=_source_status(
            result.error,
            any("cache" in w.lower() or "stale" in w.lower() for w in warnings),
        ),
        as_of=_iso(data.get("fetched_at")),
        detail=detail,
        provider=provider,
        served_from=served_from,
    )
    return items, entry


def _map_hermes_log(
    runs: _FetchResult,
    options_status: _FetchResult,
    locale: Locale,
    copy: dict[str, str],
    captured_at: datetime,
) -> tuple[list[BriefHermesLogEntry], BriefSourceState]:
    entries: list[BriefHermesLogEntry] = []
    for run in (runs.data or {}).get("runs", [])[:5]:
        kind = str(run.get("kind") or "paper")
        if kind not in {"backtest", "factor", "paper", "replication"}:
            kind = "paper"
        sample = "sample" in str(run.get("source") or "").lower()
        prefix_key = f"run_{kind}{'_sample' if sample else ''}"
        entries.append(
            BriefHermesLogEntry(
                timestamp=_iso(run.get("created_at")),
                status="warn" if sample else "ok",
                text=f"{copy[prefix_key]} · {run.get('run_id')}",
                href=None,
                summary=str(run.get("run_id") or "") or None,
            )
        )
    status = (options_status.data or {}).get("status")
    if options_status.error is None and isinstance(status, dict) and status.get("status"):
        strategies = status.get("strategies") or []
        strategies_text = " / ".join(str(s) for s in strategies) if strategies else "--"
        done = status.get("status") == "completed"
        status_text = status.get("status")
        if locale == "zh":
            status_text = "完成" if done else "更新"
        entries.append(
            BriefHermesLogEntry(
                timestamp=_iso(status.get("finished_at")) or _iso(status.get("started_at")),
                status="ok" if done else "warn",
                text=copy["scan_entry"].format(
                    status=status_text, strategies=strategies_text
                ),
                href=None,
                summary=f"provider={status['provider']}" if status.get("provider") else None,
            )
        )
    entries.append(
        BriefHermesLogEntry(
            timestamp=captured_at,
            status="warn",
            text=copy["printed"],
            href=None,
            summary=None,
        )
    )
    error = runs.error or options_status.error
    entry = BriefSourceState(
        name="research_activity",
        status=_source_status(error),
        as_of=_iso((runs.data or {}).get("generated_at")),
        detail=error or f"{len(entries)} entries",
    )
    return entries[:8], entry


def _paper_period_return(performance: dict[str, Any]) -> float | None:
    """Rebased 7-day paper return, mirroring selectBriefPerformanceSeries."""
    paper = next(
        (s for s in performance.get("series") or [] if s.get("id") == "paper"),
        None,
    )
    if paper is None:
        return None
    points = [
        p for p in paper.get("points") or [] if _valid_date(p.get("date"))
    ]
    if not points:
        return None
    last_date = str(performance.get("actual_end") or max(str(p["date"]) for p in points))
    start = _performance_range_start(last_date, "7d")
    window = sorted(
        (p for p in points if start <= str(p["date"]) <= last_date),
        key=lambda p: str(p["date"]),
    )
    if not window:
        return None
    base = 1 + _finite(window[0].get("return_ratio"))
    if base <= 0:
        return None
    rebased_last = (1 + _finite(window[-1].get("return_ratio"))) / base - 1
    return rebased_last * 100


def _performance_range_start(end_value: str, selected_range: str) -> str:
    end = date.fromisoformat(end_value)
    if selected_range == "7d":
        return date.fromordinal(end.toordinal() - 6).isoformat()
    months = 1 if selected_range == "1m" else 3
    absolute_month = end.year * 12 + (end.month - 1) - months
    year, month_zero = divmod(absolute_month, 12)
    month = month_zero + 1
    if month == 12:
        days_in_month = 31
    else:
        days_in_month = date(year, month + 1, 1).toordinal() - date(year, month, 1).toordinal()
    return date(year, month, min(end.day, days_in_month)).isoformat()
