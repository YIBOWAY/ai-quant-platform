from __future__ import annotations

from pathlib import Path

from quant_system.agent.candidate_manifest import (
    CandidateIntegrityError,
    CandidateMigrationRequiredError,
)
from quant_system.agent.candidate_pool import CandidatePool
from quant_system.agent.models import AgentDecision


class SafetyGate:
    """Manual-review gate for agent candidates.

    Accepts only an agent-output root (never a pre-derived candidates directory).
    Authorization requires a verified snapshot whose approval binding is digest-bound.
    """

    def __init__(self, agent_output_dir: str | Path) -> None:
        self.agent_output_dir = Path(agent_output_dir)

    def allow_promotion(self, candidate_id: str) -> bool:
        try:
            snapshot = CandidatePool(self.agent_output_dir).get(candidate_id)
        except (
            CandidateIntegrityError,
            CandidateMigrationRequiredError,
            FileNotFoundError,
            OSError,
        ):
            return False
        return snapshot.approval_binding == "approved"

    def evaluate(self, candidate_id: str) -> AgentDecision:
        allowed = self.allow_promotion(candidate_id)
        return AgentDecision(
            allowed=allowed,
            candidate_id=candidate_id,
            reason=(
                "digest-bound manual approval present"
                if allowed
                else "manual approval required"
            ),
            safety={
                "auto_promotion": False,
                "requires_human_review": True,
            },
        )
