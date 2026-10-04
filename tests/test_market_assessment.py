import html
import json
from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quant_system.api.dependencies import require_mutation_security
from quant_system.api.routes import market_assessment as route
from quant_system.api.server import create_app
from quant_system.config.settings import Settings
from quant_system.data.market_valuation import (
    fetch_treasury_spread,
    fetch_us_valuations,
    parse_ishares_valuation,
    parse_multpl_history,
)
from quant_system.factors.asia_radar import ASIA_ETF_SYMBOLS
from quant_system.factors.market_assessment import (
    ANALYSIS_VERSION,
    add_ai_analysis,
    build_assessment,
)

AS_OF = date(2026, 9, 4)


def _prices(last=105.0):
    return pd.Series([100.0] * 259 + [last], index=pd.bdate_range(end=AS_OF, periods=260))


def _macro():
    return {
        key: {
            "value": value,
            "score": 90.0,
            "samples": 120,
            "error": None,
            "source_url": "https://www.multpl.com/" + key,
            "source_date": AS_OF.isoformat(),
        }
        for key, value in (("cape", 41.41), ("pe", 30.0), ("pb", 5.0), ("buffett", 250.03))
    }


def _complete_us():
    return build_assessment(
        "us",
        prices={"SPY": _prices(), "QQQ": _prices()},
        expected=AS_OF,
        macro=_macro(),
        spread={"value": 0.4, "score": 25, "source_date": AS_OF.isoformat()},
        vix=pd.Series([15.0, 16.0], index=pd.to_datetime(["2026-09-03", "2026-09-04"])),
        vix3m=pd.Series([18.0], index=pd.to_datetime(["2026-09-04"])),
    )


def test_public_valuation_table_uses_prior_months_and_excludes_future():
    rows = [
        (day.strftime("%b %d, %Y"), 10 + index / 10)
        for index, day in enumerate(pd.date_range("2020-09-01", periods=72, freq="MS"))
    ]
    rows += [("Sep 4, 2026", "† 30"), ("Sep 1, 2026", 25), ("Sep 5, 2026", 999)]
    text = (
        '<table id="datatable">'
        + "".join(
            f"<tr><td>{day}</td><td>&#x2002;{value}</td></tr>" for day, value in reversed(rows)
        )
        + "</table>"
    )
    parsed = parse_multpl_history(text, as_of=AS_OF)
    assert parsed[-1] == (AS_OF, 30.0, True)
    result = fetch_us_valuations(as_of=AS_OF, download=lambda _: text)
    assert result["cape"]["samples"] == 72
    assert result["cape"]["score"] == 100
    assert result["cape"]["value"] == 30
    assert result["cape"]["estimated"] is True
    assert result["cape"]["history_reference"] == {
        "samples": 72,
        "frequency": "month",
        "start_date": "2020-09-01",
        "end_date": "2026-08-01",
        "minimum": 10.0,
        "median": 13.55,
        "maximum": 17.1,
    }  # Neither the current month's 25 nor the current/future daily values enter this range.
    assessment = build_assessment(
        "us", prices={"SPY": _prices(), "QQQ": _prices()}, expected=AS_OF,
        macro=result, spread={}, vix=None, vix3m=None,
    )
    assert assessment["factors"][0]["history_reference"] == result["cape"]["history_reference"]


def test_pb_annual_history_is_not_presented_as_monthly_or_backfilled():
    rows = [(f"Dec 31, {year}", 2.0 + (year - 2016) / 10) for year in range(2016, 2026)]
    rows.append(("Sep 4, 2026", "† 6.13"))
    table = (
        '<table id="datatable">'
        + "".join(f"<tr><td>{day}</td><td>{value}</td></tr>" for day, value in rows)
        + "</table>"
    )
    result = fetch_us_valuations(as_of=AS_OF, download=lambda _: table)
    assert result["pb"]["frequency"] == "year"
    assert result["pb"]["samples"] == 10
    assert result["pb"]["estimated"] is True
    assert result["pb"]["value"] == 6.13
    assert result["pb"]["history_reference"] == {
        "samples": 10,
        "frequency": "year",
        "start_date": "2016-12-31",
        "end_date": "2025-12-31",
        "minimum": 2.0,
        "median": 2.45,
        "maximum": 2.9,
    }


def _issuer_html(ticker="EWY", observed=20260903, pe=21.1037):
    props = {
        "data": [
            {"name": "priceEarnings", "value": pe, "asOfDate": observed},
            {"name": "priceBook", "value": 2.277, "asOfDate": observed},
        ]
    }
    return (
        '<walrus-render-on-client componentprops="' + html.escape(json.dumps(props)) + '">'
        "</walrus-render-on-client><walrus-render-on-client "
        'componentkey="ProductIdSetterForPPContainerV3" componentprops="'
        + html.escape(json.dumps({"ticker": ticker}))
        + '"></walrus-render-on-client>'
    )


