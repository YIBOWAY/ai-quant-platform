from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from quant_system.d34.artifact_factor import load_d34_paper_factor_registry
from quant_system.d34.research_driver import (
    HISTORICAL_DSR_REVIEW_NOTES,
    HUNG_MOMENTUM_CANDIDATE_ID,
    HUNG_MOMENTUM_CORRECTION_NOTE,
    READ_ONLY_DSR_CANDIDATE_ID,
    D34ResearchError,
    D34ResearchRequest,
    QlibExperimentResult,
    ResearchProposal,
    annotate_hung_momentum_candidates,
    execute_research_request,
    factor_display_name_zh,
    qlib_expression,
    render_factor_source,
)


def _request(tmp_path: Path) -> D34ResearchRequest:
    provider = tmp_path / "qlib-provider"
    provider.mkdir()
    return D34ResearchRequest.model_validate(
        {
            "contract": "hqa.d34_research_request/v2",
            "job_id": "job-12345678",
            "run_id": "attempt-12345678",
            "resource_envelope_id": "local-paper-research-v1",
            "resource_policy_digest": "f539564775cd6f0c51fbd8478697265c1f4df86987513dad5e7a842b92191270",
            "snapshot_id": "snapshot-12345678",
            "snapshot_digest": "a" * 64,
            "snapshot_source": "futu",
            "provider_uri": str(provider),
            "universe": ["SPY", "QQQ", "IWM", "DIA"],
            "calendar": [
                "2026-07-01T00:00:00+00:00",
                "2026-07-02T00:00:00+00:00",
                "2026-07-06T00:00:00+00:00",
            ],
            "max_iterations": 3,
            "experiments_per_iteration": 3,
            "top_k": 1,
            "initial_cash": 100000,
            "budget_reservation_usd": 10,
            "objective": "Find a robust cross-sectional daily paper factor.",
        }
    )


def test_request_is_futu_only_and_bounded(tmp_path: Path) -> None:
    request = _request(tmp_path)
    assert request.universe == ("SPY", "QQQ", "IWM", "DIA")
    assert request.experiment_count == 9

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
        ("momentum", 0, 5, "pct_change"),
        ("mean_reversion", 0, 5, "pct_change"),
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
    assert f"display_name_zh = {factor_display_name_zh(proposal)!r}" in source

    path = tmp_path / "candidate_factor.py"
    path.write_text(source, encoding="utf-8")
    registry = load_d34_paper_factor_registry(
        code_path=path,
        expected_code_digest=digest,
        expected_factor_id=factor_id,
    )
    factor = registry.create(factor_id)
    assert factor.metadata.display_name_zh == factor_display_name_zh(proposal)
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


@pytest.mark.parametrize(
    ("operator", "short_window", "long_window", "expected"),
    [
        ("momentum", 0, 21, "21 日横截面动量"),
        ("momentum", 1, 21, "跳过最近 1 日的 21 日横截面动量"),
        ("mean_reversion", 0, 10, "10 日均值回归"),
        ("low_volatility", 0, 20, "20 日低波动"),
        ("volume_surprise", 0, 15, "15 日成交量异动"),
        ("moving_average_spread", 5, 20, "5 日 / 20 日均线差"),
        ("composed", 0, 20, "20 日复合选股因子"),
    ],
)
def test_generated_factor_zh_name_is_deterministic(
    operator: str,
    short_window: int,
    long_window: int,
    expected: str,
) -> None:
    proposal = ResearchProposal(
        title="Model supplied English title",
        thesis="Model supplied English thesis.",
        operator=operator,
        short_window=short_window,
        long_window=long_window,
        rationale="Structured fields own the Chinese presentation name.",
        qlib_expr="-$close/Ref($close,20)+1" if operator == "composed" else None,
    )

    assert factor_display_name_zh(proposal) == expected


