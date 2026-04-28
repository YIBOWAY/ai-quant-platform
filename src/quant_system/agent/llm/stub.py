from __future__ import annotations

import hashlib


class StubLLMClient:
    """Deterministic offline LLM replacement for tests and local dry runs."""

    def __init__(self, response: str | None = None) -> None:
        self.response = response

    def generate(
        self,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        if self.response is not None:
            return self.response
        digest = hashlib.sha256(f"{system}\n{prompt}".encode()).hexdigest()[:12]
        return "\n".join(
            [
                "from quant_system.factors.base import BaseFactor, FactorMetadata",
                "",
                "",
                "class AgentCandidateFactor(BaseFactor):",
                '    factor_id = "agent_candidate_low_vol_momentum"',
                '    factor_name = "Agent Candidate Low Vol Momentum"',
                '    factor_version = "0.1.0-candidate"',
                '    description = "Deterministic offline candidate; requires human review."',
                "",
                "    @property",
                "    def metadata(self) -> FactorMetadata:",
                "        return FactorMetadata(",
                "            factor_id=self.factor_id,",
                "            factor_name=self.factor_name,",
                "            factor_version=self.factor_version,",
                "            description=self.description,",
                "            lookback=self.lookback,",
                '            direction="higher_is_better",',
                "        )",
                "",
                "    def _compute_values(self, frame):",
                f"        # stub_generation_id={digest}",
                '        return frame.groupby("symbol")["close"].pct_change(self.lookback)',
            ]
        )
