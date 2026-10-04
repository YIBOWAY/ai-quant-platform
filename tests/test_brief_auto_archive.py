from __future__ import annotations

from datetime import date

import httpx
import pytest

from quant_system.brief.auto_archive import (
    _COPY,
    AutoArchiveUnavailable,
    build_auto_archive_snapshot,
    compose_brief_lede,
)
from quant_system.research.paper_evaluation import _digest, _empty_facts

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
        "/api/paper-evaluation": (200, {"status": "unavailable", "analysis": None}),
        "/api/assistant/remote/book": (
            200,
            {
                "contract": "hqa.assistant_remote_book/v1",
                "candidates": [],
                "requests": [],
                "verified_count": 0,
                "hung_count": 0,
                "fossil_count": 4,
                "fossils": [],
            },
        ),
        "/api/paper/strategy-sleeves/hung-effect": (
            200,
            {
                "hung_count": 0,
                "observation_day_count": 0,
                "empty": True,
                "sleeve_equity": None,
                "sleeve_equity_status": "empty",
                "sleeve_return_pct": None,
            },
        ),
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
    assert payload.title == "量化日报"
    assert "101,234.50" in payload.lede
    assert "模拟账户总资产" in payload.lede
    assert "行情截至 2026-08-11" in payload.lede
    assert not payload.lede.startswith("今晨，模拟盘权益报")
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
        "paper_evaluation",
        "market_SPY",
        "market_QQQ",
        "market_SOXX",
        "market_IGV",
    ]
    assert all(
        source.status == "available"
        for source in watermark.sources
        if source.name != "paper_evaluation"
    )
    assert (
        next(source for source in watermark.sources if source.name == "paper_evaluation").status
        == "unavailable"
    )


def test_archive_keeps_cost_reference_but_never_calls_it_market_equity() -> None:
    account = _account_payload()
    account["positions"][0]["price_kind"] = "avg_cost_fallback"
    account["price_source"]["kind"] = "mixed"
    client = _client(_routes({"/api/paper/account": (200, account)}))
    result = build_auto_archive_snapshot(locale="zh", today=ISSUE_DATE, client=client)
    assert result.payload.account.valuation_status == "incomplete"
    assert result.payload.account.market_equity is None
    assert result.payload.account.unpriced_symbols == ["AAPL"]
    assert "101,234.50" not in result.payload.lede
    account_source = next(
        item for item in result.source_watermark.sources if item.name == "paper_account"
    )
    assert account_source.status == "stale"


def test_archive_preserves_explicit_unknown_market_equity() -> None:
    account = {**_account_payload(), "valuation_status": "complete", "market_equity": None}
    client = _client(_routes({"/api/paper/account": (200, account)}))
    result = build_auto_archive_snapshot(locale="zh", today=ISSUE_DATE, client=client)
    assert result.payload.account.valuation_status == "incomplete"
    assert result.payload.account.market_equity is None
    assert "101,234.50" not in result.payload.lede


def test_english_locale_copy() -> None:
    snapshot = build_auto_archive_snapshot(
        locale="en",
        today=ISSUE_DATE,
        client=_client(_routes()),
    )
    assert snapshot.payload.title == "Daily Brief"
    assert "4/4 watched ETFs are up today" in snapshot.payload.market_note
    assert "Account inventory" in snapshot.payload.lede
    assert "Market bars through 2026-08-11" in snapshot.payload.lede


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
        _routes({"/api/paper/account/equity-curve": (200, {"account_id": "default", "points": []})})
    )
    snapshot = build_auto_archive_snapshot(locale="zh", today=ISSUE_DATE, client=client)
    statuses = {s.name: s.status for s in snapshot.source_watermark.sources}
    assert statuses["paper_equity"] == "unavailable"
    equity_entry = next(s for s in snapshot.source_watermark.sources if s.name == "paper_equity")
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


def test_lede_uses_inventory_copy_when_hung_count_is_zero() -> None:
    lede = compose_brief_lede(
        copy=_COPY["zh"],
        hung_count=0,
        book_available=True,
        equity="$1.00",
        paper_return="▲ 1.00%",
        range_label="近 7 日",
        market_note="今日四个观察指数中 0/4 收涨。",
        asia_radar_note="",
        digest_count=2,
        market_as_of="2026-08-14",
    )
    assert lede.startswith("市场方面，")
    assert "模拟账户总资产" in lede
    assert "行情截至 2026-08-14" in lede
    assert "模拟盘权益报" not in lede


