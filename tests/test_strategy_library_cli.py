"""CLI routing/schema receipts use sealed services and never run real research."""

import io
import json
from types import SimpleNamespace

import pytest

from quant_system.research import strategy_library_cli as cli

IDENTIFIER = "strategy-" + "a" * 24
DIGEST = "b" * 64


@pytest.fixture
def settings(monkeypatch, tmp_path):
    value = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    value.model_copy = lambda **_kwargs: value
    monkeypatch.setattr(cli, "load_settings", lambda: value)
    return value


def invoke(argv, text=""):
    output = io.StringIO()
    code = cli.main(argv, stdin=io.StringIO(text), stdout=output)
    return code, json.loads(output.getvalue())


def entry(**updates):
    return {
        "strategy_id": IDENTIFIER,
        "title": "月度组合",
        "definition_digest": DIGEST,
        "status": "draft",
        "created_at": "2026-09-09T00:00:00Z",
        "definition": {
            "kind": "factor_blend",
            "symbols": ["SPY", "QQQ"],
            "rebalance": "monthly",
            "top_n": 1,
            "factors": [],
        },
        "origin": {"type": "study", "run_id": "study-original", "profile_id": "profile-one"},
        "validation": None,
        "execution_ready": False,
        "activation_blockers": ["strategy_definition_schedule_unavailable"],
        **updates,
    }


def test_empty_list_is_observational_and_does_not_create_data(settings):
    code, result = invoke(["list"])
    assert code == 0 and result == {
        "contract": cli.CONTRACT,
        "action": "list",
        "ok": True,
        "items": [],
    }
    assert list(settings.data.data_dir.iterdir()) == []


@pytest.mark.parametrize(
    "argv,method", [(["factor-options"], "factor_options"), (["show", IDENTIFIER], "read_strategy")]
)
def test_readonly_routes_cannot_save_validate_or_enable(settings, monkeypatch, argv, method):
    def forbidden(*_args, **_kwargs):
        pytest.fail("read-only command attempted mutation")

    for name in (
        "import_study",
        "import_backtest",
        "compose_strategy",
        "validate_strategy",
        "enable_strategy",
    ):
        monkeypatch.setattr(cli.service, name, forbidden)
    returned = {
        "factors": [
            {
                "factor_id": "momentum",
                "label": "动量",
                "lookback": 21,
                "direction": "higher_is_better",
                "expression": None,
                "origin": "builtin",
            }
        ]
    }
    monkeypatch.setattr(
        cli.service, method, lambda *_a, **_k: returned if method == "factor_options" else entry()
    )
    code, result = invoke(argv)
    assert code == 0 and result["ok"]
    if method == "factor_options":
        assert result["factors"][0]["factor_id"] == "momentum"
    else:
        assert result["execution_ready"] is False
        assert result["activation_blockers"] == ["strategy_definition_schedule_unavailable"]
    assert list(settings.data.data_dir.iterdir()) == []


def test_receipt_excludes_prices_model_text_credentials_and_noisy_stdout(settings, monkeypatch):
    def saved(*_args):
        print("DO_NOT_EMIT_TOKEN")
        return entry(
            raw_prices=["DO_NOT_EMIT_PRICES"],
            api_key="DO_NOT_EMIT_KEY",
            validation={
                "definition_digest": DIGEST,
                "platform_metrics": {"total_return": 0, "sharpe": float("nan")},
                "qlib": {"chain_of_thought": "DO_NOT_EMIT_COT"},
                "gates": {"dsr": {"passed": False, "prompt": "DO_NOT_EMIT_PROMPT"}},
                "blockers": ["dsr_failed"],
            },
        )

    monkeypatch.setattr(cli.service, "read_strategy", saved)
    code, result = invoke(["show", IDENTIFIER])
    assert code == 0
    assert "DO_NOT_EMIT" not in json.dumps(result)
    assert result["validation"]["platform_metrics"]["total_return"] == 0
    assert result["validation"]["platform_metrics"]["sharpe"] is None
    assert result["validation"]["blockers"] == ["dsr_failed"]
    assert result["links"]["origin"].endswith("/study-original/profiles/profile-one")