def test_momentum_honors_short_window_as_skip_n() -> None:
    ordinary = ResearchProposal(
        title="Ordinary twenty-one day momentum",
        thesis="Cross-sectional 21-day return.",
        operator="momentum",
        short_window=0,
        long_window=21,
        rationale="Zero skip is ordinary lookback.",
    )
    assert ordinary.short_window == 0
    assert qlib_expression(ordinary) == "$close/Ref($close,21)-1"
    ordinary_source, _ = render_factor_source(
        proposal=ordinary, factor_id="d34_mom_ordinary"
    )
    assert "pct_change(self.lookback)" in ordinary_source

    skip_one = ResearchProposal(
        title="Skip-one twenty-one day momentum",
        thesis="Skip one day then 21-day return.",
        operator="momentum",
        short_window=1,
        long_window=21,
        rationale="Skip-1 must be expressible.",
    )
    assert qlib_expression(skip_one) == "Ref($close,1)/Ref($close,22)-1"
    skip_one_source, _ = render_factor_source(
        proposal=skip_one, factor_id="d34_mom_skip_one"
    )
    assert "values.shift(1)" in skip_one_source
    assert "values.shift(22)" in skip_one_source
    assert "pct_change(self.lookback)" not in skip_one_source

    skip = ResearchProposal(
        title="Skip-five twenty-one day momentum",
        thesis="Skip five days then 21-day return.",
        operator="momentum",
        short_window=5,
        long_window=21,
        rationale="Honor skip-N.",
    )
    assert qlib_expression(skip) == "Ref($close,5)/Ref($close,26)-1"
    skip_source, _ = render_factor_source(proposal=skip, factor_id="d34_mom_skip")
    assert "values.shift(5)" in skip_source
    assert "values.shift(26)" in skip_source
    assert "pct_change(self.lookback)" not in skip_source


def test_momentum_default_short_window_is_zero_not_skip_one() -> None:
    proposal = ResearchProposal(
        title="Default is unset skip",
        thesis="Omitted short_window must not mean skip-1.",
        operator="momentum",
        long_window=21,
        rationale="Unset and skip-1 are different.",
    )
    assert proposal.short_window == 0
    assert qlib_expression(proposal) == "$close/Ref($close,21)-1"


def test_moving_average_spread_requires_positive_short_window() -> None:
    with pytest.raises(ValueError, match="d34_factor_window_invalid"):
        ResearchProposal(
            title="Spread without a short window",
            thesis="The short mean cannot be zero length.",
            operator="moving_average_spread",
            short_window=0,
            long_window=20,
            rationale="Untangle skip-N from the short MA window.",
        )


def test_historical_digest_bound_source_is_not_re_rendered(tmp_path: Path) -> None:
    historical = ResearchProposal(
        title="Ordinary twenty-one day momentum",
        thesis="Cross-sectional 21-day return.",
        operator="momentum",
        short_window=0,
        long_window=21,
        rationale="Stored source is the hung artifact.",
    )
    source, digest = render_factor_source(
        proposal=historical, factor_id="d34_mom_ordinary"
    )
    assert "pct_change(self.lookback)" in source
    path = tmp_path / "candidate_factor.py"
    path.write_text(source, encoding="utf-8")
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == digest

    skip_one = ResearchProposal(
        title="Skip-one twenty-one day momentum",
        thesis="Skip one day then 21-day return.",
        operator="momentum",
        short_window=1,
        long_window=21,
        rationale="New renderer honors skip-1.",
    )
    new_source, new_digest = render_factor_source(
        proposal=skip_one, factor_id="d34_mom_ordinary"
    )
    assert new_digest != digest
    assert "pct_change(self.lookback)" not in new_source

    registry = load_d34_paper_factor_registry(
        code_path=path,
        expected_code_digest=digest,
        expected_factor_id="d34_mom_ordinary",
    )
    factor = registry.create("d34_mom_ordinary")
    assert factor.factor_id == "d34_mom_ordinary"
    assert path.read_text(encoding="utf-8") == source


