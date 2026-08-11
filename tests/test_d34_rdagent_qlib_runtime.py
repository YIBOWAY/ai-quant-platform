from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from quant_system.d34.rdagent_qlib_runtime import (
    RDAgentCostMeter,
    RDAgentProposalProvider,
    shifted_target_weights,
)
from quant_system.d34.research_driver import D34ResearchRequest, ResearchProposal


def test_rdagent_proposal_uses_structured_json_and_prior_receipts(tmp_path) -> None:
    provider = tmp_path / "provider"
    provider.mkdir()
    request = D34ResearchRequest.model_validate(
        {
            "contract": "hqa.d34_research_request/v1",
            "job_id": "job-12345678",
            "mandate_id": "mandate-12345678",
            "snapshot_id": "snapshot-12345678",
            "snapshot_digest": "a" * 64,
            "snapshot_source": "futu",
            "provider_uri": str(provider.resolve()),
            "universe": ["SPY", "QQQ"],
            "calendar": [
                "2026-07-01T00:00:00+00:00",
                "2026-07-02T00:00:00+00:00",
                "2026-07-03T00:00:00+00:00",
            ],
            "max_iterations": 1,
            "experiments_per_iteration": 1,
            "top_k": 1,
            "objective": "Find one useful paper factor.",
        }
    )

    class Backend:
        prompt = ""
        response_format = None

        def build_messages_and_create_chat_completion(self, prompt, **kwargs):
            self.prompt = prompt
            self.response_format = kwargs["response_format"]
            return json.dumps(
                {
                    "title": "Five day momentum",
                    "thesis": "Recent relative strength may persist.",
                    "operator": "momentum",
                    "short_window": 1,
                    "long_window": 5,
                    "rationale": "Try a short, observable horizon.",
                }
            )

    backend = Backend()
    proposal = RDAgentProposalProvider(backend)(
        request,
        2,
        1,
        (
            {
                "experiment_id": "iteration-01-experiment-01",
                "status": "succeeded",
                "score": 0.2,
            },
        ),
    )

    assert proposal.operator == "momentum"
    assert backend.response_format is ResearchProposal
    assert "iteration-01-experiment-01" in backend.prompt
    assert "Do not output Python code" in backend.prompt


def test_target_weights_shift_scores_to_next_trade_day() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            ("SPY", pd.Timestamp("2026-07-01")),
            ("QQQ", pd.Timestamp("2026-07-01")),
            ("SPY", pd.Timestamp("2026-07-02")),
            ("QQQ", pd.Timestamp("2026-07-02")),
        ],
        names=["instrument", "datetime"],
    )
    scores = pd.Series([2.0, 1.0, 0.2, 0.9], index=index, name="score")
    calendar = (
        "2026-07-01T00:00:00+00:00",
        "2026-07-02T00:00:00+00:00",
        "2026-07-03T00:00:00+00:00",
    )

    weights = shifted_target_weights(
        scores,
        calendar=calendar,
        top_k=1,
        risk_degree=0.99,
    )

    assert weights.to_dict("records") == [
        {
            "tradeable_ts": pd.Timestamp("2026-07-02T00:00:00Z"),
            "symbol": "SPY",
            "target_weight": 0.99,
        },
        {
            "tradeable_ts": pd.Timestamp("2026-07-03T00:00:00Z"),
            "symbol": "QQQ",
            "target_weight": 0.99,
        },
    ]


def test_rdagent_cost_meter_reports_overrun_instead_of_hiding_it() -> None:
    meter = RDAgentCostMeter(reservation_usd=1.0)
    meter._module = SimpleNamespace(ACC_COST=2.75)
    meter._baseline = 0.25

    assert meter.spent() == 2.5
