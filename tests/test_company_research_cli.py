from __future__ import annotations

import io
import json
from copy import deepcopy

import pytest

from quant_system.config.settings import Settings
from quant_system.research import company_research as service
from quant_system.research import company_research_cli as cli


@pytest.fixture
def document():
    sections = []
    for key in cli.SECTION_KEYS:
        raw = {"raw_rows": [{"long_raw_field": "raw-detail-only" * 1000}]}
        if key == "quote":
            raw = {"last": 11, "currency": "USD", "as_of": "2024-01-05", "fallbacks": []}
        elif key == "company":
            raw = {
                "name": "NVIDIA",
                "profile": "公司业务介绍" * 1000,
                "website": "https://example.com",
                "employees": 10000,
            }
        sections.append(
            {
                "key": key,
                "label": key,
                "status": "available",
                "provider": "longbridge",
                "operation": key,
                "fetched_at": "2024-01-05T22:00:00+00:00",
                "source_url": "https://example.com/source/" + key,
                "raw_sha256": service._digest(raw),
                "reason": None,
                "data": raw,
            }
        )
    return {
        "schema_version": 1,
        "symbol": "NVDA.US",
        "snapshot_id": "a" * 64,
        "updated_at": "2024-01-05T22:00:00+00:00",
        "status": "partial",
        "stale": True,
        "source_policy": "Futu first; Longbridge backup",
        "headline": "NVIDIA 公司研究",
        "summary": ["已保存真实财报"],
        "sections": sections,
        "financials": {
            "status": "partial",
            "currency": "USD",
            "periods": [{"period": str(i), "reported_at": "2024-01-05"} for i in range(7)],
            "metrics": [{"key": str(i), "value": i, "formula": "a / b"} for i in range(10)],
            "checks": [{"key": str(i), "status": "passed"} for i in range(30)],
            "warnings": ["原始财报是当前版本"],
            "research_ideas": [{"title": "Duplicated nested idea"}],
        },
        "research_ideas": [{"title": "观察毛利率", "status": "observation_only"}],
        "warnings": ["尚未取得历史版本"],
        "error": None,
        "research_only": True,
        "pit_backtest_ready": False,
    }


@pytest.fixture
def invoke(monkeypatch, document):
    calls = []
    monkeypatch.setattr(cli, "load_settings", lambda: object())

    def read(_settings, symbol):
        calls.append(("read", symbol))
        return {**deepcopy(document), "symbol": symbol}

    monkeypatch.setattr(service, "read_company", read)

    def run(args):
        stream = io.StringIO()
        code = cli.main(args, stdout=stream)
        return code, json.loads(stream.getvalue())

    return run, calls


def test_show_defaults_to_compact_without_changing_snapshot_evidence(invoke, document):
    run, calls = invoke
    before = deepcopy(document)
    code, payload = run(["show", "NVDA"])
    assert code == 0
    assert payload["contract"] == "hqa.company_research/v1"
    assert payload["projection"] == "compact"
    for key in cli._REPORT_FIELDS:
        assert payload[key] == document[key]
    assert calls == [("read", "NVDA.US")]
    assert document == before
    assert "raw-detail-only" not in json.dumps(payload)
    assert len(json.dumps(payload)) < len(json.dumps(document)) // 4

    by_key = {section["key"]: section for section in payload["sections"]}
    for original in document["sections"]:
        projected = by_key[original["key"]]
        for name, value in original.items():
            if name != "data":
                assert projected[name] == value
        assert projected["detail"] == {
            "action": "section",
            "symbol": "NVDA.US",
            "key": original["key"],
        }
    assert by_key["quote"]["data"] == document["sections"][0]["data"]
    assert by_key["quote"]["projection"] == "full"
    company = by_key["company"]["data"]
    assert company["name"] == "NVIDIA"
    assert company["website"] == "https://example.com"
    assert len(company["profile"]) == cli.PROFILE_MAX_CHARS
    assert company["profile_truncated"] is True
    assert company["profile_original_chars"] == 6000
    assert "employees" not in company
    assert "data" not in by_key["income"]

    financials = payload["financials"]
    assert financials["periods"] == document["financials"]["periods"][:5]
    assert financials["metrics"] == document["financials"]["metrics"][:8]
    assert financials["periods_total"] == 7
    assert financials["metrics_total"] == 10
    assert financials["periods_truncated"] is True
    assert financials["checks"] == document["financials"]["checks"]


