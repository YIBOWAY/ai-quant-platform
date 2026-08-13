"""Owner-triggered D-34 research enqueue.

A Mandate is only the budget and universe envelope. Nothing here takes a
Futu snapshot or invents a daily cycle. The persistent worker materializes
market data when it later leases the queued job.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any

from quant_system.hermes.d34_job_authority import EnqueueJobCommand

JOB_INPUT_CONTRACT = "hqa.d34_job_input/v1"
OWNER_REQUEST_TRIGGER = "owner_request"
DEFAULT_JOB_RESERVATION_USD = Decimal("10")
_IN_FLIGHT_STATES = frozenset({"queued", "leased", "running"})


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


def mandate_field(mandate: Any, name: str) -> Any:
    if isinstance(mandate, dict):
        return mandate[name]
    return getattr(mandate, name)


def _job_field(job: Any, name: str) -> Any:
    if isinstance(job, dict):
        return job.get(name)
    return getattr(job, name, None)


def owner_request_job_key(*, cycle_date: date, objective: str, sequence: int = 1) -> str:
    base = f"request:{cycle_date.isoformat()}:{digest_document(objective)[:12]}"
    return base if sequence <= 1 else f"{base}:{sequence}"


def build_owner_request_input(
    *,
    mandate: Any,
    cycle_date: date,
    objective: str,
) -> dict[str, object]:
    return {
        "contract": JOB_INPUT_CONTRACT,
        "cycle_date": cycle_date.isoformat(),
        "hypothesis_number": 1,
        "trigger": OWNER_REQUEST_TRIGGER,
        "mandate_id": str(mandate_field(mandate, "mandate_id")),
        "mandate_policy_digest": str(mandate_field(mandate, "policy_digest")),
        "universe": list(mandate_field(mandate, "universe")),
        "max_iterations": int(mandate_field(mandate, "max_iterations")),
        "experiments_per_iteration": int(
            mandate_field(mandate, "max_experiments_per_iteration")
        ),
        "top_k": 1,
        "paper_execution_allowed": bool(mandate_field(mandate, "paper_execution_allowed")),
        "objective": objective,
    }


def enqueue_owner_research_request(
    *,
    jobs: Any,
    mandate: Any,
    workspace_id: str,
    objective: str,
    cycle_date: date,
) -> str:
    cleaned = objective.strip()
    if len(cleaned) < 8:
        raise ValueError("d34_research_objective_required")
    mandate_id = str(mandate_field(mandate, "mandate_id"))
    base_key = owner_request_job_key(cycle_date=cycle_date, objective=cleaned)
    existing = jobs.list(workspace_id=workspace_id, limit=100, state=None)
    used_keys: set[str] = set()
    for job in existing:
        if str(_job_field(job, "mandate_id")) != mandate_id:
            continue
        key = str(_job_field(job, "job_key") or "")
        if key == base_key or key.startswith(f"{base_key}:"):
            used_keys.add(key)
            if str(_job_field(job, "state")) in _IN_FLIGHT_STATES:
                return key
    sequence = 1
    job_key = base_key
    while job_key in used_keys:
        sequence += 1
        job_key = owner_request_job_key(
            cycle_date=cycle_date, objective=cleaned, sequence=sequence
        )
    input_document = build_owner_request_input(
        mandate=mandate,
        cycle_date=cycle_date,
        objective=cleaned,
    )
    reservation = min(
        DEFAULT_JOB_RESERVATION_USD,
        Decimal(str(mandate_field(mandate, "llm_budget_usd"))),
    )
    jobs.enqueue(
        EnqueueJobCommand(
            mandate_id=str(mandate_field(mandate, "mandate_id")),
            workspace_id=workspace_id,
            job_key=job_key,
            input_digest=digest_document(input_document),
            input_document=input_document,
            budget_reserved_usd=reservation,
            max_attempts=3,
        )
    )
    return job_key


__all__ = [
    "JOB_INPUT_CONTRACT",
    "OWNER_REQUEST_TRIGGER",
    "build_owner_request_input",
    "digest_document",
    "enqueue_owner_research_request",
    "mandate_field",
    "owner_request_job_key",
]
