from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from quant_system.d34.research_request import (
    OWNER_REQUEST_TRIGGER,
    enqueue_owner_research_request,
    owner_request_job_key,
)


def test_owner_request_is_idempotent_for_the_same_objective() -> None:
    mandate = SimpleNamespace(
        mandate_id="mandate-test-1",
        policy_digest="a" * 64,
        universe=("SPY", "QQQ"),
        max_iterations=3,
        max_experiments_per_iteration=2,
        paper_execution_allowed=True,
        llm_budget_usd=Decimal("100"),
    )
    queued: list[object] = []

    class Jobs:
        def list(self, *, workspace_id, limit, state):
            _ = workspace_id, limit, state
            return queued

        def enqueue(self, command):
            queued.append(
                SimpleNamespace(
                    job_key=command.job_key,
                    mandate_id=command.mandate_id,
                    state="queued",
                )
            )
            return command

    jobs = Jobs()
    first = enqueue_owner_research_request(
        jobs=jobs,
        mandate=mandate,
        workspace_id="default",
        objective="Find a twenty-day reversal",
        cycle_date=date(2026, 8, 13),
    )
    second = enqueue_owner_research_request(
        jobs=jobs,
        mandate=mandate,
        workspace_id="default",
        objective="Find a twenty-day reversal",
        cycle_date=date(2026, 8, 13),
    )

    assert first == second
    assert first == owner_request_job_key(
        cycle_date=date(2026, 8, 13),
        objective="Find a twenty-day reversal",
    )
    assert first.startswith("request:2026-08-13:")
    assert len(queued) == 1


def test_owner_request_retries_after_a_terminal_job() -> None:
    mandate = SimpleNamespace(
        mandate_id="mandate-test-1",
        policy_digest="a" * 64,
        universe=("SPY", "QQQ"),
        max_iterations=3,
        max_experiments_per_iteration=2,
        paper_execution_allowed=True,
        llm_budget_usd=Decimal("100"),
    )
    queued: list[object] = []

    class Jobs:
        def list(self, *, workspace_id, limit, state):
            return queued

        def enqueue(self, command):
            queued.append(
                SimpleNamespace(
                    job_key=command.job_key,
                    mandate_id=command.mandate_id,
                    state="queued",
                )
            )
            return command

    jobs = Jobs()
    first = enqueue_owner_research_request(
        jobs=jobs,
        mandate=mandate,
        workspace_id="default",
        objective="Find a twenty-day reversal",
        cycle_date=date(2026, 8, 13),
    )
    queued[0].state = "rejected"
    second = enqueue_owner_research_request(
        jobs=jobs,
        mandate=mandate,
        workspace_id="default",
        objective="Find a twenty-day reversal",
        cycle_date=date(2026, 8, 13),
    )

    assert first != second
    assert second == f"{first}:2"
    assert len(queued) == 2


def test_owner_request_input_has_no_snapshot() -> None:
    captured: list[object] = []

    class Jobs:
        def list(self, *, workspace_id, limit, state):
            return []

        def enqueue(self, command):
            captured.append(command)
            return command

    enqueue_owner_research_request(
        jobs=Jobs(),
        mandate={
            "mandate_id": "mandate-test-1",
            "policy_digest": "b" * 64,
            "universe": ["SPY"],
            "max_iterations": 1,
            "max_experiments_per_iteration": 1,
            "paper_execution_allowed": True,
            "llm_budget_usd": "25.00",
        },
        workspace_id="default",
        objective="Compose a volume surprise expression",
        cycle_date=date(2026, 8, 13),
    )

    document = captured[0].input_document
    assert document["trigger"] == OWNER_REQUEST_TRIGGER
    assert document["objective"] == "Compose a volume surprise expression"
    assert "snapshot_id" not in document
    assert "snapshot_parquet" not in document
