"""Concrete RD-Agent proposal and Qlib experiment adapters used in Docker."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

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


class RegisteredFactorVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: str = Field(pattern=r"^hqa\.registered_factor_verification_request/v1$")
    job_id: str = Field(pattern=r"^job-[A-Za-z0-9._:-]{8,200}$")
    run_id: str = Field(pattern=r"^attempt-[A-Za-z0-9._:-]{8,200}$")
    factor_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = Field(pattern=r"^snapshot-[A-Za-z0-9._:-]{8,200}$")
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_uri: Path
    universe: tuple[str, ...]
    calendar: tuple[str, ...]
    qlib_expression: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(default=1, ge=1, le=64)
    initial_cash: float = Field(default=100_000, gt=0)

    @property
    def request_digest(self) -> str:
        from quant_system.d34.research_request import digest_document  # noqa: PLC0415

        return digest_document(self.model_dump(mode="json"))


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

Required JSON object shape:
{{
  "title": "short hypothesis name",
  "thesis": "falsifiable research claim that cites prior receipts when any exist",
  "operator": "composed",
  "short_window": 0,
  "long_window": 20,
  "qlib_expr": "$close/Ref($close,20)-1",
  "rationale": "why this expression improves on prior receipts"
}}

Prefer operator=composed and a whitelist Qlib expression using only
$close/$open/$high/$low/$volume and Ref, Mean, Std, Sum, Max, Min, Delta,
EMA, Rank, Abs, Log, Sign, plus + - * /. long_window must be 2..252.
Rank(expression, window) is a time-series percentile over that window,
not a cross-sectional rank. Rank(expression, 1) is constant and is not
a useful selection signal; the portfolio already ranks scores across symbols.
short_window is momentum skip-N: 0 means no skip; 1 means skip one day
(Ref($close,1)/Ref($close,1+window)-1). Do not use 1 as a sentinel for
"unset". moving_average_spread requires short_window >= 1 and
short_window < long_window. Depth <= 6. If you cannot form a valid
composed expression, you may fall back to operator in momentum,
mean_reversion, low_volatility, volume_surprise, moving_average_spread
and omit qlib_expr. Explain a testable thesis. Do not output Python,
trading orders, or live instructions.
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
            # Qlib reports gross traded value / previous account NAV per day.
            # Sum the exact return window; do not annualize or divide by two.
            "turnover": _period_turnover(report),
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


def _period_turnover(report: pd.DataFrame) -> float | None:
    """Preserve unknown turnover instead of pandas' implicit missing-day skip."""
    if report.empty or "turnover" not in report.columns:
        return None
    values = report["turnover"].tolist()
    if any(
        type(value) not in {int, float} or not math.isfinite(value) or value < 0
        for value in values
    ):
        return None
    try:
        total = math.fsum(values)
    except OverflowError:
        return None
    return total if math.isfinite(total) else None


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

    def metering_alert(self, *, spent: float) -> str | None:
        if self._module is None:
            return None
        if spent == 0:
            return "d34_budget_metering_failed"
        return None


