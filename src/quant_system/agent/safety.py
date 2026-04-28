from __future__ import annotations

import re
from pathlib import Path

from quant_system.agent.models import AgentDecision

_SAFE_CANDIDATE_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")


class SafetyGate:
    """Manual-review gate for agent candidates.

    The gate deliberately has no path that promotes artifacts automatically.
    It only observes whether a human-created approval lock exists.
    """

    def __init__(self, candidates_dir: str | Path) -> None:
        self.candidates_dir = Path(candidates_dir)

    def allow_promotion(self, candidate_id: str) -> bool:
        if _SAFE_CANDIDATE_ID.fullmatch(candidate_id) is None:
            return False
        root = self.candidates_dir.resolve()
        candidate_dir = (self.candidates_dir / candidate_id).resolve()
        try:
            candidate_dir.relative_to(root)
        except ValueError:
            return False
        return (candidate_dir / "approved.lock").exists()

    def evaluate(self, candidate_id: str) -> AgentDecision:
        allowed = self.allow_promotion(candidate_id)
        return AgentDecision(
            allowed=allowed,
            candidate_id=candidate_id,
            reason="manual approval lock present" if allowed else "manual approval required",
            safety={
                "auto_promotion": False,
                "requires_human_review": True,
            },
        )