def test_lede_uses_hung_copy_when_official_book_has_a_sleeve() -> None:
    lede = compose_brief_lede(
        copy=_COPY["zh"],
        hung_count=1,
        book_available=True,
        equity="$101,234.50",
        paper_return="▲ 1.00%",
        range_label="近 7 日",
        market_note="今日四个观察指数中 1/4 收涨。",
        asia_radar_note="",
        digest_count=1,
        market_as_of="2026-08-14",
        sleeve_equity="$10,000.00",
        sleeve_observation="尚未入账",
    )
    assert "已启用 1 条模拟策略" in lede
    assert "最近可用策略估值 $10,000.00" in lede
    assert "不代表实时资产" in lede
    assert "观察结果 尚未入账" in lede
    assert "模拟账户总资产" in lede
    assert "已挂观察权益报" not in lede
    assert "已挂观察权益报 $101,234.50" not in lede
    assert "行情截至 2026-08-14" in lede


def test_snapshot_hung_lede_does_not_call_full_account_observation() -> None:
    snapshot = build_auto_archive_snapshot(
        locale="zh",
        today=ISSUE_DATE,
        client=_client(
            _routes(
                {
                    "/api/assistant/remote/book": (
                        200,
                        {
                            "contract": "hqa.assistant_remote_book/v1",
                            "candidates": [
                                {
                                    "candidate_id": "artifact-d489583fb04bdc04",
                                    "status": "hung",
                                    "sleeve_id": "sleeve-hung-1",
                                    "source_digest": "d4" * 32,
                                    "fossil": False,
                                }
                            ],
                            "requests": [],
                            "verified_count": 0,
                            "hung_count": 1,
                            "fossil_count": 4,
                            "fossils": [],
                        },
                    ),
                    "/api/paper/strategy-sleeves": (
                        200,
                        {
                            "sleeves": [
                                {
                                    "sleeve_id": "sleeve-hung-1",
                                    "cash": 94.06,
                                }
                            ]
                        },
                    ),
                    "/api/paper/strategy-sleeves/hung-effect": (
                        200,
                        {
                            "hung_count": 1,
                            "observation_day_count": 1,
                            "empty": False,
                            "sleeve_equity": 10_009.637481431073,
                            "sleeve_equity_status": "available",
                            "sleeve_return_pct": 0.0,
                        },
                    ),
                }
            )
        ),
    )
    assert "已启用 1 条模拟策略" in snapshot.payload.lede
    assert "最近可用策略估值 $10,009.64" in snapshot.payload.lede
    assert "成交 1 日 · 首个成交收盘起算 ▲ 0.00%" in snapshot.payload.lede
    assert "估值截至" in snapshot.payload.lede
    assert "今晨" not in snapshot.payload.lede
    assert "$94.06" not in snapshot.payload.lede
    assert "模拟账户总资产" in snapshot.payload.lede
    assert "已挂观察权益报" not in snapshot.payload.lede
    assert "已挂观察权益报 $101,234.50" not in snapshot.payload.lede


def test_snapshot_distinguishes_effect_unavailable_from_not_booked() -> None:
    snapshot = build_auto_archive_snapshot(
        locale="zh",
        today=ISSUE_DATE,
        client=_client(
            _routes(
                {
                    "/api/assistant/remote/book": (
                        200,
                        {
                            "hung_count": 1,
                            "candidates": [],
                            "requests": [],
                            "verified_count": 0,
                            "fossil_count": 0,
                            "fossils": [],
                        },
                    ),
                    "/api/paper/strategy-sleeves/hung-effect": (
                        200,
                        {
                            "hung_count": 1,
                            "observation_day_count": 1,
                            "empty": False,
                            "sleeve_equity": None,
                            "sleeve_equity_status": "unavailable",
                            "sleeve_equity_reason": "strategy_price_unavailable",
                            "sleeve_return_pct": None,
                        },
                    ),
                }
            )
        ),
    )

    assert "观察结果 1 日 · 效果暂不可用" in snapshot.payload.lede
    assert "尚未入账" not in snapshot.payload.lede


