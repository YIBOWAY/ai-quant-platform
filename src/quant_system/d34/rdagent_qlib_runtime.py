"""Concrete RD-Agent proposal and Qlib experiment adapters used in Docker."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from quant_system.d34.research_driver import (
    D34_TARGET_GROSS_EXPOSURE,
    D34ResearchError,
    D34ResearchRequest,
    QlibExperimentResult,
    ResearchProposal,
    execute_research_request,
)

RDAGENT_COMMIT = "274e274d5dbb72cc2ea139d1a7c93d73ce9b1198"
QLIB_COMMIT = "da920b7f954f48ab1bb64117c976710de198373e"
RISK_DEGREE = D34_TARGET_GROSS_EXPOSURE
ONE_WAY_COST = 0.0006


class RDAgentProposalProvider:
    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def __call__(
        self,
        request: D34ResearchRequest,
        iteration: int,
        experiment: int,
        history: tuple[dict[str, object], ...],
    ) -> ResearchProposal:
        prior = json.dumps(
            list(history[-12:]),
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )[-12_000:]
        prompt = f"""
You are the RD-Agent research proposer for a local paper-only quant assistant.
Return one structured JSON proposal for iteration {iteration}, experiment {experiment}.

Objective: {request.objective}
Universe: {', '.join(request.universe)}
Available daily observations: {len(request.calendar)}
Prior experiment receipts: {prior}

Required JSON object shape (all six keys are required):
{{
  "title": "short hypothesis name",
  "thesis": "falsifiable research claim",
  "operator": "momentum",
  "short_window": 1,
  "long_window": 5,
  "rationale": "why this improves on prior receipts"
}}

