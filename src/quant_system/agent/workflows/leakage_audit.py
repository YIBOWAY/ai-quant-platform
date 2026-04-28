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
    factor_id: str,
) -> CandidateArtifact:
    audit.record("tool_call", {"tool": "list_factors"})
    factors = AgentToolbox.list_factors()
    llm.generate(
        f"Audit factor {factor_id}. Known factors: {factors}",
        system="Produce a leakage checklist. Do not change code.",
        max_tokens=800,
        temperature=0.0,
    )
    lines = [
        "# Agent Leakage Audit",
        "",
        f"- Factor id: {factor_id}",
        "- Check rolling windows use only trailing data.",
        "- Check factor timestamps are signal timestamps, not trade timestamps.",
        "- Check execution happens on `tradeable_ts`, not the same close used for signal.",
        "- Check no global full-frame ranking is used where cross-sectional ranking is required.",
        "- Check sample-data results are not treated as production evidence.",
        "",
        "This checklist is advisory and requires human review.",
        "",
    ]
    artifact = candidates.write_candidate(
        task_id=task.task_id,
        goal=f"leakage audit {factor_id}",
        artifact_type="leakage_audit",
        filename="leakage_audit.md",
        content="\n".join(lines),
        metadata_extra={"source": "agent_leakage_audit"},
    )
    audit.record(
        "candidate_written",
        {
            "candidate_id": artifact.candidate_id,
            "path": str(artifact.path),
        },
    )
    return artifact