@pytest.mark.parametrize(
    "argv,method,expected",
    [
        (
            ["import-study", "study-original", "profile-one", "--title", "原月度规则"],
            "import_study",
            ("study-original", "profile-one"),
        ),
        (["import-backtest", "backtest-original"], "import_backtest", ("backtest-original",)),
    ],
)
def test_imports_delegate_one_original_identity_and_stop_at_saved(
    settings, monkeypatch, argv, method, expected
):
    calls = []
    monkeypatch.setattr(
        cli.service, method, lambda *args, **kwargs: calls.append((args, kwargs)) or entry()
    )
    monkeypatch.setattr(
        cli.service, "validate_strategy", lambda *_a: pytest.fail("implicit validation")
    )
    code, result = invoke(argv)
    assert code == 0 and result["status"] == "draft"
    assert len(calls) == 1 and calls[0][0] == (settings, *expected)
    assert calls[0][1]["title"] == ("原月度规则" if method == "import_study" else None)


def compose_payload():
    return {
        "title": "明确月度组合",
        "symbols": ["SPY", "QQQ"],
        "top_n": 1,
        "rebalance": "monthly",
        "factors": [
            {"factor_id": "momentum", "lookback": 21, "direction": "higher_is_better", "weight": 1}
        ],
    }


def test_compose_uses_the_strict_api_schema_and_preserves_rule_fields(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli.service, "compose_strategy", lambda *args: calls.append(args) or entry()
    )
    code, result = invoke(["compose"], json.dumps(compose_payload()))
    assert code == 0 and result["status"] == "draft"
    assert len(calls) == 1 and calls[0][0] is settings
    assert calls[0][1]["rebalance"] == "monthly"
    assert calls[0][1]["factors"][0]["lookback"] == 21
    assert calls[0][1]["factors"][0]["source_digest"]
    assert calls[0][1]["kind"] == "factor_blend"


@pytest.mark.parametrize(
    "text,error",
    [
        ('{"title":"a","title":"b"}', "strategy_compose_duplicate_json_key"),
        ('{"weight":NaN}', "strategy_compose_nonfinite_json"),
        ('{"title":', "strategy_compose_json_invalid"),
        (
            json.dumps({**compose_payload(), "unexpected": "DO_NOT_EMIT_SECRET"}),
            "strategy_request_schema_invalid",
        ),
        (" " * 65_537, "strategy_compose_input_too_large"),
    ],
)
def test_bad_json_never_reaches_domain_and_does_not_echo_input(settings, monkeypatch, text, error):
    monkeypatch.setattr(
        cli.service, "compose_strategy", lambda *_a: pytest.fail("invalid compose executed")
    )
    code, result = invoke(["compose"], text)
    assert code == 2 and result["error"] == error
    assert "DO_NOT_EMIT_SECRET" not in json.dumps(result)
    assert list(settings.data.data_dir.iterdir()) == []


def test_validate_keeps_exact_digest_and_reports_a_failed_gate(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        cli.service,
        "validate_strategy",
        lambda *args: (
            calls.append(args)
            or entry(
                status="validation_failed",
                validation={"definition_digest": DIGEST, "blockers": ["dsr_failed"]},
            )
        ),
    )
    code, result = invoke(["validate", IDENTIFIER, "--expected-digest", DIGEST])
    assert code == 1 and result["ok"] is False
    assert result["status"] == "validation_failed"
    assert calls == [(settings, IDENTIFIER, DIGEST)]


def test_enable_reports_schedule_refusal_without_bypass_or_retry(settings, monkeypatch):
    calls = []

    def unavailable(*args):
        calls.append(args)
        raise ValueError("strategy_definition_schedule_unavailable")

    monkeypatch.setattr(cli.service, "enable_strategy", unavailable)
    code, result = invoke(["enable", IDENTIFIER, "--expected-digest", DIGEST])
    assert code == 2 and not result["ok"]
    assert result["error"] == "strategy_definition_schedule_unavailable"
    assert calls == [(settings, IDENTIFIER, DIGEST)]


def test_enable_cannot_report_success_without_an_actual_running_sleeve(settings, monkeypatch):
    monkeypatch.setattr(cli.service, "enable_strategy", lambda *_a: entry(status="validated"))
    code, result = invoke(["enable", IDENTIFIER, "--expected-digest", DIGEST])
    assert code == 1 and not result["ok"]
    assert result["error"] == "strategy_enable_not_confirmed"


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["paper-cycle"],
        ["enable", IDENTIFIER],
        ["validate", IDENTIFIER, "--expected-digest", "secret-value"],
    ],
)
def test_argv_requires_known_command_and_exact_digest(settings, monkeypatch, argv):
    monkeypatch.setattr(cli.service, "enable_strategy", lambda *_a: pytest.fail("invalid enable"))
    monkeypatch.setattr(
        cli.service, "validate_strategy", lambda *_a: pytest.fail("invalid validate")
    )
    code, result = invoke(argv)
    assert code == 2 and not result["ok"]
    assert "secret-value" not in json.dumps(result)
