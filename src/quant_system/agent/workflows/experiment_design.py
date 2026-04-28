from __future__ import annotations

import json

from quant_system.agent.audit import AgentAuditLog
from quant_system.agent.candidate_pool import CandidatePool
from quant_system.agent.llm.base import LLMClient
from quant_system.agent.models import AgentTask, CandidateArtifact
from quant_system.agent.tools import AgentToolbox
from quant_system.experiments.models import ExperimentConfig


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
    AgentToolbox.list_factors()
    audit.record("tool_call", {"tool": "propose_experiment_config", "goal": goal})
    config_payload = AgentToolbox.propose_experiment_config(
        goal=goal,
        universe=universe,
        llm=llm,
    )
    config = ExperimentConfig.model_validate(config_payload)
    artifact = candidates.write_candidate(
        task_id=task.task_id,
        goal=goal,
        artifact_type="experiment_config",
        filename="experiment_config.json",
        content=json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True),
        universe=universe,
        metadata_extra={"source": "agent_experiment_design"},
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
