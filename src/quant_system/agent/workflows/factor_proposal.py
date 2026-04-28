from __future__ import annotations

from quant_system.agent.audit import AgentAuditLog
from quant_system.agent.candidate_pool import CandidatePool
from quant_system.agent.llm.base import LLMClient
from quant_system.agent.models import AgentTask, CandidateArtifact
from quant_system.agent.tools import AgentToolbox


def run(
    *,
    llm: LLMClient,
    audit: AgentAuditLog,
    candidates: CandidatePool,
    task: AgentTask,
    goal: str,
    universe: list[str],
) -> CandidateArtifact:
    audit.record("tool_call", {"tool": "list_factors"})
    factors = AgentToolbox.list_factors()
    audit.record("tool_call", {"tool": "propose_factor_code", "goal": goal})
    source = AgentToolbox.propose_factor_code(
        goal=goal,
        universe=universe,
        factors=factors,
        llm=llm,
    )
    artifact = candidates.write_candidate(
        task_id=task.task_id,
        goal=goal,
        artifact_type="factor",
        filename="factor.py.candidate",
        content=source,
        universe=universe,
        metadata_extra={"source": "agent_factor_proposal"},
    )
    audit.record(
        "candidate_written",
        {
            "candidate_id": artifact.candidate_id,
            "path": str(artifact.path),
            "metadata_path": str(artifact.metadata_path),
        },
    )
    return artifact
