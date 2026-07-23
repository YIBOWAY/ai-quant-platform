from quant_system.hermes.compatibility_contract import (
    compatibility_manifest_path,
    load_hermes_compatibility_contract,
)


def test_agent_v02_compatibility_manifest_is_closed_and_runtime_loadable() -> None:
    contract = load_hermes_compatibility_contract()

    assert compatibility_manifest_path().is_file()
    assert contract.schema_version == 1
    assert contract.profile == "local_agent_v0_2"
    assert "managed_run_sessions" in contract.required_bool_features
    assert contract.required_exact_features == {
        "managed_run_history_authority": "hermes_session_db",
        "managed_session_fork_mode": "preserve_source_exact_message_cursor",
    }
    assert "run_evidence" in contract.required_durable
    assert contract.durable_evidence_template.format(
        capability="run_evidence"
    ) == "store.transactional_probe:run_evidence"
    assert contract.hqa_cli_operations == (
        "capabilities",
        "submit",
        "status",
        "events",
        "session-ensure",
        "session-fork",
    )
    assert ("POST", "/v1/runs") in contract.http_endpoints
    assert ("POST", "/api/sessions/{session_id}/fork") in contract.http_endpoints
