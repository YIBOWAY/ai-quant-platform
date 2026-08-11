from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from quant_system.d34.artifact_factor import load_d34_paper_factor_registry
from quant_system.d34.research_driver import (
    D34ResearchRequest,
    QlibExperimentResult,
    ResearchProposal,
    execute_research_request,
    render_factor_source,
)


def _request(tmp_path: Path) -> D34ResearchRequest:
    provider = tmp_path / "qlib-provider"
    provider.mkdir()
    return D34ResearchRequest.model_validate(
        {
            "contract": "hqa.d34_research_request/v1",
            "job_id": "job-12345678",
            "mandate_id": "mandate-12345678",
            "snapshot_id": "snapshot-12345678",
            "snapshot_digest": "a" * 64,
            "snapshot_source": "futu",
            "provider_uri": str(provider),
            "universe": ["SPY", "QQQ", "IWM", "DIA"],
            "calendar": [
                "2026-07-01T00:00:00+00:00",
                "2026-07-02T00:00:00+00:00",
                "2026-07-03T00:00:00+00:00",
            ],
            "max_iterations": 2,
            "experiments_per_iteration": 2,
            "top_k": 1,
            "initial_cash": 100000,
            "budget_reservation_usd": 8,
            "objective": "Find a robust cross-sectional daily paper factor.",
        }
    )


def test_request_is_futu_only_and_bounded(tmp_path: Path) -> None:
    request = _request(tmp_path)
    assert request.universe == ("SPY", "QQQ", "IWM", "DIA")
    assert request.experiment_count == 4

    document = request.model_dump(mode="json")
    document["snapshot_source"] = "sample"
    with pytest.raises(ValueError):
        D34ResearchRequest.model_validate(document)

    document = request.model_dump(mode="json")
    document["universe"] = ["SPY", "SPY"]
    with pytest.raises(ValueError):
        D34ResearchRequest.model_validate(document)


@pytest.mark.parametrize(
    ("operator", "short_window", "long_window", "expected_fragment"),
    [
        ("momentum", 1, 5, "pct_change"),
        ("mean_reversion", 1, 5, "pct_change"),
        ("low_volatility", 1, 5, "rolling"),
        ("volume_surprise", 1, 5, "volume"),
        ("moving_average_spread", 3, 10, "short_mean"),
    ],
)
def test_factor_renderer_produces_digest_bound_platform_factor(
    tmp_path: Path,
    operator: str,
    short_window: int,
    long_window: int,
    expected_fragment: str,
) -> None:
    proposal = ResearchProposal(
        title="Observable test factor",
        thesis="A deterministic cross-sectional relationship should persist.",
        operator=operator,
        short_window=short_window,
        long_window=long_window,
        rationale="Exercise the shared factor specification.",
    )
    factor_id = f"d34_{operator}"
    source, digest = render_factor_source(proposal=proposal, factor_id=factor_id)
    assert expected_fragment in source

    path = tmp_path / "candidate_factor.py"
    path.write_text(source, encoding="utf-8")
    registry = load_d34_paper_factor_registry(
        code_path=path,
        expected_code_digest=digest,
        expected_factor_id=factor_id,
    )
    factor = registry.create(factor_id)
    frame = pd.DataFrame(
        {
            "symbol": ["SPY"] * 12,
            "timestamp": pd.date_range("2026-01-01", periods=12, tz="UTC"),
            "close": [100 + index for index in range(12)],
            "volume": [1_000_000 + index * 1_000 for index in range(12)],
        }
    )
    result = factor.compute(frame)
    assert set(result["factor_id"]) == {factor_id}


def test_research_loop_iterates_selects_best_and_is_idempotent(tmp_path: Path) -> None:
    request = _request(tmp_path)
    proposals: list[tuple[int, int, int]] = []
    run_scores = iter((0.2, 0.5, 1.4, 0.8))

    def propose(
        _request: D34ResearchRequest,
        iteration: int,
        experiment: int,
        history: tuple[dict[str, object], ...],
    ) -> ResearchProposal:
        proposals.append((iteration, experiment, len(history)))
        return ResearchProposal(
            title=f"Momentum iteration {iteration} experiment {experiment}",
            thesis="Cross-sectional persistence may survive one-day execution lag.",
            operator="momentum",
            short_window=1,
            long_window=3 + iteration + experiment,
            rationale="Refine the lookback from prior observed receipts.",
        )

    def run_experiment(
        _request: D34ResearchRequest,
        proposal: ResearchProposal,
        qlib_expression: str,
        experiment_dir: Path,
    ) -> QlibExperimentResult:
        score = next(run_scores)
        assert qlib_expression.startswith("$close/Ref")
        assert experiment_dir.is_dir()
        weights = pd.DataFrame(
            {
                "tradeable_ts": pd.to_datetime(
                    ["2026-07-02T00:00:00Z", "2026-07-03T00:00:00Z"]
                ),
                "symbol": ["SPY", "QQQ"],
                "target_weight": [0.99, 0.99],
            }
        )
        return QlibExperimentResult(
            score=score,
            daily_returns=(0.0, score / 100, 0.001),
            return_dates=tuple(_request.calendar),
            terminal_nav=1 + score / 100,
            terminal_weights={"SPY": 0.99},
            target_weights=weights,
            metrics={"sharpe": score},
            qlib_config={"expression": qlib_expression, "proposal": proposal.title},
        )

    output_root = tmp_path / "outputs"
    result = execute_research_request(
        request,
        output_root=output_root,
        proposal_provider=propose,
        experiment_runner=run_experiment,
        cost_provider=lambda: 1.25,
    )

    assert proposals == [(1, 1, 0), (1, 2, 1), (2, 1, 2), (2, 2, 3)]
    assert result.contract == "hqa.d34_research_result/v1"
    assert result.selected_experiment == "iteration-02-experiment-01"
    assert result.budget_spent_usd == 1.25
    assert result.output_dir.name.startswith("research-")
    assert result.factor_path.is_file()
    assert result.target_weights_path.is_file()
    assert result.qlib_receipt_path.is_file()
    assert len(result.candidate_code_digest) == 64
    assert len(result.qlib_config_digest) == 64
    assert len(result.target_weights_digest) == 64
    receipt = json.loads(result.qlib_receipt_path.read_text(encoding="utf-8"))
    assert receipt["contract"] == "hqa.d34_engine_receipt/v1"
    assert receipt["engine"] == "qlib"
    assert receipt["snapshot_digest"] == request.snapshot_digest
    assert receipt["target_weights_digest"] == result.target_weights_digest
    assert receipt["research_summary_digest"]

    replay = execute_research_request(
        request,
        output_root=output_root,
        proposal_provider=lambda *_args: pytest.fail("idempotent replay called LLM"),
        experiment_runner=lambda *_args: pytest.fail("idempotent replay reran Qlib"),
        cost_provider=lambda: 99,
    )
    assert replay == result