def test_issuer_numbers_are_bound_to_ticker_and_date_not_etf_price():
    values = parse_ishares_valuation(_issuer_html(), ticker="EWY", as_of=AS_OF)
    assert values["pe"] == {"value": 21.1037, "source_date": "2026-09-03"}
    assert values["pb"]["value"] == 2.277
    with pytest.raises(ValueError, match="issuer_ticker_mismatch"):
        parse_ishares_valuation(_issuer_html(), ticker="EWT", as_of=AS_OF)
    with pytest.raises(ValueError, match="stale_or_missing"):
        parse_ishares_valuation(_issuer_html(observed=20260701), ticker="EWY", as_of=AS_OF)
    with pytest.raises(ValueError, match="stale_or_missing"):
        parse_ishares_valuation(_issuer_html(observed=20260905), ticker="EWY", as_of=AS_OF)


def test_yield_curve_cannot_claim_uninversion_without_past_negative_observation():
    csv = "observation_date,T10Y2Y\n2026-09-03,0.3\n2026-09-04,0.4\n"
    result = fetch_treasury_spread(as_of=AS_OF, download=lambda _: csv)
    assert result["recently_inverted"] is False and result["score"] == 25
    assert result["history_reference"]["maximum"] == 0.3
    assert result["history_reference"]["end_date"] == "2026-09-03"
    result = fetch_treasury_spread(as_of=AS_OF, download=lambda _: csv.replace("0.3", "-0.3"))
    assert result["recently_inverted"] is True and result["score"] == 65
    assert result["history_reference"]["minimum"] == -0.3


def test_empty_and_missing_dimensions_never_imply_safety_or_zero_valuation():
    empty = build_assessment("us", prices={}, expected=AS_OF)
    assert empty["score"] is None
    assert empty["status"] == "unavailable"
    prices_only = build_assessment(
        "us", prices={"SPY": _prices(), "QQQ": _prices()}, expected=AS_OF
    )
    assert prices_only["score"] is None
    assert prices_only["scores"]["valuation"] is None
    assert prices_only["scores"]["pressure"] is None
    assert prices_only["scores"]["bubble"] is None
    assert prices_only["coverage"]["weight_pct"] == 20
    assert prices_only["rule_assessment"]["stance"] == "数据不足"


def test_complete_us_separates_expensive_valuation_from_current_pressure():
    result = _complete_us()
    assert result["coverage"] == {"available": 9, "total": 9, "weight_pct": 100.0}
    assert sum(factor["weight"] for factor in result["factors"]) == 100
    assert result["scores"]["valuation"] == 90
    assert result["scores"]["pressure"] < 40
    assert result["rule_assessment"]["stance"] == "暂缓追涨，保留现有风险控制"
    assert result["input_digest"] == _complete_us()["input_digest"]
    assert all(0 <= factor["score"] <= 100 for factor in result["factors"])


def test_asia_missing_issuer_cannot_become_known_bubble_even_with_full_prices():
    result = build_assessment(
        "asia",
        prices={ticker: _prices() for ticker in ASIA_ETF_SYMBOLS},
        expected=AS_OF,
        valuations={},
    )
    assert result["scores"]["valuation"] is None
    assert result["scores"]["bubble"] is None
    assert all(row["pe"] is None and row["score"] is None for row in result["market_rows"])
    assert result["coverage"]["weight_pct"] == 65
    assert result["rule_assessment"]["stance"] == "补齐估值"


def test_ai_invalid_evidence_is_rejected_and_no_data_makes_zero_calls():
    class Llm:
        model = "fixture"
        reasoning_effort = "xhigh"
        calls = 0

        def _chat_json(self, messages):
            self.calls += 1
            return {
                "summary": "测试判断",
                "actions": ["条件一", "条件二"],
                "scenarios": ["情形一", "情形二"],
                "evidence_refs": ["invented", "us.pe"],
            }

    client = Llm()
    result = add_ai_analysis(build_assessment("us", prices={}, expected=AS_OF), client=client)
    assert client.calls == 0 and result["ai_analysis"] is None
    result = add_ai_analysis(_complete_us(), client=client)
    assert client.calls == 1 and result["ai_analysis"] is None and result["ai_error"]