def test_snapshot_keeps_not_booked_only_for_a_true_empty_effect() -> None:
    snapshot = build_auto_archive_snapshot(
        locale="zh",
        today=ISSUE_DATE,
        client=_client(
            _routes(
                {
                    "/api/assistant/remote/book": (
                        200,
                        {
                            "hung_count": 1,
                            "candidates": [],
                            "requests": [],
                            "verified_count": 0,
                            "fossil_count": 0,
                            "fossils": [],
                        },
                    ),
                    "/api/paper/strategy-sleeves/hung-effect": (
                        200,
                        {
                            "hung_count": 1,
                            "observation_day_count": 0,
                            "empty": True,
                            "sleeve_equity": None,
                            "sleeve_equity_status": "empty",
                            "sleeve_return_pct": None,
                        },
                    ),
                }
            )
        ),
    )

    assert "观察结果 尚无成交" in snapshot.payload.lede
    assert "效果暂不可用" not in snapshot.payload.lede


@pytest.mark.parametrize(
    "effect_response",
    [
        (503, {"detail": "down"}),
        (
            200,
            {
                "hung_count": 2,
                "observation_day_count": 1,
                "empty": False,
                "sleeve_equity": 20_000.0,
                "sleeve_equity_status": "available",
                "sleeve_return_pct": 0.0,
            },
        ),
    ],
)
def test_snapshot_marks_effect_error_or_count_mismatch_unavailable(
    effect_response,
) -> None:
    snapshot = build_auto_archive_snapshot(
        locale="zh",
        today=ISSUE_DATE,
        client=_client(
            _routes(
                {
                    "/api/assistant/remote/book": (
                        200,
                        {
                            "hung_count": 1,
                            "candidates": [],
                            "requests": [],
                            "verified_count": 0,
                            "fossil_count": 0,
                            "fossils": [],
                        },
                    ),
                    "/api/paper/strategy-sleeves/hung-effect": effect_response,
                }
            )
        ),
    )

    assert "观察结果 效果暂不可用" in snapshot.payload.lede
    assert "尚未入账" not in snapshot.payload.lede


def test_missing_book_does_not_block_archive_and_avoids_strategy_pnl_claim() -> None:
    snapshot = build_auto_archive_snapshot(
        locale="zh",
        today=ISSUE_DATE,
        client=_client(_routes({"/api/assistant/remote/book": (404, {"detail": "no"})})),
    )
    assert "模拟账户总资产" in snapshot.payload.lede
    assert any("remote book" in w for w in snapshot.warnings)


def test_semis_relative_note_in_market_note() -> None:
    routes = _routes()
    soxx = _history_payload("SOXX")
    igv = _history_payload("IGV")
    soxx["rows"][1]["close"] = 103.0  # SOXX +3%
    igv["rows"][1]["close"] = 100.5  # IGV +0.5%
    routes["/api/market-data/history?ticker=SOXX"] = (200, soxx)
    routes["/api/market-data/history?ticker=IGV"] = (200, igv)
    snapshot = build_auto_archive_snapshot(locale="zh", today=ISSUE_DATE, client=_client(routes))
    assert "SOXX" in snapshot.payload.market_note
    assert "半导体（SOXX）相对软件（IGV）偏强" in snapshot.payload.market_note


def _matching_paper_evaluation():
    series = [
        {
            "date": "2026-08-08",
            "sleeve_equity": 1000,
            "sleeve_pct": 0,
            "spy_close": 100,
            "spy_pct": 0,
        },
        {
            "date": "2026-08-11",
            "sleeve_equity": 1010,
            "sleeve_pct": 1,
            "spy_close": 102,
            "spy_pct": 2,
        },
    ]
    effect = {
        "hung_count": 1,
        "observation_day_count": 2,
        "empty": False,
        "sleeve_equity_status": "available",
        "sleeve_equity": 1010,
        "sleeve_return_pct": 1,
        "spy_return_pct": 2,
        "cost_drag_pct": 0.12,
        "turnover": 1.2,
        "series": series,
        "as_of": "2026-08-11",
    }
    facts = {
        **_empty_facts(),
        "status": "partial",
        "as_of": "2026-08-11",
        "sleeves": [{"sleeve_id": "sleeve-test"}],
        "period": {
            "start": "2026-08-08",
            "end": "2026-08-11",
            "observation_count": 2,
            "basis": "committed_holdings_daily_prices",
        },
        "metrics": {
            "sleeve_equity_usd": 1010,
            "sleeve_return_pct": 1,
            "spy_return_pct": 2,
            "commission_drag_pct": 0.12,
            "turnover": 1.2,
        },
        "observation_series": series,
        "evidence": [{"id": key} for key in ("coverage", "performance", "costs", "prediction")],
    }
    evaluation = {
        "status": "partial",
        "as_of": facts["as_of"],
        "error": None,
        "input_digest": _digest(facts),
        "facts": facts,
        "updated_at": "2026-08-11T09:20:00Z",
        "analysis": {
            "summary": "已记录区间上涨 1%，仍落后同区间 SPY 1 个百分点。[performance]",
            "observations": ["已列出实际佣金。[costs]"],
            "explanations": ["两个成交观察点不能代表完整日净值。[coverage]"],
            "limitations": ["未保存预测分数，无法判断在线 IC。[prediction]"],
            "model": "grok-4.6",
            "reasoning_effort": "xhigh",
            "generated_at": "2026-08-11T09:20:00Z",
        },
    }
    return evaluation, effect


