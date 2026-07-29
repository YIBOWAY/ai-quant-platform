from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from quant_system.api.routes import paper as paper_routes
from quant_system.config.settings import SafetySettings, Settings
from quant_system.ops import zero_effect


def _release_facts() -> dict[str, bool]:
    return {
        "release_authorized": False,
        "public_write_authorized": False,
        "chat_write_ready": False,
        "ready": False,
    }


def _mixed_receipt() -> dict[str, object]:
    settings = zero_effect._settings_safety_observation(
        Settings.model_construct(
            safety=SafetySettings.model_construct(
                kill_switch=True,
                live_trading_enabled=False,
            )
        )
    )
    account = zero_effect._account_observation(zero_effect._deterministic_account())
    release = {"facts": _release_facts()}
    execution = {
        "dependency_surface": {"requested_provider": "sample"},
        "repository_blocked_result": {
            "status_code": 409,
            "detail": {"code": "global_kill_switch_enabled"},
        },
        "account_before": account,
        "account_after": account,
        "effect_counters": {
            "orders": 0,
            "fills": 0,
            "cash_changes": 0,
            "position_changes": 0,
            "broker_calls": 0,
            "trade_context_creations": 0,
            "account_unlocks": 0,
            "external_dispatches": 0,
        },
        "tree_before": {"sha256": "1" * 64},
        "tree_after": {"sha256": "1" * 64},
        "route_invocations": 1,
    }
    return zero_effect._authoritative_receipt(
        request_digest="2" * 64,
        state_namespace={
            "canonical_path": "/private/closure-zero-effect",
            "namespace_sha256": "3" * 64,
        },
        idempotency_identity={
            "operation_id": zero_effect.OPERATION_ID,
            "state_namespace_sha256": "3" * 64,
            "identity_sha256": "4" * 64,
        },
        platform_identity={"commit": "5" * 40},
        hqa_identity={"commit": "6" * 40},
        platform_runtime_digest="7" * 64,
        hqa_runtime_digest="8" * 64,
        execution_authority={"callable": "run_paper"},
        postflight_runtime_identity={"verified": True},
        settings_preflight=settings,
        settings_postflight=settings,
        release_preflight=release,
        release_postflight=release,
        replay_request=zero_effect._paper_run_request(enable_kill_switch=False),
        execution=execution,
    )


def test_authoritative_operation_binds_mixed_values_and_global_block() -> None:
    request = json.loads(
        zero_effect.default_request_bytes(
            {
                "canonical_path": "/private/closure-zero-effect",
                "namespace_sha256": zero_effect.sha256_bytes(
                    b"/private/closure-zero-effect"
                ),
            }
        )
    )
    receipt = _mixed_receipt()

    assert request["paper_run_request"]["enable_kill_switch"] is False
    for phase in ("safety_preflight", "safety_postflight"):
        safety = receipt[phase]
        assert isinstance(safety, dict)
        assert [item["value"] for item in safety["switch_observations"]] == [
            True,
            True,
            False,
        ]
    assert receipt["expected_outcome"]["code"] == "global_kill_switch_enabled"


def test_mixed_operation_hits_global_block_before_any_runtime_write(
    tmp_path: Path,
) -> None:
    request = zero_effect._paper_run_request(enable_kill_switch=False)
    settings = Settings(
        safety=SafetySettings(
            kill_switch=True,
            live_trading_enabled=False,
        )
    )

    with pytest.raises(HTTPException) as caught:
        paper_routes.run_paper(request, tmp_path, settings)

    assert caught.value.status_code == 409
    assert caught.value.detail == {
        "code": "global_kill_switch_enabled",
        "message": (
            "Global kill switch is enabled; API requests cannot disable "
            "the kill switch"
        ),
    }
    assert list(tmp_path.iterdir()) == []


def test_two_mixed_challenges_make_all_three_source_signatures_unique() -> None:
    first = zero_effect._scoped_switch_observations(
        global_process_value=True,
        paper_account_value=False,
        replay_request_value=False,
    )
    second = zero_effect._scoped_switch_observations(
        global_process_value=True,
        paper_account_value=False,
        replay_request_value=True,
    )
    signatures = {
        first[index]["authority_reference"]: (
            first[index]["value"],
            second[index]["value"],
        )
        for index in range(3)
    }

    assert signatures == {
        "Settings.safety.kill_switch": (True, True),
        "PaperAccount.kill_switch": (False, False),
        "PaperRunRequest.enable_kill_switch": (False, True),
    }
    assert len(set(signatures.values())) == 3
