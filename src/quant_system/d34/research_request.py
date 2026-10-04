"""Fixed-resource local paper research enqueue contracts."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

JOB_INPUT_CONTRACT = "hqa.d34_job_input/v2"
OWNER_REQUEST_TRIGGER = "owner_request"
DEFAULT_JOB_RESERVATION_USD = Decimal("10")
LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID = "local-paper-research-v1"
LOCAL_RESEARCH_RESOURCE_ENVELOPE: dict[str, object] = {
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
LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST = (
    "f539564775cd6f0c51fbd8478697265c1f4df86987513dad5e7a842b92191270"
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode()


def digest_document(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def build_owner_request_input(
    *,
    objective: str,
    universe: list[str] | tuple[str, ...],
) -> dict[str, object]:
    return {
        "contract": JOB_INPUT_CONTRACT,
        "hypothesis_number": 1,
        "trigger": OWNER_REQUEST_TRIGGER,
        "resource_envelope_id": LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
        "resource_policy_digest": LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
        "universe": list(universe),
        "max_iterations": int(LOCAL_RESEARCH_RESOURCE_ENVELOPE["max_iterations"]),
        "experiments_per_iteration": int(
            LOCAL_RESEARCH_RESOURCE_ENVELOPE["experiments_per_iteration"]
        ),
        "top_k": 1,
        "research_only": True,
        "paper_execution_allowed": False,
        "objective": objective,
    }


__all__ = [
    "JOB_INPUT_CONTRACT",
    "LOCAL_RESEARCH_RESOURCE_ENVELOPE",
    "LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID",
    "LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST",
    "OWNER_REQUEST_TRIGGER",
    "build_owner_request_input",
    "digest_document",
]
