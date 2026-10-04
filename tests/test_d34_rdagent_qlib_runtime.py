from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from quant_system.d34.rdagent_qlib_runtime import (
    RDAgentCostMeter,
    RDAgentProposalProvider,
    shifted_target_weights,
)
from quant_system.d34.research_driver import D34ResearchRequest


def test_cost_meter_flags_zero_acc_cost_increment_after_llm_path() -> None:
    meter = RDAgentCostMeter.__new__(RDAgentCostMeter)
    meter._reservation = 6.0
    meter._module = type("Module", (), {"ACC_COST": 12.5})()
    meter._baseline = 12.5
    assert meter.spent() == 0.0
    assert meter.metering_alert(spent=0.0) == "d34_budget_metering_failed"
    meter._baseline = 10.0
    assert meter.spent() == 2.5
    assert meter.metering_alert(spent=2.5) is None
    meter._module = None
    assert meter.metering_alert(spent=0.0) is None


def test_rdagent_proposal_uses_structured_json_and_prior_receipts(tmp_path) -> None:
    provider = tmp_path / "provider"
    provider.mkdir()
    request = D34ResearchRequest.model_validate(
        {
            "contract": "hqa.d34_research_request/v2",
            "job_id": "job-12345678",
            "run_id": "attempt-12345678",
            "resource_envelope_id": "local-paper-research-v1",
            "resource_policy_digest": "f539564775cd6f0c51fbd8478697265c1f4df86987513dad5e7a842b92191270",
            "snapshot_id": "snapshot-12345678",
            "snapshot_digest": "a" * 64,
            "snapshot_source": "futu",
            "provider_uri": str(provider.resolve()),
            "universe": ["SPY", "QQQ"],
            "calendar": [
                "2026-07-01T00:00:00+00:00",
                "2026-07-02T00:00:00+00:00",
                "2026-07-06T00:00:00+00:00",
            ],
            "max_iterations": 3,
            "experiments_per_iteration": 3,
            "top_k": 1,
            "objective": "Find one useful paper factor.",
        }
    )

    class Backend:
        prompt = ""
        json_mode = False
        response_format_present = False

        def build_messages_and_create_chat_completion(self, prompt, **kwargs):
            self.prompt = prompt
            self.json_mode = kwargs["json_mode"]
            self.response_format_present = "response_format" in kwargs
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
    assert backend.json_mode is True
    assert backend.response_format_present is False
    assert "iteration-01-experiment-01" in backend.prompt
    assert '"title"' in backend.prompt
    assert '"short_window": 0' in backend.prompt
    assert "0 means no skip" in backend.prompt
    assert "Do not use 1 as a sentinel" in backend.prompt
    assert '"long_window"' in backend.prompt
    assert '"rationale"' in backend.prompt
    assert "Do not output Python" in backend.prompt
    assert "composed" in backend.prompt
    assert '"qlib_expr": "$close/Ref($close,20)-1"' in backend.prompt
    assert "time-series percentile" in backend.prompt


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
        "2026-07-06T00:00:00+00:00",
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
            "tradeable_ts": pd.Timestamp("2026-07-06T00:00:00Z"),
            "symbol": "QQQ",
            "target_weight": 0.99,
        },
    ]


def test_rdagent_cost_meter_reports_overrun_instead_of_hiding_it() -> None:
    meter = RDAgentCostMeter(reservation_usd=1.0)
    meter._module = SimpleNamespace(ACC_COST=2.75)
    meter._baseline = 0.25

    assert meter.spent() == 2.5