def _snapshot_with_evaluation(document, effect, *, locale="zh", today=ISSUE_DATE):
    return build_auto_archive_snapshot(
        locale=locale,
        today=today,
        client=_client(
            _routes(
                {
                    "/api/paper-evaluation": (200, document),
                    "/api/paper/strategy-sleeves/hung-effect": (200, effect),
                    "/api/assistant/remote/book": (200, {"hung_count": 1}),
                }
            )
        ),
    )


def test_matching_grok_summary_is_archived_with_date_and_source():
    document, effect = _matching_paper_evaluation()
    snapshot = _snapshot_with_evaluation(document, effect)
    assert "Grok 模拟运行解读（估值截至 2026-08-11）" in snapshot.payload.lede
    assert "仍落后同区间 SPY 1 个百分点" in snapshot.payload.lede
    assert "[performance]" not in snapshot.payload.lede
    source = next(s for s in snapshot.source_watermark.sources if s.name == "paper_evaluation")
    assert source.status == "available"
    assert source.as_of.date() == ISSUE_DATE
    assert document["input_digest"] in source.detail
    assert not any("paper evaluation:" in text for text in snapshot.warnings)


@pytest.mark.parametrize(
    "change", ["as_of", "return", "turnover", "commission", "series", "model", "failed", "future"]
)
def test_stale_failed_or_mismatched_paper_summary_never_enters_archive(change):
    document, effect = _matching_paper_evaluation()
    if change == "as_of":
        document["as_of"] = "2026-08-08"
    elif change == "return":
        effect["sleeve_return_pct"] = 10
    elif change == "turnover":
        effect["turnover"] = 20
    elif change == "commission":
        effect["cost_drag_pct"] = 2
    elif change == "series":
        effect = {
            **effect,
            "series": [effect["series"][0], {**effect["series"][1], "spy_close": 90}],
        }
    elif change == "model":
        document["analysis"]["model"] = "different-model"
    elif change == "failed":
        document["status"] = "failed"
    snapshot = _snapshot_with_evaluation(
        document,
        effect,
        today=date(2026, 8, 10) if change == "future" else ISSUE_DATE,
    )
    assert "仍落后同区间 SPY" not in snapshot.payload.lede
    assert any("paper evaluation:" in text for text in snapshot.warnings)
    assert (
        next(s for s in snapshot.source_watermark.sources if s.name == "paper_evaluation").status
        == "unavailable"
    )


def test_unavailable_paper_evaluation_does_not_block_archive():
    snapshot = build_auto_archive_snapshot(
        locale="zh",
        today=ISSUE_DATE,
        client=_client(_routes({"/api/paper-evaluation": (503, {"detail": "unavailable"})})),
    )
    assert snapshot.payload.account.equity == _account_payload()["equity"]
    assert "Grok 模拟运行解读" not in snapshot.payload.lede
    assert any("paper evaluation:" in text for text in snapshot.warnings)


def test_english_archive_labels_chinese_model_output_honestly():
    document, effect = _matching_paper_evaluation()
    snapshot = _snapshot_with_evaluation(document, effect, locale="en")
    assert "Grok paper review (Chinese; valuation through 2026-08-11)" in snapshot.payload.lede