def run_registered_factor_verification(
    *,
    request_path: str | Path,
    output_root: str | Path,
) -> dict[str, object]:
    """Run one registered expression through Qlib without invoking an LLM."""

    request = RegisteredFactorVerificationRequest.model_validate_json(
        Path(request_path).read_text(encoding="utf-8")
    )
    from quant_system.d34.research_driver import (  # noqa: PLC0415
        D34ResearchRequest,
        ResearchProposal,
    )
    from quant_system.d34.research_request import (  # noqa: PLC0415
        LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
        LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
        digest_document,
    )

    research_request = D34ResearchRequest(
        contract="hqa.d34_research_request/v2",
        job_id=request.job_id,
        run_id=request.run_id,
        resource_envelope_id=LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
        resource_policy_digest=LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
        snapshot_id=request.snapshot_id,
        snapshot_digest=request.snapshot_digest,
        snapshot_source="futu",
        provider_uri=request.provider_uri,
        universe=request.universe,
        calendar=request.calendar,
        max_iterations=3,
        experiments_per_iteration=3,
        top_k=request.top_k,
        initial_cash=request.initial_cash,
        budget_reservation_usd=10,
        objective=f"Verify registered factor {request.factor_id}",
    )
    proposal = ResearchProposal(
        title=f"Registered {request.factor_id}",
        thesis="Verify the exact registered factor through the canonical dual-engine path.",
        operator="composed",
        short_window=0,
        long_window=20,
        qlib_expr=request.qlib_expression,
        rationale="No LLM proposal; source and expression are fixed by the registered factor map.",
    )
    root = Path(output_root) / f"registered-{request.request_digest[:32]}"
    experiment = root / "qlib"
    if root.exists():
        receipt_path = root / "qlib_receipt.json"
        target_path = root / "target_weights.parquet"
        if not receipt_path.is_file() or not target_path.is_file():
            raise D34ResearchError(
                "registered_factor_verification_collision",
                "existing registered-factor evidence is incomplete",
            )
    else:
        experiment.mkdir(parents=True)
        result = QlibExperimentRunner()(
            research_request,
            proposal,
            request.qlib_expression,
            experiment,
        )
        target_path = experiment / "target_weights.parquet"
        target_digest = hashlib.sha256(target_path.read_bytes()).hexdigest()
        qlib_config = dict(result.qlib_config)
        receipt_body = {
            "contract": "hqa.d34_engine_receipt/v1",
            "engine": "qlib",
            "job_id": request.job_id,
            "run_id": request.run_id,
            "factor_id": request.factor_id,
            "source_digest": request.source_digest,
            "snapshot_id": request.snapshot_id,
            "snapshot_digest": request.snapshot_digest,
            "universe_digest": digest_document(list(request.universe)),
            "calendar_digest": digest_document(list(request.calendar)),
            "target_weights_digest": target_digest,
            "daily_returns": list(result.daily_returns),
            "return_dates": list(result.return_dates),
            "terminal_nav": result.terminal_nav,
            "terminal_weights": dict(result.terminal_weights),
            "metrics": dict(result.metrics),
            "qlib_config": qlib_config,
            "qlib_config_digest": digest_document(qlib_config),
        }
        receipt_digest = digest_document(receipt_body)
        receipt_path = root / "qlib_receipt.json"
        receipt_path.write_text(
            json.dumps(
                {**receipt_body, "receipt_digest": receipt_digest},
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        target_path.replace(root / "target_weights.parquet")
        target_path = root / "target_weights.parquet"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    return {
        "contract": "hqa.registered_factor_qlib_result/v1",
        "job_id": request.job_id,
        "run_id": request.run_id,
        "request_digest": request.request_digest,
        "qlib_receipt_path": str(receipt_path),
        "qlib_receipt_digest": str(receipt["receipt_digest"]),
        "target_weights_path": str(target_path),
        "target_weights_digest": hashlib.sha256(target_path.read_bytes()).hexdigest(),
    }

def run_container_research(
    *, request_path: str | Path, output_root: str | Path
) -> dict[str, object]:
    try:
        document = json.loads(Path(request_path).read_text(encoding="utf-8"))
        request = D34ResearchRequest.model_validate(document)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise D34ResearchError(
            "d34_research_request_unreadable", "research request is unreadable"
        ) from exc
    backend = None
    meter = None
    if request.formula is None:
        from rdagent.oai.llm_utils import APIBackend  # noqa: PLC0415

        backend = APIBackend()
        meter = RDAgentCostMeter(request.budget_reservation_usd)

    result = execute_research_request(
        request,
        output_root=output_root,
        proposal_provider=RDAgentProposalProvider(backend),
        experiment_runner=QlibExperimentRunner(),
        cost_provider=meter.spent if meter is not None else lambda: 0.0,
    )
    payload: dict[str, object] = {
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
        "experiment_trials_path": str(result.experiment_trials_path),
        "experiment_trials_digest": result.experiment_trials_digest,
        "experiment_trials_file_digest": result.experiment_trials_file_digest,
        "successful_experiment_count": result.successful_experiment_count,
        "rdagent_commit": RDAGENT_COMMIT,
        "qlib_commit": QLIB_COMMIT,
    }
    alert = (
        meter.metering_alert(spent=float(result.budget_spent_usd))
        if meter is not None else None
    )
    if alert is not None:
        payload["budget_metering"] = alert
        receipt_path = result.output_dir / "research_receipt.json"
        try:
            document = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            document = None
        if isinstance(document, dict):
            document["budget_metering"] = alert
            receipt_path.write_text(
                json.dumps(document, sort_keys=True) + "\n", encoding="utf-8"
            )
    return payload


__all__ = [
    "QLIB_COMMIT",
    "RDAGENT_COMMIT",
    "QlibExperimentRunner",
    "RDAgentCostMeter",
    "RDAgentProposalProvider",
    "run_container_research",
    "shifted_target_weights",
]