def test_hung_momentum_candidate_gets_correction_note_without_rewriting_objective() -> None:
    objective = "Discover and falsify one daily cross-sectional momentum variant."
    raw = [
        {
            "candidate_id": HUNG_MOMENTUM_CANDIDATE_ID,
            "objective": objective,
            "status": "hung",
            "sleeve_id": "sleeve-7b28fcdb6717",
        },
        {
            "candidate_id": READ_ONLY_DSR_CANDIDATE_ID,
            "objective": "Read-only historical candidate.",
            "status": "verified",
            "sleeve_id": None,
        },
        {"candidate_id": "artifact-other", "objective": "leave me", "status": "verified"},
    ]
    annotated = annotate_hung_momentum_candidates(
        raw
    )
    assert annotated[0]["objective"] == objective
    assert HUNG_MOMENTUM_CORRECTION_NOTE in annotated[0]["description_note"]
    assert (
        HISTORICAL_DSR_REVIEW_NOTES[HUNG_MOMENTUM_CANDIDATE_ID]
        in annotated[0]["description_note"]
    )
    assert "主人已知情" in annotated[0]["description_note"]
    assert "普通 21 日动量" in annotated[0]["description_note"]
    assert "DSR=0.840302" in annotated[0]["description_note"]
    assert annotated[0]["status"] == "hung"
    assert annotated[0]["sleeve_id"] == "sleeve-7b28fcdb6717"
    assert "DSR=0.852474" in annotated[1]["description_note"]
    assert annotated[1]["status"] == "verified"
    assert annotated[1]["sleeve_id"] is None
    assert "description_note" not in annotated[2]
    assert all("description_note" not in item for item in raw)


def test_composed_expression_renders_validated_qlib_and_pandas() -> None:
    proposal = ResearchProposal(
        title="Ranked twenty-day reversal",
        thesis="Names that fell for twenty days should mean-revert next open.",
        operator="composed",
        short_window=1,
        long_window=20,
        qlib_expr="Rank(1-$close/Ref($close,20),1)",
        rationale="Prior catalog momentum receipts did not fade enough.",
    )
    assert qlib_expression(proposal).startswith("Rank(")
    source, digest = render_factor_source(proposal=proposal, factor_id="d34_composed_rev")
    assert "import numpy as np" in source
    assert "rank(pct=True)" in source
    assert len(digest) == 64