def test_refresh_projects_one_existing_refresh_result_without_extra_calls(
    invoke,
    monkeypatch,
    document,
):
    run, reads = invoke
    refreshes = []

    def refresh(_settings, symbol):
        refreshes.append(symbol)
        return deepcopy(document)

    monkeypatch.setattr(service, "refresh_company", refresh)
    code, payload = run(["refresh", "NVDA"])
    assert code == 0
    assert payload["projection"] == "compact"
    assert payload["snapshot_id"] == document["snapshot_id"]
    assert refreshes == ["NVDA.US"]
    assert reads == []


@pytest.mark.parametrize("key", cli.SECTION_KEYS)
def test_section_reads_only_the_selected_saved_raw_section(invoke, document, key):
    run, calls = invoke
    code, payload = run(["section", "NVDA", key])
    assert code == 0
    assert payload["projection"] == "section"
    assert payload["snapshot_id"] == document["snapshot_id"]
    assert payload["updated_at"] == document["updated_at"]
    assert payload["section"] == next(s for s in document["sections"] if s["key"] == key)
    assert payload["raw_size_bytes"] <= payload["size_limit_bytes"]
    assert "sections" not in payload
    assert calls == [("read", "NVDA.US")]


def test_oversized_section_fails_explicitly_without_silently_truncating_raw(invoke, document):
    run, _ = invoke
    section = next(item for item in document["sections"] if item["key"] == "income")
    section["data"] = {"large": "x" * cli.SECTION_DATA_MAX_BYTES}
    section["raw_sha256"] = service._digest(section["data"])
    code, payload = run(["section", "NVDA", "income"])
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"] == "size_limit"
    assert payload["raw_size_bytes"] > payload["size_limit_bytes"]
    assert payload["snapshot_id"] == document["snapshot_id"]
    assert payload["section"]["raw_sha256"] == section["raw_sha256"]
    assert payload["section"]["status"] == "available"
    assert "data" not in payload["section"]


def test_compare_is_compact_and_allows_four_saved_companies(invoke):
    run, calls = invoke
    code, payload = run(["compare", "NVDA", "AAPL", "MSFT", "AMZN"])
    assert code == 0
    assert payload["projection"] == "compact"
    assert len(payload["items"]) == 4
    assert all(item["projection"] == "compact" for item in payload["items"])
    assert all("raw-detail-only" not in json.dumps(item) for item in payload["items"])
    assert calls == [("read", symbol + ".US") for symbol in ("NVDA", "AAPL", "MSFT", "AMZN")]


@pytest.mark.parametrize(
    "args",
    [
        ["compare", "NVDA", "AAPL", "MSFT", "AMZN", "META"],
        ["compare"],
        ["section", "NVDA", "../../secrets"],
        ["section", "NVDA", "orders"],
        ["section", "../../secrets", "income"],
        ["section", "NVDA", "income", "--url", "bad"],
        ["show", "NVDA", "--raw"],
        ["order", "NVDA"],
    ],
)
def test_invalid_args_are_rejected_before_settings_or_snapshot_access(invoke, monkeypatch, args):
    run, calls = invoke

    def forbidden():
        pytest.fail("invalid input must not load settings")

    monkeypatch.setattr(cli, "load_settings", forbidden)
    code, payload = run(args)
    assert code == 2
    assert payload["status"] == "failed"
    assert calls == []


def test_show_compare_and_section_are_provider_free_and_leave_saved_files_unchanged(
    monkeypatch,
    tmp_path,
    document,
):
    settings = Settings()
    settings.data.data_dir = tmp_path
    saved = service.save_snapshot(settings, document)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    def forbidden(*_args, **_kwargs):
        pytest.fail("a saved-evidence CLI read must not call providers or refresh")

    monkeypatch.setattr(service, "refresh_company", forbidden)
    monkeypatch.setattr(service.LongbridgeClient, "request", forbidden)
    monkeypatch.setattr(service.FutuMarketDataProvider, "fetch_underlying_snapshot", forbidden)
    for args in (["show", "NVDA"], ["compare", "NVDA"], ["section", "NVDA", "income"]):
        stream = io.StringIO()
        assert cli.main(args, stdout=stream) == 0
        payload = json.loads(stream.getvalue())
        report = payload["items"][0] if args[0] == "compare" else payload
        assert report["snapshot_id"] == saved["snapshot_id"]
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}


def test_missing_snapshot_section_does_not_claim_raw_evidence(invoke, document):
    run, _ = invoke
    document.update(status="not_loaded", sections=[], snapshot_id=None)
    code, payload = run(["section", "NVDA", "income"])
    assert code == 0
    assert payload["status"] == "not_loaded"
    assert payload["snapshot_id"] is None
    assert payload["section"] is None
