from __future__ import annotations

import json
from pathlib import Path

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
    output_dir: str | Path,
    experiment_id: str,
) -> CandidateArtifact:
    audit.record("tool_call", {"tool": "read_experiment_summary", "experiment_id": experiment_id})
    summary = AgentToolbox.read_experiment_summary(
        experiment_id=experiment_id,
        output_dir=output_dir,
    )
    llm_note = llm.generate(
        json.dumps(summary, sort_keys=True),
        system="Summarize research experiments for human review only.",
        max_tokens=800,
        temperature=0.0,
    )
    lines = [
        "# Agent Experiment Summary",
        "",
        f"- Experiment id: {experiment_id}",
        f"- Found local summary: {summary.get('found', True)}",
        "- Live trading: disabled",
        "- Auto promotion: disabled",
        "",
        "## Assistant Note",
        "",
        llm_note,
        "",
    ]
    artifact = candidates.write_candidate(
        task_id=task.task_id,
        goal=f"summarize {experiment_id}",
        artifact_type="result_summary",
        filename="agent_summary.md",
        content="\n".join(lines),
        metadata_extra={"source": "agent_result_summary"},
    )
    reports_dir = Path(output_dir) / "reports" / "agent"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{experiment_id}_agent_summary.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    audit.record(
        "candidate_written",
        {
            "candidate_id": artifact.candidate_id,
            "path": str(artifact.path),
            "report_path": str(report_path),
        },
    )
    return artifact
