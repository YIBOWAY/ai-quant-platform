from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_system.agent.llm.base import LLMClient
from quant_system.experiments.models import (
    FactorBlendConfig,
    FactorDirection,
    FactorWeight,
    WalkForwardConfig,
)
from quant_system.factors.registry import build_default_factor_registry


class AgentToolbox:
    """Fixed allowlist of pure research tools available to agent workflows."""

    @staticmethod
    def read_experiment_summary(*, experiment_id: str, output_dir: str | Path) -> dict[str, Any]:
        output = Path(output_dir)
        direct_path = output / "experiments" / experiment_id / "agent_summary.json"
        if direct_path.exists():
            return json.loads(direct_path.read_text(encoding="utf-8"))
        for summary_path in output.glob("experiments/*/agent_summary.json"):
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            if payload.get("experiment_id") == experiment_id:
                return payload
        return {
            "experiment_id": experiment_id,
            "found": False,
            "message": "No local agent_summary.json found for this experiment_id.",
        }

    @staticmethod
    def list_factors() -> list[dict[str, Any]]:
        registry = build_default_factor_registry()
        return [metadata.model_dump(mode="json") for metadata in registry.list_metadata()]

    @staticmethod
    def list_strategies() -> list[str]:
        return [
            "ScoreSignalStrategy",
            "multi_factor_score",
            "run_signal_paper_trading",
        ]

    @staticmethod
    def propose_factor_code(
        *,
        goal: str,
        universe: list[str],
        factors: list[dict[str, Any]],
        llm: LLMClient,
    ) -> str:
        prompt = "\n".join(
            [
                "Create one candidate BaseFactor subclass as inert source text.",
                f"Goal: {goal}",
                f"Universe: {', '.join(universe) if universe else 'not specified'}",
                f"Existing factors: {json.dumps(factors, sort_keys=True)}",
                "Do not include trading, broker, shell, network, or credential code.",
            ]
        )
        return llm.generate(
            prompt,
            system="You propose research-only factor candidates for human review.",
            max_tokens=1200,
            temperature=0.0,
        )

    @staticmethod
    def propose_experiment_config(
        *,
        goal: str,
        universe: list[str],
        llm: LLMClient,
    ) -> dict[str, Any]:
        llm.generate(
            f"Design a research experiment only. Goal: {goal}. Universe: {universe}.",
            system="You design offline research configs. No trading promotion is allowed.",
            max_tokens=500,
            temperature=0.0,
        )
        symbols = universe or ["SPY", "QQQ"]
        factor_blend = FactorBlendConfig(
            factors=[
                FactorWeight(
                    factor_id="momentum",
                    weight=1.0,
                    direction=FactorDirection.HIGHER_IS_BETTER,
                ),
                FactorWeight(
                    factor_id="volatility",
                    weight=0.5,
                    direction=FactorDirection.LOWER_IS_BETTER,
                ),
            ],
            rebalance_every_n_bars=5,
        )
        return {
            "experiment_name": "agent-candidate-experiment",
            "symbols": symbols,
            "start": "2024-01-02",
            "end": "2024-03-29",
            "initial_cash": 100_000.0,
            "commission_bps": 1.0,
            "slippage_bps": 5.0,
            "target_gross_exposure": 0.5,
            "factor_blend": factor_blend.model_dump(mode="json"),
            "sweep": {"lookback": [5, 10], "top_n": [1, 2]},
            "walk_forward": WalkForwardConfig(enabled=False).model_dump(mode="json"),
        }
