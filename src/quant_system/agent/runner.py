from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from quant_system.agent.audit import AgentAuditLog
from quant_system.agent.candidate_pool import CandidatePool
from quant_system.agent.llm.base import LLMClient
from quant_system.agent.llm.stub import StubLLMClient
from quant_system.agent.models import (
    AgentTask,
    AgentTaskType,
    CandidateArtifact,
    ReviewRecord,
    utc_now_iso,
)
from quant_system.agent.workflows import (
    experiment_design,
    factor_proposal,
    leakage_audit,
    result_summary,
)


def _task_id(task_type: AgentTaskType, subject: str) -> str:
    created = utc_now_iso().replace(":", "").replace("-", "")
    digest = hashlib.sha256(f"{task_type.value}|{subject}|{created}".encode()).hexdigest()[:8]
    return f"agent-{task_type.value}-{created}-{digest}"


class AgentRunner:
    def __init__(
        self,
        *,
        agent_output_dir: str | Path,
        result_output_dir: str | Path | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self.agent_output_dir = Path(agent_output_dir)
        # Experiment/result reads are a separately named root. Never fall back
        # from general data into the candidate root, or the reverse.
        self.result_output_dir = (
            Path(result_output_dir)
            if result_output_dir is not None
            else self.agent_output_dir
        )
        self.llm = llm or StubLLMClient()
        self.candidates = CandidatePool(self.agent_output_dir)

    def propose_factor(
        self,
        *,
        goal: str,
        universe: list[str],
        metadata_extra: dict[str, Any] | None = None,
    ) -> CandidateArtifact:
        task = AgentTask(
            task_id=_task_id(AgentTaskType.FACTOR_PROPOSAL, goal),
            task_type=AgentTaskType.FACTOR_PROPOSAL,
            goal=goal,
            universe=universe,
        )
        audit = AgentAuditLog(self.agent_output_dir, task_id=task.task_id)
        audit.record("task", task.model_dump(mode="json"))
        return factor_proposal.run(
            llm=self.llm,
            audit=audit,
            candidates=self.candidates,
            task=task,
            goal=goal,
            universe=universe,
            metadata_extra=metadata_extra,
        )

    def propose_experiment(self, *, goal: str, universe: list[str]) -> CandidateArtifact:
        task = AgentTask(
            task_id=_task_id(AgentTaskType.EXPERIMENT_DESIGN, goal),
            task_type=AgentTaskType.EXPERIMENT_DESIGN,
            goal=goal,
            universe=universe,
        )
        audit = AgentAuditLog(self.agent_output_dir, task_id=task.task_id)
        audit.record("task", task.model_dump(mode="json"))
        return experiment_design.run(
            llm=self.llm,
            audit=audit,
            candidates=self.candidates,
            task=task,
            goal=goal,
            universe=universe,
        )

    def summarize(self, *, experiment_id: str) -> CandidateArtifact:
        task = AgentTask(
            task_id=_task_id(AgentTaskType.RESULT_SUMMARY, experiment_id),
            task_type=AgentTaskType.RESULT_SUMMARY,
            goal=f"summarize {experiment_id}",
            experiment_id=experiment_id,
        )
        audit = AgentAuditLog(self.agent_output_dir, task_id=task.task_id)
        audit.record("task", task.model_dump(mode="json"))
        return result_summary.run(
            llm=self.llm,
            audit=audit,
            candidates=self.candidates,
            task=task,
            output_dir=self.result_output_dir,
            experiment_id=experiment_id,
        )

    def audit_leakage(self, *, factor_id: str) -> CandidateArtifact:
        task = AgentTask(
            task_id=_task_id(AgentTaskType.LEAKAGE_AUDIT, factor_id),
            task_type=AgentTaskType.LEAKAGE_AUDIT,
            goal=f"leakage audit {factor_id}",
            factor_id=factor_id,
        )
        audit = AgentAuditLog(self.agent_output_dir, task_id=task.task_id)
        audit.record("task", task.model_dump(mode="json"))
        return leakage_audit.run(
            llm=self.llm,
            audit=audit,
            candidates=self.candidates,
            task=task,
            factor_id=factor_id,
        )

    def list_candidates(self) -> list[dict]:
        return [
            item.model_dump(mode="json") for item in self.candidates.list_for_read()
        ]

    def review(
        self,
        *,
        candidate_id: str,
        decision: Literal["approve", "reject"],
        note: str,
        expected_manifest_digest: str,
        expected_status: Literal["pending"],
        reviewer: Literal["auto", "manual"] = "manual",
    ) -> ReviewRecord:
        # Validate CAS inputs before any audit/root IO so invalid IDs leave
        # zero writes (shared with CandidatePool.review preconditions).
        from quant_system.agent.candidate_manifest import _validate_candidate_id
        from quant_system.agent.candidate_pool import (
            _validate_digest,
            _validate_note,
        )

        candidate_id = _validate_candidate_id(candidate_id)
        expected_manifest_digest = _validate_digest(expected_manifest_digest)
        note = _validate_note(note)
        if expected_status != "pending":
            from quant_system.agent.candidate_fs import CandidateIntegrityError

            raise CandidateIntegrityError(
                "expected_status must be the literal 'pending'"
            )
        if decision not in {"approve", "reject"}:
            from quant_system.agent.candidate_fs import CandidateIntegrityError

            raise CandidateIntegrityError("decision must be approve or reject")
        if reviewer not in {"auto", "manual"}:
            from quant_system.agent.candidate_fs import CandidateIntegrityError

            raise CandidateIntegrityError("reviewer must be auto or manual")

        task_id = _task_id(AgentTaskType.REVIEW, candidate_id)
        audit = AgentAuditLog(self.agent_output_dir, task_id=task_id)
        # Record CAS values before mutation; never re-list to derive them.
        audit.record(
            "task",
            {
                "task_id": task_id,
                "task_type": AgentTaskType.REVIEW.value,
                "candidate_id": candidate_id,
                "expected_manifest_digest": expected_manifest_digest,
                "expected_status": expected_status,
                "decision": decision,
                "reviewer": reviewer,
            },
        )
        record = self.candidates.review(
            candidate_id=candidate_id,
            decision=decision,
            note=note,
            expected_manifest_digest=expected_manifest_digest,
            expected_status=expected_status,
            reviewer=reviewer,
        )
        audit.record("review_recorded", record.model_dump(mode="json"))
        return record
