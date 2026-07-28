from __future__ import annotations

from quant_system.config.settings import SafetySettings, Settings
from quant_system.ops import zero_effect


def _release_facts() -> dict[str, bool]:
    return {
        "release_authorized": False,
        "public_write_authorized": False,
        "chat_write_ready": False,
        "ready": False,
    }


def _authoritative_receipt() -> dict[str, object]:
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
        execution=execution,
    )


def test_receipt_binds_three_switch_scopes_to_authorities() -> None:
    receipt = _authoritative_receipt()
    expected = [
        {
            "switch_scope": "global_process",
            "authority_reference": "Settings.safety.kill_switch",
            "value": True,
        },
        {
            "switch_scope": "paper_account",
            "authority_reference": "PaperAccount.kill_switch",
            "value": True,
        },
        {
            "switch_scope": "replay_request",
            "authority_reference": "PaperRunRequest.enable_kill_switch",
            "value": True,
        },
    ]

    for phase in ("safety_preflight", "safety_postflight"):
        safety = receipt[phase]
        assert isinstance(safety, dict)
        assert safety["switch_observations"] == expected
        assert safety["global_kill_switch"] is True
        assert safety["paper_account_local_kill_switch"] is True
        assert safety["replay_enable_kill_switch"] is True
        assert safety["live_trading_enabled"] is False
        assert safety["release_authorized"] is False
        assert safety["public_write_authorized"] is False
        assert safety["chat_write_ready"] is False
        assert safety["ready"] is False
