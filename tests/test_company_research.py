from copy import deepcopy

import pytest

from quant_system.config.settings import Settings
from quant_system.data.providers.longbridge import LongbridgeProviderError
from quant_system.research import company_research as service


@pytest.fixture
def settings(tmp_path):
    value = Settings()
    value.data.data_dir = tmp_path
    return value


class Client:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def request(self, operation, symbol, **params):
        self.calls.append((operation, symbol, params))
        value = self.responses.get((operation, params.get("kind")), [])
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)


def test_first_read_and_missing_capability_report_are_provider_free(settings):
    assert service.read_company(settings, "NVDA")["status"] == "not_loaded"
    assert list(settings.data.data_dir.iterdir()) == []


def test_collect_keeps_successful_sections_and_reports_empty_statements(settings):
    client = Client({("company", None): {"name": "NVIDIA", "profile": "Reported business"}})
    report = service.collect_company(
        settings,
        "NVDA",
        client=client,
        quote_reader=lambda _s, _sym: {"last": 10, "as_of": None},
    )
    sections = {s["key"]: s for s in report["sections"]}
    assert report["status"] == "partial"
    assert sections["company"]["status"] == "available"
    assert sections["income"]["status"] == "empty"
    assert report["pit_backtest_ready"] is False
    assert report["research_only"] is True
    assert all(params.get("kind") != "ALL" for _, _, params in client.calls)
    assert not any(op == "quote" for op, _, _ in client.calls)


def test_quote_uses_backup_only_after_primary_failure(settings):
    client = Client({("quote", None): [{"symbol": "NVDA.US", "last": "12.3"}]})

    def fail(*_):
        raise RuntimeError("contains-private-token-never-copy")

    section = service.collect_quote(settings, "NVDA.US", client=client, quote_reader=fail)
    assert section["provider"] == "longbridge"
    assert section["data"]["last"] == 12.3
    assert section["data"]["fallbacks"][0]["provider"] == "futu"
    assert "private-token" not in str(section)


def test_snapshots_are_immutable_and_reads_do_not_refresh(settings):
    client = Client({("company", None): {"name": "NVIDIA"}})
    report = service.collect_company(
        settings,
        "NVDA",
        client=client,
        quote_reader=lambda *_: {"last": 10},
    )
    saved = service.save_snapshot(settings, report)
    files = {p: p.read_bytes() for p in settings.data.data_dir.rglob("*.json")}
    assert service.read_company(settings, "NVDA.US")["snapshot_id"] == saved["snapshot_id"]
    assert files == {p: p.read_bytes() for p in files}
    snapshot = next(p for p in files if p.name == saved["snapshot_id"] + ".json")
    snapshot.write_text("{}")
    assert service.read_company(settings, "NVDA.US")["status"] == "failed"


def test_symbol_path_injection_rejected_without_writes(settings):
    with pytest.raises(LongbridgeProviderError):
        service.read_company(settings, "../../secrets")
    assert not list(settings.data.data_dir.iterdir())


def test_refresh_lease_is_exclusive_and_interruption_is_visible(settings):
    lease = service.begin_refresh(settings, "NVDA")
    with pytest.raises(service.ResearchBusy):
        service.begin_refresh(settings, "NVDA.US")
    assert service.read_company(settings, "NVDA")["status"] == "updating"
    lease.close()
    assert service.read_company(settings, "NVDA")["status"] == "failed"


def test_raw_response_hash_and_forecast_dates_are_not_execution_authority(settings):
    client = Client(
        {
            ("company", None): {"name": "NVIDIA"},
            ("segments", None): {
                "business": [{"name": "Compute", "value": "5"}],
                "fp_end": "2026.07.31",
                "rpt_date": "2026.05.20",
            },
        }
    )
    report = service.collect_company(
        settings, "NVDA", client=client, quote_reader=lambda *_: {"last": 10}
    )
    assert any("早于" in warning for warning in report["warnings"])
    assert all(len(s["raw_sha256"]) == 64 for s in report["sections"] if s["status"] == "available")


def test_failed_refresh_preserves_last_usable_snapshot(settings):
    first = service.refresh_company(
        settings,
        "NVDA",
        client=Client(
            {
                ("company", None): {"name": "Previously saved company"},
            }
        ),
        quote_reader=lambda *_: {"last": 10},
    )

    def fail(*_, **__):
        raise LongbridgeProviderError("timeout")

    offline = Client()
    offline.request = fail
    second = service.refresh_company(settings, "NVDA", client=offline, quote_reader=fail)
    assert second["status"] == "failed"
    assert second["snapshot_id"] == first["snapshot_id"]
    assert second["headline"] == first["headline"]
    assert second["error"]
    assert len(list(settings.data.data_dir.rglob("attempts/*.json"))) == 1
