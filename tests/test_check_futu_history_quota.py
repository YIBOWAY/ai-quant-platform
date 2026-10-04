"""Guard tests for the read-only Futu history-kline quota probe script.

The live probe contacts a local OpenD over the Futu SDK, so these tests
monkeypatch the SDK layer (``_load_sdk``) with a fake quote context. They never
import ``futu`` and never open a socket.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_futu_history_quota.py"
SCRIPTS_README = REPO_ROOT / "scripts" / "README.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_futu_history_quota", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    # Register before exec so module-level names resolve from sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeQuoteContext:
    def __init__(self, response):
        self._response = response
        self.get_detail_calls: list[bool] = []
        self.closed = False

    def get_history_kl_quota(self, get_detail=False):
        self.get_detail_calls.append(get_detail)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    def close(self):
        self.closed = True


def _install_fake_sdk(monkeypatch, module, response, calls):
    def _factory(**kwargs):
        ctx = _FakeQuoteContext(response)
        calls.append({"context_kwargs": kwargs, "ctx": ctx})
        return ctx

    monkeypatch.setattr(
        module, "_load_sdk", lambda: SimpleNamespace(RET_OK=0, OpenQuoteContext=_factory)
    )


def _install_failing_sdk(monkeypatch, module, exc):
    def _loader():
        raise exc

    monkeypatch.setattr(module, "_load_sdk", _loader)


def _ok_payload(used=12, remain=999, details=None):
    if details is None:
        details = [{"code": "HK.00700", "name": "Tencent", "request_time": "2026-09-16 09:00:00"}]
    return (0, (used, remain, details))


def _single_json_line(captured: str):
    lines = [line for line in captured.strip().splitlines() if line.strip()]
    assert len(lines) == 1, lines
    return json.loads(lines[0])


def test_script_exists_and_is_indexed() -> None:
    assert SCRIPT_PATH.exists()
    assert "check_futu_history_quota.py" in SCRIPTS_README.read_text(encoding="utf-8")


def test_normal_return_maps_quota_fields(monkeypatch, capsys) -> None:
    module = _load_module()
    calls: list[dict] = []
    _install_fake_sdk(monkeypatch, module, _ok_payload(used=12, remain=999), calls)

    assert module.main([]) == 0
    payload = _single_json_line(capsys.readouterr().out)

    assert payload["used_quota"] == 12
    assert payload["remain_quota"] == 999
    assert payload["detail_count"] == 1
    assert payload["as_of"]  # ISO 8601 local timestamp
    assert module.datetime.fromisoformat(payload["as_of"]).tzinfo is not None
    # Read-only detail request, host/port threaded through, context closed.
    assert calls[0]["context_kwargs"] == {"host": "127.0.0.1", "port": 11111}
    assert calls[0]["ctx"].get_detail_calls == [True]
    assert calls[0]["ctx"].closed is True


def test_quota_payload_serializes_verbatim_into_line(monkeypatch, capsys) -> None:
    module = _load_module()
    calls: list[dict] = []
    details = [
        {"code": "US.AAPL", "name": "Apple", "request_time": "2026-09-16 09:01:00"},
        {"code": "US.SPY", "name": "SPY", "request_time": "2026-09-16 09:02:00"},
    ]
    _install_fake_sdk(monkeypatch, module, _ok_payload(used=7, remain=500, details=details), calls)

    assert module.main([]) == 0
    payload = _single_json_line(capsys.readouterr().out)

    assert payload["used_quota"] == 7
    assert payload["remain_quota"] == 500
    assert payload["detail_count"] == 2


def test_non_ret_ok_exits_one_with_structured_error(monkeypatch, capsys) -> None:
    module = _load_module()
    calls: list[dict] = []
    _install_fake_sdk(monkeypatch, module, (1, "no permission for history kline"), calls)

    assert module.main([]) == 1
    payload = _single_json_line(capsys.readouterr().out)

    assert payload["error"] == "quota_query_failed"
    assert "no permission" in payload["message"]
    assert "used_quota" not in payload
    assert calls[0]["ctx"].closed is True


def test_connection_failure_is_structured_and_redacted(monkeypatch, capsys) -> None:
    module = _load_module()
    calls: list[dict] = []
    _install_fake_sdk(
        monkeypatch,
        module,
        ConnectionRefusedError("refused token=super-secret-value host=127.0.0.1"),
        calls,
    )

    assert module.main([]) == 1
    payload = _single_json_line(capsys.readouterr().out)

    assert payload["error"] == "connection_failed"
    assert payload["host"] == "127.0.0.1"
    assert "ConnectionRefusedError" in payload["message"]
    assert "super-secret-value" not in payload["message"]
    assert calls[0]["ctx"].closed is True


def test_sdk_import_failure_exits_one(monkeypatch, capsys) -> None:
    module = _load_module()
    _install_failing_sdk(monkeypatch, module, ImportError("no module named futu"))

    assert module.main([]) == 1
    payload = _single_json_line(capsys.readouterr().out)
    assert payload["error"] == "sdk_unavailable"


def test_record_appends_two_durable_lines(monkeypatch, capsys, tmp_path) -> None:
    module = _load_module()
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    calls: list[dict] = []
    _install_fake_sdk(monkeypatch, module, _ok_payload(), calls)

    assert module.main(["--record"]) == 0
    capsys.readouterr()
    assert module.main(["--record"]) == 0
    capsys.readouterr()

    ledger = tmp_path / "data" / "futu_quota_ledger.jsonl"
    assert ledger.exists()
    lines = ledger.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    for record in records:
        assert record["source"] == "check_futu_history_quota.py"
        assert record["used_quota"] == 12
        assert record["remain_quota"] == 999
        assert record["detail_count"] == 1
        assert record["detail_summary"] == [
            {"code": "HK.00700", "name": "Tencent", "request_time": "2026-09-16 09:00:00"}
        ]
        assert record["detail_truncated"] is False
        assert record["as_of"]


def test_record_creates_missing_dir_and_omits_empty_detail(
    monkeypatch, capsys, tmp_path
) -> None:
    module = _load_module()
    nested = tmp_path / "missing" / "nested"
    monkeypatch.setenv("QS_DATA_DIR", str(nested))
    calls: list[dict] = []
    _install_fake_sdk(monkeypatch, module, _ok_payload(details=[]), calls)

    assert module.main(["--record"]) == 0
    capsys.readouterr()

    ledger = nested / "futu_quota_ledger.jsonl"
    assert ledger.exists()
    record = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert record["detail_count"] == 0
    assert "detail_summary" not in record


def test_record_defaults_to_repo_data_dir(monkeypatch, tmp_path) -> None:
    module = _load_module()
    monkeypatch.delenv("QS_DATA_DIR", raising=False)
    assert module._ledger_path() == Path(
        "/Users/sunyibo/programs/ai-quant-platform/data/futu_quota_ledger.jsonl"
    )


def test_check_floor_breach_warns_and_exits_two(monkeypatch, capsys) -> None:
    module = _load_module()
    calls: list[dict] = []
    _install_fake_sdk(monkeypatch, module, _ok_payload(used=995, remain=5), calls)

    assert module.main(["--check-floor", "10"]) == 2
    captured = capsys.readouterr()
    payload = _single_json_line(captured.out)
    assert payload["remain_quota"] == 5
    assert "WARNING" in captured.err
    assert "remain_quota=5" in captured.err


def test_check_floor_met_exits_zero(monkeypatch, capsys) -> None:
    module = _load_module()
    calls: list[dict] = []
    _install_fake_sdk(monkeypatch, module, _ok_payload(used=5, remain=50), calls)

    assert module.main(["--check-floor", "10"]) == 0
    captured = capsys.readouterr()
    assert _single_json_line(captured.out)["remain_quota"] == 50
    assert "WARNING" not in captured.err


def test_redact_masks_labelled_secrets() -> None:
    module = _load_module()
    redacted = module._redact("token=abc123 apikey: def456 password=hunter2 plain=ok")
    assert "abc123" not in redacted
    assert "def456" not in redacted
    assert "hunter2" not in redacted
    assert "plain=ok" in redacted