@pytest.mark.parametrize(
    ("reference_case", "expected_error"),
    [("valid", None), ("fourteen", "段落或引用数量"), ("unavailable", "不存在或不可用的指标")],
)
def test_asia_ai_prompt_exposes_only_usable_refs_and_explains_rejections(
    reference_case,
    expected_error,
):
    document = build_assessment(
        "asia",
        prices={ticker: _prices() for ticker in ASIA_ETF_SYMBOLS},
        expected=AS_OF,
        valuations={
            "EWT": {
                "pe": {"value": 33.84, "source_date": AS_OF.isoformat()},
                "pb": {"value": 4.65, "source_date": AS_OF.isoformat()},
            }
        },
    )
    available = [row["key"] for row in document["factors"] if row["status"] == "available"]
    refs = (
        available[:14]
        if reference_case == "fourteen"
        else [
            "EWT.pe",
            "ASHR.pe" if reference_case == "unavailable" else "EWT.pb",
        ]
    )

    class Capture:
        model = "fixture"
        reasoning_effort = "xhigh"
        messages = None

        def _chat_json(self, messages):
            self.messages = messages
            return {
                "summary": "台湾估值偏高，等待价格与估值变化再判断。",
                "actions": ["观察估值变化。", "观察价格回落。"],
                "scenarios": ["估值降低时重新判断。", "价格走弱时重新判断。"],
                "evidence_refs": refs,
            }

    client = Capture()
    result = add_ai_analysis(document, client=client)
    facts = json.loads(client.messages[1]["content"])
    assert "EWT.pe" in facts["allowed_evidence_refs"]
    assert "ASHR.pe" not in facts["allowed_evidence_refs"]
    assert facts["as_of"] == AS_OF.isoformat()
    if expected_error is None:
        assert result["ai_analysis"]["input_digest"] == document["input_digest"]
        assert result["ai_error"] is None
    else:
        assert result["ai_analysis"] is None
        assert expected_error in result["ai_error"]


def test_http_get_is_read_only_and_refresh_reuses_ai_for_unchanged_facts(tmp_path, monkeypatch):
    settings = Settings()
    settings.data.data_dir = tmp_path
    calls = {"data": 0, "ai": 0}

    def collect(*_):
        calls["data"] += 1
        return _complete_us()

    def analyze(document):
        calls["ai"] += 1
        document["ai_analysis"] = {
            "model": route.RollupLlmClient().model,
            "reasoning_effort": route.RollupLlmClient().reasoning_effort,
            "analysis_version": ANALYSIS_VERSION,
            "input_digest": document["input_digest"],
            "generated_at": document["updated_at"],
            "summary": "根据估值和压力分别判断。",
            "actions": ["动作一", "动作二"],
            "scenarios": ["情形一", "情形二"],
            "evidence_refs": ["us.pe", "us.cape"],
        }

    monkeypatch.setattr(route, "collect_assessment", collect)
    monkeypatch.setattr(route, "add_ai_analysis", analyze)
    app = create_app(settings=settings, output_dir=tmp_path)
    app.dependency_overrides[require_mutation_security] = lambda: None
    client = TestClient(app)
    assert client.get("/api/market-assessment?scope=us").json()["score"] is None
    assert calls == {"data": 0, "ai": 0}
    assert client.post("/api/market-assessment/refresh", json={"scope": "us"}).status_code == 202
    first = client.get("/api/market-assessment?scope=us").json()
    assert (
        first["status"] == "ready"
        and first["ai_analysis"]["model"] == route.RollupLlmClient().model
    )
    assert client.post("/api/market-assessment/refresh", json={"scope": "us"}).status_code == 202
    assert (
        client.get("/api/market-assessment?scope=us").json()["input_digest"]
        == first["input_digest"]
    )
    assert calls == {"data": 2, "ai": 1}
    # Same market input must not preserve a previous model, effort or prompt revision.
    for key, value in (
        ("model", "grok-4.5"),
        ("reasoning_effort", "high"),
        ("analysis_version", "old"),
    ):
        previous = route._read(settings, "us")
        previous["ai_analysis"][key] = value
        route._write(settings, "us", previous)
        prior_calls = calls["ai"]
        assert (
            client.post("/api/market-assessment/refresh", json={"scope": "us"}).status_code == 202
        )
        assert calls["ai"] == prior_calls + 1
    last_valid = route._read(settings, "us")
    last_valid["ai_analysis"]["analysis_version"] = "prior"
    route._write(settings, "us", last_valid)

    def unavailable(document):
        document["ai_error"] = "等待模型回复超时"

    monkeypatch.setattr(route, "add_ai_analysis", unavailable)
    client.post("/api/market-assessment/refresh", json={"scope": "us"})
    retained = client.get("/api/market-assessment?scope=us").json()
    assert retained["status"] == "partial"
    assert retained["ai_error"] == "等待模型回复超时"
    assert retained["ai_analysis"]["generated_at"] == last_valid["ai_analysis"]["generated_at"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("updated_at", "not-a-timestamp"),
        ("updated_at", "2999-01-01T00:00:00Z"),
        ("as_of", "2999-01-01"),
        ("as_of", "not-a-date"),
    ],
)
def test_invalid_cached_dates_return_existing_failed_state_without_generation(
    tmp_path,
    monkeypatch,
    field,
    value,
):
    settings = Settings()
    settings.data.data_dir = tmp_path
    document = _complete_us()
    document[field] = value
    route._write(settings, "us", document)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("GET must not fetch data or call Grok")

    monkeypatch.setattr(route, "collect_assessment", forbidden)
    monkeypatch.setattr(route, "add_ai_analysis", forbidden)
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))
    response = client.get("/api/market-assessment?scope=us")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["score"] is None