Choose exactly one operator from momentum, mean_reversion, low_volatility,
volume_surprise, moving_average_spread. Choose integer windows between 1 and
252; moving_average_spread requires short_window < long_window. Explain a
testable thesis and why this proposal improves on prior receipts. Do not output Python code,
Qlib syntax, trading orders, or any live-trading instruction.
""".strip()
        response = self._backend.build_messages_and_create_chat_completion(
            prompt,
            system_prompt=(
                "Propose bounded, falsifiable paper-research hypotheses. "
                "Respond only with the requested JSON schema."
            ),
            json_mode=True,
            chat_cache_prefix=f"d34:{request.job_id}:{iteration}:{experiment}:",
        )
        return ResearchProposal.model_validate_json(response)


def shifted_target_weights(
    scores: pd.Series,
    *,
    calendar: tuple[str, ...],
    top_k: int,
    risk_degree: float,
) -> pd.DataFrame:
    if (
        scores.empty
        or top_k < 1
        or not 0 < risk_degree <= 1
        or not isinstance(scores.index, pd.MultiIndex)
    ):
        raise D34ResearchError(
            "d34_qlib_scores_invalid", "Qlib factor scores are invalid"
        )
    frame = scores.rename("score").reset_index()
    if "instrument" not in frame.columns or "datetime" not in frame.columns:
        raise D34ResearchError(
            "d34_qlib_scores_invalid", "Qlib factor score index is invalid"
        )
    frame["instrument"] = frame["instrument"].astype(str).str.upper().str.strip()
    frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    frame = frame.dropna(subset=["score"])
    calendar_index = pd.to_datetime(list(calendar), utc=True)
    next_trade = {
        calendar_index[index]: calendar_index[index + 1]
        for index in range(len(calendar_index) - 1)
    }
    rows: list[dict[str, object]] = []
    for signal_ts, day in frame.groupby("datetime", sort=True):
        tradeable_ts = next_trade.get(pd.Timestamp(signal_ts))
        if tradeable_ts is None:
            continue
        ranked = day.sort_values(
            ["score", "instrument"], ascending=[False, True]
        ).head(top_k)
        if ranked.empty:
            continue
        weight = float(risk_degree) / len(ranked)
        rows.extend(
            {
                "tradeable_ts": tradeable_ts,
                "symbol": str(row.instrument),
                "target_weight": weight,
            }
            for row in ranked.itertuples(index=False)
        )
    result = pd.DataFrame(
        rows, columns=["tradeable_ts", "symbol", "target_weight"]
    )
    if result.empty:
        raise D34ResearchError(
            "d34_qlib_scores_empty", "Qlib scores produced no next-day targets"
        )
    return result.sort_values(["tradeable_ts", "symbol"], ignore_index=True)


def _finite_mapping(value: Mapping[str, Any]) -> dict[str, float]:
    result = {str(key): float(item) for key, item in value.items()}
    if any(not math.isfinite(item) or item < 0 for item in result.values()):
        raise D34ResearchError(
            "d34_qlib_position_invalid", "Qlib emitted invalid terminal weights"
        )
    return result


class QlibExperimentRunner:
    def __init__(self) -> None:
        self._provider_uri: Path | None = None

    def _initialize(self, provider_uri: Path) -> None:
        if self._provider_uri == provider_uri:
            return
        import qlib  # noqa: PLC0415

        qlib.init(provider_uri=str(provider_uri), region="us")
        self._provider_uri = provider_uri

    def __call__(
        self,
        request: D34ResearchRequest,
        proposal: ResearchProposal,
        qlib_expression: str,
        experiment_dir: Path,
    ) -> QlibExperimentResult:
        from qlib.contrib.evaluate import backtest_daily  # noqa: PLC0415
        from qlib.contrib.strategy import TopkDropoutStrategy  # noqa: PLC0415
        from qlib.data import D  # noqa: PLC0415

        self._initialize(request.provider_uri)
        start = pd.Timestamp(request.calendar[0]).tz_convert(None)
        end = pd.Timestamp(request.calendar[-1]).tz_convert(None)
        features = D.features(
            list(request.universe),
            [qlib_expression],
            start_time=start,
            end_time=end,
            freq="day",
            disk_cache=True,
        )
        if features.empty:
            raise D34ResearchError(
                "d34_qlib_scores_empty", "Qlib returned no factor observations"
            )
        scores = features.iloc[:, 0].dropna().astype(float).rename("score")
        weights = shifted_target_weights(
            scores,
            calendar=request.calendar,
            top_k=request.top_k,
            risk_degree=RISK_DEGREE,
        )
        strategy = TopkDropoutStrategy(
            signal=scores,
            topk=request.top_k,
            n_drop=request.top_k,
            hold_thresh=0,
            risk_degree=RISK_DEGREE,
            only_tradable=True,
            forbid_all_trade_at_limit=False,
        )
        exchange_kwargs = {
            "deal_price": "$open",
            "open_cost": ONE_WAY_COST,
            "close_cost": ONE_WAY_COST,
            "min_cost": 0,
            "trade_unit": 1,
            "limit_threshold": None,
        }
        report, positions = backtest_daily(
            start_time=start,
            end_time=end,
            strategy=strategy,
            account=request.initial_cash,
            benchmark=request.universe[0],
            exchange_kwargs=exchange_kwargs,
        )
        if report.empty or not {"return", "cost"}.issubset(report.columns):
            raise D34ResearchError(
                "d34_qlib_backtest_empty", "Qlib backtest returned no portfolio report"
            )
        net_returns = (
            pd.to_numeric(report["return"], errors="coerce")
            - pd.to_numeric(report["cost"], errors="coerce")
        ).fillna(0.0)
        observed_dates = tuple(
            pd.Timestamp(value).tz_localize("UTC").isoformat() for value in report.index
        )
        if observed_dates != request.calendar:
            raise D34ResearchError(
                "d34_qlib_calendar_mismatch",
                "Qlib report calendar differs from the canonical snapshot calendar",
            )
        std = float(net_returns.std(ddof=1))
        sharpe = (
            float(net_returns.mean()) / std * math.sqrt(252)
            if math.isfinite(std) and std > 0
            else 0.0
        )
        curve = (1 + net_returns).cumprod()
        drawdown = curve / curve.cummax() - 1
        terminal_date = max(positions)
        terminal_weights = _finite_mapping(
            positions[terminal_date].get_stock_weight_dict(only_stock=False)
        )
        target_path = experiment_dir / "target_weights.parquet"
        weights.to_parquet(target_path, index=False)
        metrics = {
            "sharpe": sharpe,
            "annualized_return": float(net_returns.mean()) * 252,
            "max_drawdown": float(drawdown.min()),
            "mean_daily_cost": float(report["cost"].mean()),
            "observation_count": len(net_returns),
        }
        qlib_config = {
            "contract": "hqa.d34_qlib_config/v1",
            "qlib_commit": QLIB_COMMIT,
            "expression": qlib_expression,
            "proposal": proposal.model_dump(mode="json"),
            "universe": list(request.universe),
            "start_time": request.calendar[0],
            "end_time": request.calendar[-1],
            "top_k": request.top_k,
            "n_drop": request.top_k,
            "risk_degree": RISK_DEGREE,
            "execution_timing": "next_open",
            "exchange": exchange_kwargs,
        }
        (experiment_dir / "qlib_metrics.json").write_text(
            json.dumps(metrics, sort_keys=True) + "\n", encoding="utf-8"
        )
        return QlibExperimentResult(
            score=sharpe,
            daily_returns=tuple(float(value) for value in net_returns),
            return_dates=observed_dates,
            terminal_nav=float(curve.iloc[-1]),
            terminal_weights=terminal_weights,
            target_weights=weights,
            metrics=metrics,
            qlib_config=qlib_config,
        )


class RDAgentCostMeter:
    def __init__(self, reservation_usd: float) -> None:
        self._reservation = reservation_usd
        try:
            from rdagent.oai.backend import litellm as backend_module  # noqa: PLC0415

            self._module: Any | None = backend_module
            self._baseline = float(backend_module.ACC_COST)
        except (ImportError, TypeError, ValueError):
            self._module = None
            self._baseline = 0.0

    def spent(self) -> float:
        if self._module is None:
            return self._reservation
        observed = float(self._module.ACC_COST) - self._baseline
        if not math.isfinite(observed) or observed < 0:
            return self._reservation
        return observed


def run_container_research(
    *, request_path: str | Path, output_root: str | Path
) -> dict[str, object]:
    from rdagent.oai.llm_utils import APIBackend  # noqa: PLC0415

    try:
        document = json.loads(Path(request_path).read_text(encoding="utf-8"))
        request = D34ResearchRequest.model_validate(document)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise D34ResearchError(
            "d34_research_request_unreadable", "research request is unreadable"
        ) from exc
    backend = APIBackend()
    meter = RDAgentCostMeter(request.budget_reservation_usd)

    result = execute_research_request(
        request,
        output_root=output_root,
        proposal_provider=RDAgentProposalProvider(backend),
        experiment_runner=QlibExperimentRunner(),
        cost_provider=meter.spent,
    )
    return {
        "contract": result.contract,
        "job_id": result.job_id,
        "request_digest": result.request_digest,
        "selected_experiment": result.selected_experiment,
        "factor_id": result.factor_id,
        "candidate_code_digest": result.candidate_code_digest,
        "qlib_config_digest": result.qlib_config_digest,
        "target_weights_digest": result.target_weights_digest,
        "qlib_receipt_digest": result.qlib_receipt_digest,
        "budget_spent_usd": result.budget_spent_usd,
        "output_dir": str(result.output_dir),
        "factor_path": str(result.factor_path),
        "target_weights_path": str(result.target_weights_path),
        "qlib_receipt_path": str(result.qlib_receipt_path),
        "rdagent_commit": RDAGENT_COMMIT,
        "qlib_commit": QLIB_COMMIT,
    }


__all__ = [
    "QLIB_COMMIT",
    "RDAGENT_COMMIT",
    "QlibExperimentRunner",
    "RDAgentCostMeter",
    "RDAgentProposalProvider",
    "run_container_research",
    "shifted_target_weights",
]
