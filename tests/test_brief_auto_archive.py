from __future__ import annotations

from datetime import date

import httpx
import pytest

from quant_system.brief.auto_archive import (
    AutoArchiveUnavailable,
    build_auto_archive_snapshot,
)

ISSUE_DATE = date(2026, 8, 11)


def _account_payload() -> dict:
    return {
        "account_id": "default",
        "base_currency": "USD",
        "equity": 101234.5,
        "cash": 61234.5,
        "pnl_abs": 1234.5,
        "pnl_pct": 0.01234,
        "invested_pct": 0.4,
        "kill_switch": True,
        "price_source": {"kind": "futu", "as_of": "2026-08-11T08:29:00+08:00"},
        "positions": [
            {
                "symbol": "AAPL",
                "quantity": 10,
                "avg_cost": 200.0,
                "last_price": 210.0,
                "market_value": 2100.0,
                "weight": 0.0207,
                "unrealized_pnl": 100.0,
                "price_kind": "realtime",
                "price_as_of": "2026-08-11T08:29:00+08:00",
            }
        ],
        "pending_orders": [],
        "stale": False,
    }


def _curve_payload() -> dict:
    return {
        "account_id": "default",
        "points": [
            {
                "timestamp": "2026-08-11T08:29:00+08:00",
                "equity": 101234.5,
                "cash": 61234.5,
                "market_value": 40000.0,
                "realized_pnl": 0.0,
                "source": "current_quote",
            }
        ],
    }


def _performance_payload() -> dict:
    return {
        "account_id": "default",
        "range": "3m",
        "granularity": "1d",
        "benchmarks": ["SPY", "QQQ"],
        "requested_start": "2026-05-11",
        "requested_end": "2026-08-11",
        "actual_start": "2026-05-11",
        "actual_end": "2026-08-11",
        "coverage_complete": True,
        "series": [
            {
                "id": "paper",
                "kind": "paper",
                "label": "模拟盘",
                "symbol": None,
                "status": "available",
                "source": "paper_account_ledger+futu_qfq_1d",
                "as_of": "2026-08-11T08:29:00+08:00",
                "error_code": None,
                "points": [
                    {
                        "date": "2026-08-04",
                        "return_ratio": 0.0,
                        "equity": 100000.0,
                        "close": None,
                    },
                    {
                        "date": "2026-08-11",
                        "return_ratio": 0.012345,
                        "equity": 101234.5,
                        "close": None,
                    },
                ],
            }
        ],
        "warnings": [],
    }


def _history_payload(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "ticker": symbol,
        "source": "futu",
        "frequency": "1d",
        "row_count": 2,
        "rows": [
            {
                "timestamp": "2026-08-08T00:00:00Z",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 100.0,
                "volume": 1,
            },
            {
                "timestamp": "2026-08-11T00:00:00Z",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 101.0,
                "volume": 1,
            },
        ],
        "metadata": {"provider": "futu", "requested_provider": "futu", "fetched_at": None},
    }


def _asia_radar_payload() -> dict:
    return {
        "schema_version": "1.1",
        "provider": "futu",
        "as_of": "2026-08-10",
        "timezone": "America/New_York",
        "fetched_at": "2026-08-11T09:05:00Z",
        "provenance": "futu",
        "status": "available",
        "market_count": 12,
        "winner_symbols": ["EWY", "EWJ", "EWT"],
        "laggard_symbols": ["EIDO", "EWM", "EWS"],
        "spread_pct": 59.4,
        "top_ytd_symbol": "EWY",
        "top_ytd_pct": 61.2,
        "bottom_ytd_symbol": "EIDO",
        "bottom_ytd_pct": -4.1,
        "markets": [],
    }


def _news_payload() -> dict:
    return {
        "provider": "aihot",
        "served_from": "primary",
        "fetched_at": "2026-08-11T09:00:00Z",
        "count": 1,
        "items": [
            {
                "id": "news-1",
                "title": "A new model was released",
                "url": "https://example.com/news-1",
                "source": "example",
                "published_at": "2026-08-11T01:00:00Z",
                "summary": "A factual summary.",
                "category": "models",
                "score": 9.1,
            }
        ],
        "warnings": [],
    }