@pytest.mark.parametrize("formula", [None, "$close/Ref($close,5)-1"])
def test_research_loop_iterates_or_reproduces_exact_formula_once(tmp_path: Path, formula) -> None:
    request = _request(tmp_path)
    if formula is not None:
        request = D34ResearchRequest.model_validate({**request.model_dump(), "formula": formula})
    proposals: list[tuple[int, int, int]] = []
    run_scores = iter((0.2, 0.5, 0.7, 1.4, 0.8, 0.6, 0.4, 0.3, 0.1))

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
            short_window=0,
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
        if formula is not None:
            assert qlib_expression == "(($close/Ref($close,5))-1)"
        else:
            assert qlib_expression.startswith("$close/Ref")
        assert experiment_dir.is_dir()
        weights = pd.DataFrame(
            {
                "tradeable_ts": pd.to_datetime(
                    ["2026-07-02T00:00:00Z", "2026-07-06T00:00:00Z"]
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
        trials_root=tmp_path / "trials",
    )

    assert proposals == ([] if formula is not None else [
        (iteration, experiment, (iteration - 1) * 3 + experiment - 1)
        for iteration in range(1, 4)
        for experiment in range(1, 4)
    ])
    assert result.contract == "hqa.d34_research_result/v2"
    assert result.selected_experiment == (
        "iteration-01-experiment-01" if formula is not None else "iteration-02-experiment-01"
    )
    assert result.budget_spent_usd == 1.25
    from quant_system.research.trials import TrialsLedger

    trial_rows = TrialsLedger(tmp_path / "trials").list()
    assert trial_rows
    assert all(row.source.startswith(request.job_id) for row in trial_rows)
    assert result.output_dir.name.startswith("research-")
    assert result.factor_path.is_file()
    assert result.target_weights_path.is_file()
    assert result.qlib_receipt_path.is_file()
    assert result.experiment_trials_path.is_file()
    trial_batch = json.loads(result.experiment_trials_path.read_text(encoding="utf-8"))
    assert trial_batch["contract"] == "hqa.d34_experiment_trial_batch/v1"
    assert trial_batch["job_id"] == request.job_id
    assert trial_batch["request_digest"] == request.request_digest
    assert trial_batch["successful_experiment_count"] == request.experiment_count
    assert len(trial_batch["experiments"]) == request.experiment_count
    assert {row["experiment_id"] for row in trial_batch["experiments"]} == {
        f"iteration-{iteration:02d}-experiment-{experiment:02d}"
        for iteration in range(1, 2 if formula is not None else 4)
        for experiment in range(1, 2 if formula is not None else 4)
    }
    assert all(
        len(row["daily_returns"]) == len(request.calendar)
        for row in trial_batch["experiments"]
    )
    assert trial_batch["receipt_digest"] == result.experiment_trials_digest
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
        trials_root=tmp_path / "trials",
    )
    assert replay == result


def test_research_loop_records_invalid_proposal_and_uses_next_experiment(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    calls = 0

    def propose(*_args) -> ResearchProposal:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("model returned the wrong JSON schema")
        return ResearchProposal(
            title="Five day momentum",
            thesis="Recent relative strength may persist.",
            operator="momentum",
            short_window=0,
            long_window=5,
            rationale="Use the next bounded experiment after malformed JSON.",
        )

    def run_experiment(
        _request: D34ResearchRequest,
        _proposal: ResearchProposal,
        _expression: str,
        _experiment_dir: Path,
    ) -> QlibExperimentResult:
        return QlibExperimentResult(
            score=0.5,
            daily_returns=(0.0, 0.01, 0.001),
            return_dates=tuple(_request.calendar),
            terminal_nav=1.011,
            terminal_weights={"SPY": 0.99},
            target_weights=pd.DataFrame(
                {
                    "tradeable_ts": pd.to_datetime(["2026-07-02T00:00:00Z"]),
                    "symbol": ["SPY"],
                    "target_weight": [0.99],
                }
            ),
            metrics={"sharpe": 0.5},
            qlib_config={"expression": "$close/Ref($close, 5)-1"},
        )

    result = execute_research_request(
        request,
        output_root=tmp_path / "outputs",
        proposal_provider=propose,
        experiment_runner=run_experiment,
        cost_provider=lambda: 1.0,
        trials_root=tmp_path / "trials",
    )

    failure = json.loads(
        (
            result.output_dir
            / "experiments/iteration-01-experiment-01/failure.json"
        ).read_text(encoding="utf-8")
    )
    assert calls == 9
    assert failure["error_type"] == "ValueError"
    assert "proposal" not in failure
    assert result.selected_experiment == "iteration-03-experiment-03"


def test_successful_experiment_batch_survives_later_budget_failure(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    return_scale = 1.0

    def propose(*_args) -> ResearchProposal:
        return ResearchProposal(
            title="Bounded momentum",
            thesis="Keep the completed experiment evidence.",
            operator="momentum",
            short_window=0,
            long_window=5,
            rationale="The later budget check must not erase completed trials.",
        )

    def run_experiment(
        _request: D34ResearchRequest,
        _proposal: ResearchProposal,
        _expression: str,
        _experiment_dir: Path,
    ) -> QlibExperimentResult:
        nonlocal return_scale
        return QlibExperimentResult(
            score=1.0,
            daily_returns=(0.0, 0.01 * return_scale, -0.002),
            return_dates=tuple(_request.calendar),
            terminal_nav=1.008,
            terminal_weights={"SPY": 0.99},
            target_weights=pd.DataFrame(
                {
                    "tradeable_ts": pd.to_datetime(_request.calendar[1:]),
                    "symbol": ["SPY", "QQQ"],
                    "target_weight": [0.99, 0.99],
                }
            ),
            metrics={"sharpe": 1.0},
            qlib_config={"expression": "momentum"},
        )

    output_root = tmp_path / "outputs"
    with pytest.raises(D34ResearchError, match="RD-Agent cost exceeded"):
        execute_research_request(
            request,
            output_root=output_root,
            proposal_provider=propose,
            experiment_runner=run_experiment,
            cost_provider=lambda: float("inf"),
            trials_root=tmp_path / "trials",
        )

    batch_path = output_root / f"experiment-trials-{request.request_digest[:32]}.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    original_batch = batch_path.read_bytes()
    assert batch["experiment_count"] == 9
    assert batch["successful_experiment_count"] == 9
    assert len(batch["experiments"]) == 9

    return_scale = 2.0
    with pytest.raises(D34ResearchError, match="existing experiment trial batch"):
        execute_research_request(
            request,
            output_root=output_root,
            proposal_provider=propose,
            experiment_runner=run_experiment,
            cost_provider=lambda: float("inf"),
            trials_root=tmp_path / "trials-replay",
        )
    assert batch_path.read_bytes() == original_batch
