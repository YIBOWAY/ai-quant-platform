from __future__ import annotations

import inspect

from quant_system.d34.research_request import (
    LOCAL_RESEARCH_RESOURCE_ENVELOPE,
    LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
    LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
    OWNER_REQUEST_TRIGGER,
    build_owner_request_input,
)
from quant_system.hermes.d34_job_authority import EnqueueJobCommand


def test_fixed_resource_envelope_is_versioned_and_paper_only() -> None:
    assert LOCAL_RESEARCH_RESOURCE_ENVELOPE == {
        "contract": "hqa.local_research_resource_envelope/v1",
        "experiments_per_iteration": 3,
        "llm_budget_usd": "10.000000",
        "max_concurrent_jobs": 1,
        "max_iterations": 3,
        "max_universe_size": 64,
        "paper_only": True,
        "research_only": True,
        "timeout_seconds": 7200,
    }
    assert LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID == "local-paper-research-v1"
    assert LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST == (
        "f539564775cd6f0c51fbd8478697265c1f4df86987513dad5e7a842b92191270"
    )


def test_owner_request_input_uses_fixed_resource_and_has_no_snapshot_or_mandate() -> None:
    document = build_owner_request_input(
        objective="Compose a volume surprise expression",
        universe=["SPY", "QQQ"],
    )

    assert document["trigger"] == OWNER_REQUEST_TRIGGER
    assert document["resource_envelope_id"] == LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID
    assert document["resource_policy_digest"] == LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST
    assert document["max_iterations"] == 3
    assert document["experiments_per_iteration"] == 3
    assert document["research_only"] is True
    assert document["paper_execution_allowed"] is False
    for forbidden in (
        "mandate_id",
        "mandate_policy_digest",
        "hang_if_pass",
        "snapshot_id",
        "snapshot_parquet",
        "cycle_date",
    ):
        assert forbidden not in document


def test_enqueue_command_has_resource_envelope_not_mandate() -> None:
    parameters = inspect.signature(EnqueueJobCommand).parameters

    assert "resource_envelope_id" in parameters
    assert "mandate_id" not in parameters