def _runs_payload() -> dict:
    return {
        "total": 2,
        "generated_at": "2026-08-11T08:00:00Z",
        "runs": [
            {
                "kind": "backtest",
                "run_id": "run-1",
                "source": "local",
                "created_at": "2026-08-11T07:00:00Z",
                "summary": {},
            },
            {
                "kind": "paper",
                "run_id": "run-2",
                "source": "sample_seed",
                "created_at": "2026-08-11T07:30:00Z",
                "summary": {},
            },
        ],
    }


def _options_status_payload() -> dict:
    return {
        "exists": True,
        "status_path": "/x",
        "status": {
            "status": "completed",
            "strategies": ["csp"],
            "provider": "futu",
            "started_at": "2026-08-11T06:00:00Z",
            "finished_at": "2026-08-11T06:30:00Z",
        },
    }


def _routes(overrides: dict[str, tuple[int, dict]] | None = None) -> dict[str, tuple[int, dict]]:
    routes: dict[str, tuple[int, dict]] = {
        "/api/paper/account": (200, _account_payload()),
        "/api/paper/account/equity-curve": (200, _curve_payload()),
        "/api/paper/account/performance": (200, _performance_payload()),
        "/api/asia-radar/summary": (200, _asia_radar_payload()),
        "/api/news/items": (200, _news_payload()),
        "/api/runs/recent": (200, _runs_payload()),
        "/api/options/daily-scan/status": (200, _options_status_payload()),
    }
    for symbol in ("SPY", "QQQ", "SOXX", "IGV"):
        routes[f"/api/market-data/history?ticker={symbol}"] = (200, _history_payload(symbol))
    if overrides:
        routes.update(overrides)
    return routes


def _client(routes: dict[str, tuple[int, dict]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.query:
            key = f"{request.url.path}?{request.url.query.decode()}"
        else:
            key = request.url.path
        matches = [route_key for route_key in routes if key.startswith(route_key)]
        if not matches:
            return httpx.Response(404, json={"detail": "unknown test route"})
        status, payload = routes[max(matches, key=len)]
        return httpx.Response(status, json=payload)

    return httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )


def test_builds_valid_snapshot_from_backend_facts() -> None:
    client = _client(_routes())
    snapshot = build_auto_archive_snapshot(
        locale="zh",
        today=ISSUE_DATE,
        client=client,
    )

    payload = snapshot.payload
    assert payload.schema_version == "brief_snapshot_v1"
    assert payload.issue_date == ISSUE_DATE
    assert payload.locale == "zh"
    assert payload.title == "每日晨报"
    assert "101,234.50" in payload.lede
    assert payload.account.equity == pytest.approx(101234.5)
    assert payload.account.price_source.kind == "futu"
    assert len(payload.paper_equity) == 1
    assert [m.symbol for m in payload.markets] == ["SPY", "QQQ", "SOXX", "IGV"]
    assert all(m.change_pct == pytest.approx(0.01) for m in payload.markets)
    assert "4/4 收涨" in payload.market_note
    assert len(payload.ai_news) == 1
    assert payload.performance is not None
    assert payload.performance.master_range == "3m"
    # hermes log: 2 runs + options scan + printed entry
    assert len(payload.hermes_log) == 4
    sample_entry = next(e for e in payload.hermes_log if "run-2" in e.text)
    assert sample_entry.status == "warn"
    assert "SAMPLE" in sample_entry.text

    watermark = snapshot.source_watermark
    names = [source.name for source in watermark.sources]
    assert names == [
        "paper_account",
        "paper_equity",
        "paper_performance",
        "research_activity",
        "ai_news",
        "asia_radar",
        "market_SPY",
        "market_QQQ",
        "market_SOXX",
        "market_IGV",
    ]
    assert all(source.status == "available" for source in watermark.sources)


def test_english_locale_copy() -> None:
    snapshot = build_auto_archive_snapshot(
        locale="en",
        today=ISSUE_DATE,
        client=_client(_routes()),
    )
    assert snapshot.payload.title == "Daily Morning Brief"
    assert "4/4 watched ETFs are up today" in snapshot.payload.market_note


def test_fails_closed_when_paper_account_is_unavailable() -> None:
    client = _client(_routes({"/api/paper/account": (503, {"detail": "db down"})}))
    with pytest.raises(AutoArchiveUnavailable, match="paper account"):
        build_auto_archive_snapshot(locale="zh", today=ISSUE_DATE, client=client)


def test_fails_closed_on_payload_level_error_marker() -> None:
    # HTTP 200 carrying an explicit apiError marker must not be read as data.
    client = _client(
        _routes({"/api/paper/account/performance": (200, {"apiError": "upstream failed"})})
    )
    with pytest.raises(AutoArchiveUnavailable, match="performance"):
        build_auto_archive_snapshot(locale="zh", today=ISSUE_DATE, client=client)


def test_fails_closed_when_performance_lacks_requested_window() -> None:
    # performance is a blocking source: a 200 payload without requested_start /
    # requested_end is malformed — the archive must fail with a typed error,
    # never crash on KeyError mid-build.
    payload = _performance_payload()
    del payload["requested_start"]
    client = _client(_routes({"/api/paper/account/performance": (200, payload)}))
    with pytest.raises(AutoArchiveUnavailable, match="paper_performance"):
        build_auto_archive_snapshot(locale="zh", today=ISSUE_DATE, client=client)


def test_empty_equity_curve_is_watermarked_unavailable() -> None:
    # A fresh paper account can return a reachable-but-empty curve; the
    # watermark must say "unavailable", not claim availability over 0 points.
    client = _client(
        _routes(
            {"/api/paper/account/equity-curve": (200, {"account_id": "default", "points": []})}
        )
    )
    snapshot = build_auto_archive_snapshot(locale="zh", today=ISSUE_DATE, client=client)
    statuses = {s.name: s.status for s in snapshot.source_watermark.sources}
    assert statuses["paper_equity"] == "unavailable"
    equity_entry = next(
        s for s in snapshot.source_watermark.sources if s.name == "paper_equity"
    )
    assert equity_entry.as_of is None


def test_degraded_optional_sources_become_honest_warnings() -> None:
    client = _client(
        _routes(
            {
                "/api/asia-radar/summary": (502, {"detail": "futu down"}),
                "/api/news/items": (500, {"detail": "news down"}),
                "/api/market-data/history?ticker=IGV": (500, {"detail": "igv down"}),
            }
        )
    )
    snapshot = build_auto_archive_snapshot(locale="zh", today=ISSUE_DATE, client=client)

    payload = snapshot.payload
    assert payload.ai_news == []
    igv = next(m for m in payload.markets if m.symbol == "IGV")
    assert igv.last is None and igv.change_pct is None
    # IGV change missing -> incomplete market read falls back to the honest quote
    assert payload.market_note.startswith("市场涨跌数据暂不完整")
    assert "亚洲雷达数据暂不可用" in payload.lede
    assert any("asia radar" in w for w in snapshot.warnings)
    assert any("ai news" in w for w in snapshot.warnings)
    statuses = {s.name: s.status for s in snapshot.source_watermark.sources}
    assert statuses["asia_radar"] == "unavailable"
    assert statuses["ai_news"] == "unavailable"
    assert statuses["market_IGV"] == "unavailable"
    assert statuses["market_SPY"] == "available"


def test_semis_relative_note_in_market_note() -> None:
    routes = _routes()
    soxx = _history_payload("SOXX")
    igv = _history_payload("IGV")
    soxx["rows"][1]["close"] = 103.0  # SOXX +3%
    igv["rows"][1]["close"] = 100.5  # IGV +0.5%
    routes["/api/market-data/history?ticker=SOXX"] = (200, soxx)
    routes["/api/market-data/history?ticker=IGV"] = (200, igv)
    snapshot = build_auto_archive_snapshot(
        locale="zh", today=ISSUE_DATE, client=_client(routes)
    )
    assert "SOXX" in snapshot.payload.market_note
    assert "半导体（SOXX）相对软件（IGV）偏强" in snapshot.payload.market_note
