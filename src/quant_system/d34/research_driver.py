"""Durable RD-Agent/Qlib research loop for one D-34 experiment job.

RD-Agent selects and iterates a bounded factor specification.  The specification
is rendered deterministically into both a Qlib expression and a digest-bound
Platform ``BaseFactor``.  Qlib owns research calculation/backtesting; Platform
later consumes only the emitted target weights for an independent execution
replay.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_system.d34.qlib_expr import QlibExprError, compile_qlib_expr
from quant_system.options.seller_score import is_us_market_session

RESEARCH_REQUEST_CONTRACT = "hqa.d34_research_request/v2"
RESEARCH_RESULT_CONTRACT = "hqa.d34_research_result/v2"
ENGINE_RECEIPT_CONTRACT = "hqa.d34_engine_receipt/v1"
EXPERIMENT_TRIAL_BATCH_CONTRACT = "hqa.d34_experiment_trial_batch/v1"
D34_TARGET_GROSS_EXPOSURE = 0.99

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{0,31}$")
_FACTOR_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class D34ResearchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def validate_xnys_calendar(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Return one strict, unique, increasing XNYS session sequence."""

    raw_values = tuple(values)
    try:
        calendar = pd.to_datetime(list(raw_values), utc=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("d34_research_calendar_invalid") from exc
    if (
        len(calendar) < 3
        or calendar.has_duplicates
        or not calendar.is_monotonic_increasing
        or any(
            pd.Timestamp(value).isoformat() != raw
            or not is_us_market_session(pd.Timestamp(value).date())
            for value, raw in zip(calendar, raw_values, strict=True)
        )
    ):
        raise ValueError("d34_research_calendar_invalid")
    return raw_values


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_once_atomic(path: Path, payload: bytes) -> None:
    if path.is_file():
        if path.read_bytes() == payload:
            return
        raise D34ResearchError(
            "d34_research_collision",
            "existing experiment trial batch differs from this replay",
        )
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    if path.is_file():
        temporary.unlink(missing_ok=True)
        if path.read_bytes() == payload:
            return
        raise D34ResearchError(
            "d34_research_collision",
            "existing experiment trial batch differs from this replay",
        )
    temporary.replace(path)


def _write_experiment_trial_attempt(
    *,
    root: Path,
    request: D34ResearchRequest,
    experiment_id: str,
    status: str,
    subject: str | None = None,
    proposal_digest: str | None = None,
    experiment_receipt_digest: str | None = None,
    daily_returns: tuple[float, ...] | None = None,
    evaluation_contract: Mapping[str, object] | None = None,
    failure_type: str | None = None,
    failure_reason: str | None = None,
) -> Path:
    body: dict[str, object] = {
        "contract": "hqa.d34_experiment_trial_attempt/v1",
        "job_id": request.job_id,
        "request_digest": request.request_digest,
        "universe": list(request.universe),
        "universe_digest": _digest(list(request.universe)),
        "calendar_digest": _digest(list(request.calendar)),
        "return_dates": list(request.calendar),
        "experiment_id": experiment_id,
        "status": status,
    }
    if status == "succeeded":
        body.update(
            {
                "subject": str(subject or ""),
                "proposal_digest": str(proposal_digest or ""),
                "experiment_receipt_digest": str(
                    experiment_receipt_digest or ""
                ),
                "daily_returns": [float(value) for value in daily_returns or ()],
            }
        )
        if evaluation_contract is not None:
            body["evaluation_contract"] = dict(evaluation_contract)
    else:
        body["failure_type"] = failure_type
        body["failure_reason"] = failure_reason
    receipt_digest = _digest(body)
    path = root / f"{experiment_id}.json"
    root.mkdir(parents=True, exist_ok=True)
    _write_once_atomic(
        path,
        _canonical_json({**body, "receipt_digest": receipt_digest}) + b"\n",
    )
    return path


def _experiment_evaluation_contract(request, outcome, experiment_runner):
    """Persist this experiment's own economics, never the selected sibling's.

    The runner's original combined open/close cost is retained verbatim; this
    recorder does not invent a commission/slippage decomposition.
    """
    config = json.loads(json.dumps(dict(outcome.qlib_config), allow_nan=False))
    try:
        source_path = inspect.getsourcefile(experiment_runner)
    except TypeError:
        source_path = None
    if source_path is None and callable(experiment_runner):
        try:
            source_path = inspect.getsourcefile(experiment_runner.__call__)
        except TypeError:
            source_path = None
    return {
        "schema": "hqa.d34_experiment_evaluation/v1",
        "return_definition": "net_total_return",
        "frequency": "daily",
        "initial_cash": request.initial_cash,
        "request_digest": request.request_digest,
        "snapshot_id": request.snapshot_id,
        "snapshot_digest": request.snapshot_digest,
        "snapshot_source": request.snapshot_source,
        "universe_digest": _digest(list(request.universe)),
        "calendar_digest": _digest(list(request.calendar)),
        "qlib_config": config,
        "qlib_config_digest": _digest(config),
        "implementation": {
            "producer_sha256": _file_digest(Path(__file__)),
            "runner_source_sha256": _file_digest(Path(source_path)) if source_path else None,
        },
    }


class D34ResearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract: Literal[RESEARCH_REQUEST_CONTRACT]
    job_id: str = Field(pattern=r"^job-[A-Za-z0-9._:-]{8,200}$")
    run_id: str = Field(pattern=r"^attempt-[A-Za-z0-9._:-]{8,200}$")
    resource_envelope_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    resource_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_id: str = Field(pattern=r"^snapshot-[A-Za-z0-9._:-]{8,200}$")
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_source: Literal["futu"]
    provider_uri: Path
    universe: tuple[str, ...]
    calendar: tuple[str, ...]
    max_iterations: int = Field(default=3, ge=3, le=3)
    experiments_per_iteration: int = Field(default=3, ge=3, le=3)
    top_k: int = Field(default=1, ge=1, le=100)
    initial_cash: float = Field(default=100_000, gt=0, le=1_000_000_000)
    budget_reservation_usd: float = Field(default=10, ge=0, le=100_000)
    objective: str = Field(min_length=1, max_length=10_000)
    formula: str | None = Field(default=None, min_length=1, max_length=400)

    @model_validator(mode="after")
    def validate_contract_inputs(self) -> D34ResearchRequest:
        symbols = tuple(value.strip().upper() for value in self.universe)
        if (
            symbols != self.universe
            or not 1 <= len(symbols) <= 64
            or len(set(symbols)) != len(symbols)
            or any(_SYMBOL_RE.fullmatch(value) is None for value in symbols)
            or self.top_k > len(symbols)
            or not self.provider_uri.is_absolute()
            or not self.provider_uri.is_dir()
            or self.budget_reservation_usd != 10
        ):
            raise ValueError("d34_research_request_invalid")
        validate_xnys_calendar(self.calendar)
        if self.formula is not None:
            compile_qlib_expr(self.formula)
        return self

    @property
    def experiment_count(self) -> int:
        if self.formula is not None:
            return 1
        return self.max_iterations * self.experiments_per_iteration

    @property
    def request_digest(self) -> str:
        return _digest(self.model_dump(mode="json", exclude_none=True))


class ResearchProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=200)
    thesis: str = Field(min_length=1, max_length=2_000)
    operator: Literal[
        "momentum",
        "mean_reversion",
        "low_volatility",
        "volume_surprise",
        "moving_average_spread",
        "composed",
    ]
    short_window: int = Field(
        default=0,
        ge=0,
        le=252,
        description=(
            "Momentum skip-N; 0 means no skip. "
            "moving_average_spread requires a short mean of at least 1."
        ),
    )
    long_window: int = Field(ge=2, le=252)
    rationale: str = Field(min_length=1, max_length=2_000)
    qlib_expr: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def validate_windows(self) -> ResearchProposal:
        if self.operator == "composed":
            if self.qlib_expr is None or not self.qlib_expr.strip():
                raise ValueError("d34_composed_expr_required")
            try:
                compile_qlib_expr(self.qlib_expr)
            except QlibExprError as exc:
                raise ValueError(exc.code) from exc
            return self
        if self.operator == "moving_average_spread" and (
            self.short_window < 1 or self.short_window >= self.long_window
        ):
            raise ValueError("d34_factor_window_invalid")
        return self


@dataclass(frozen=True)
class QlibExperimentResult:
    score: float
    daily_returns: tuple[float, ...]
    return_dates: tuple[str, ...]
    terminal_nav: float
    terminal_weights: Mapping[str, float]
    target_weights: pd.DataFrame
    metrics: Mapping[str, object]
    qlib_config: Mapping[str, object]


@dataclass(frozen=True)
class D34ResearchResult:
    contract: str
    job_id: str
    request_digest: str
    selected_experiment: str
    factor_id: str
    candidate_code_digest: str
    qlib_config_digest: str
    target_weights_digest: str
    qlib_receipt_digest: str
    budget_spent_usd: float
    output_dir: Path
    factor_path: Path
    target_weights_path: Path
    qlib_receipt_path: Path
    experiment_trials_path: Path
    experiment_trials_digest: str
    experiment_trials_file_digest: str
    successful_experiment_count: int


HUNG_MOMENTUM_CANDIDATE_ID = "artifact-d489583fb04bdc04"
READ_ONLY_DSR_CANDIDATE_ID = "artifact-a604ad9ad2792c32"
HUNG_MOMENTUM_CORRECTION_NOTE = (
    "更正注记：主人已知情。本候选实际运行为普通 21 日动量"
    "（$close/Ref($close,21)-1）；论题里的 short_window/skip-N 当时未被渲染器 honor。"
)
HISTORICAL_DSR_REVIEW_NOTES = {
    HUNG_MOMENTUM_CANDIDATE_ID: (
        "历史复核注记（2026-08-20）：原作业 4/4 个成功 experiment 的证据清单 "
        "SHA-256=951d538efa546fb9e54c0f953cc314ca506d4911afd14b7c3c3b42810444092f；"
        "以绑定的 Platform replay 750 日收益、n_trials=4 和修正后的 plain kurtosis "
        "重算 DSR=0.840302 < 0.95。此结论只纠正历史准入口径；按主人授权保留已挂状态"
        "与既有纸面成交，不自动解挂。"
    ),
    READ_ONLY_DSR_CANDIDATE_ID: (
        "历史复核注记（2026-08-20）：原作业 7/9 个成功 experiment 的证据清单 "
        "SHA-256=2fbe5eb539785bf2dcf7f02281baa963a20771365991f91160c1d3b052d6f123；"
        "以绑定的 Platform replay 752 日收益、n_trials=7 和修正后的 plain kurtosis "
        "重算 DSR=0.852474 < 0.95。继续保留为只读 verified candidate，不挂。"
    ),
}


def annotate_hung_momentum_candidates(
    candidates: list[dict[str, object]] | tuple[dict[str, object], ...],
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for item in candidates:
        if not isinstance(item, dict):
            annotated.append(item)
            continue
        candidate_id = str(item.get("candidate_id") or "")
        if candidate_id not in HISTORICAL_DSR_REVIEW_NOTES:
            annotated.append(item)
            continue
        row = dict(item)
        notes = [str(row.get("description_note") or "").strip()]
        if candidate_id == HUNG_MOMENTUM_CANDIDATE_ID:
            notes.append(HUNG_MOMENTUM_CORRECTION_NOTE)
        notes.append(HISTORICAL_DSR_REVIEW_NOTES[candidate_id])
        row["description_note"] = " ".join(
            dict.fromkeys(note for note in notes if note)
        )
        annotated.append(row)
    return annotated


ProposalProvider = Callable[
    [D34ResearchRequest, int, int, tuple[dict[str, object], ...]], ResearchProposal
]
ExperimentRunner = Callable[
    [D34ResearchRequest, ResearchProposal, str, Path], QlibExperimentResult
]
CostProvider = Callable[[], float]


def qlib_expression(proposal: ResearchProposal) -> str:
    if proposal.operator == "composed":
        assert proposal.qlib_expr is not None
        return compile_qlib_expr(proposal.qlib_expr).qlib
    window = proposal.long_window
    skip = proposal.short_window
    if proposal.operator == "momentum" and skip >= 1:
        return f"Ref($close,{skip})/Ref($close,{skip + window})-1"
    expressions = {
        "momentum": f"$close/Ref($close,{window})-1",
        "mean_reversion": f"1-$close/Ref($close,{window})",
        "low_volatility": f"-Std($close/Ref($close,1)-1,{window})",
        "volume_surprise": f"$volume/Mean($volume,{window})-1",
        "moving_average_spread": (
            f"Mean($close,{proposal.short_window})/Mean($close,{window})-1"
        ),
    }
    return expressions[proposal.operator]


def factor_display_name_zh(proposal: ResearchProposal) -> str:
    """Return a deterministic Chinese name from the closed proposal schema."""

    window = proposal.long_window
    if proposal.operator == "momentum":
        if proposal.short_window >= 1:
            return f"跳过最近 {proposal.short_window} 日的 {window} 日横截面动量"
        return f"{window} 日横截面动量"
    if proposal.operator == "mean_reversion":
        return f"{window} 日均值回归"
    if proposal.operator == "low_volatility":
        return f"{window} 日低波动"
    if proposal.operator == "volume_surprise":
        return f"{window} 日成交量异动"
    if proposal.operator == "moving_average_spread":
        return f"{proposal.short_window} 日 / {window} 日均线差"
    return f"{window} 日复合选股因子"


def render_factor_source(*, proposal: ResearchProposal, factor_id: str) -> tuple[str, str]:
    if _FACTOR_ID_RE.fullmatch(factor_id) is None:
        raise D34ResearchError("d34_factor_id_invalid", "generated factor id is invalid")
    window = proposal.long_window
    if proposal.operator == "composed":
        assert proposal.qlib_expr is not None
        compiled = compile_qlib_expr(proposal.qlib_expr)
        compute = f"        return {compiled.pandas_body}"
        source = (
            "from __future__ import annotations\n\n"
            "import numpy as np\n"
            "import pandas as pd\n\n"
            "from quant_system.factors.base import BaseFactor\n\n\n"
            "class D34GeneratedFactor(BaseFactor):\n"
            f"    factor_id = {factor_id!r}\n"
            f"    factor_name = {proposal.title!r}\n"
            f"    display_name_zh = {factor_display_name_zh(proposal)!r}\n"
            "    factor_version = \"1.0.0\"\n"
            f"    default_lookback = {compiled.lookback}\n"
            "    direction = \"higher_is_better\"\n"
            f"    description = {proposal.thesis!r}\n\n"
            "    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:\n"
            f"{compute}\n\n\n"
            "D34_FACTOR = D34GeneratedFactor\n"
        )
        return source, hashlib.sha256(source.encode("utf-8")).hexdigest()
    compute = {
        "momentum": (
            (
                "        return group[\"close\"].transform(\n"
                f"            lambda values: values.shift({proposal.short_window}) "
                f"/ values.shift({proposal.short_window + window}) - 1\n"
                "        )"
            )
            if proposal.short_window >= 1
            else (
                "        return group[\"close\"].transform(\n"
                "            lambda values: values.pct_change(self.lookback)\n"
                "        )"
            )
        ),
        "mean_reversion": (
            "        return -group[\"close\"].transform(\n"
            "            lambda values: values.pct_change(self.lookback)\n"
            "        )"
        ),
        "low_volatility": (
            "        returns = group[\"close\"].transform(lambda values: values.pct_change())\n"
            "        volatility = returns.groupby(frame[\"symbol\"], sort=False).transform(\n"
            "            lambda values: values.rolling(\n"
            "                self.lookback, min_periods=self.lookback\n"
            "            ).std(ddof=0)\n"
            "        )\n"
            "        return -volatility"
        ),
        "volume_surprise": (
            "        volume_mean = group[\"volume\"].transform(\n"
            "            lambda values: values.rolling(\n"
            "                self.lookback, min_periods=self.lookback\n"
            "            ).mean()\n"
            "        )\n"
            "        return frame[\"volume\"] / volume_mean - 1"
        ),
        "moving_average_spread": (
            "        short_mean = group[\"close\"].transform(\n"
            f"            lambda values: values.rolling({proposal.short_window}, "
            f"min_periods={proposal.short_window}).mean()\n"
            "        )\n"
            "        long_mean = group[\"close\"].transform(\n"
            "            lambda values: values.rolling(\n"
            "                self.lookback, min_periods=self.lookback\n"
            "            ).mean()\n"
            "        )\n"
            "        return short_mean / long_mean - 1"
        ),
    }[proposal.operator]
    source = (
        "from __future__ import annotations\n\n"
        "import pandas as pd\n\n"
        "from quant_system.factors.base import BaseFactor\n\n\n"
        "class D34GeneratedFactor(BaseFactor):\n"
        f"    factor_id = {factor_id!r}\n"
        f"    factor_name = {proposal.title!r}\n"
        f"    display_name_zh = {factor_display_name_zh(proposal)!r}\n"
        "    factor_version = \"1.0.0\"\n"
        f"    default_lookback = {window}\n"
        "    direction = \"higher_is_better\"\n"
        f"    description = {proposal.thesis!r}\n\n"
        "    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:\n"
        "        group = frame.groupby(\"symbol\", sort=False)\n"
        f"{compute}\n\n\n"
        "D34_FACTOR = D34GeneratedFactor\n"
    )
    return source, hashlib.sha256(source.encode("utf-8")).hexdigest()


def _validate_experiment(result: QlibExperimentResult, request: D34ResearchRequest) -> None:
    required_weights = {"tradeable_ts", "symbol", "target_weight"}
    weights = result.target_weights
    if (
        not math.isfinite(float(result.score))
        or not math.isfinite(float(result.terminal_nav))
        or result.terminal_nav <= 0
        or len(result.daily_returns) != len(result.return_dates)
        or tuple(result.return_dates) != request.calendar
        or not result.daily_returns
        or any(not math.isfinite(float(value)) for value in result.daily_returns)
        or any(
            _SYMBOL_RE.fullmatch(str(symbol)) is None
            or not math.isfinite(float(weight))
            or not 0 <= float(weight) <= 1
            for symbol, weight in result.terminal_weights.items()
        )
        or weights.empty
        or not required_weights.issubset(weights.columns)
    ):
        raise D34ResearchError(
            "d34_qlib_experiment_invalid", "Qlib experiment emitted invalid evidence"
        )


def _result_from_manifest(output_dir: Path, document: dict[str, object]) -> D34ResearchResult:
    factor_path = output_dir / str(document["factor_file"])
    target_path = output_dir / str(document["target_weights_file"])
    qlib_path = output_dir / str(document["qlib_receipt_file"])
    experiment_trials_path = Path(str(document["experiment_trials_path"]))
    if not experiment_trials_path.is_absolute():
        experiment_trials_path = output_dir / experiment_trials_path
    expected = {
        factor_path: str(document["candidate_code_digest"]),
        target_path: str(document["target_weights_digest"]),
        qlib_path: str(document["qlib_receipt_file_digest"]),
        experiment_trials_path: str(document["experiment_trials_file_digest"]),
    }
    if any(not path.is_file() or _file_digest(path) != digest for path, digest in expected.items()):
        raise D34ResearchError(
            "d34_research_collision", "existing research result failed digest verification"
        )
    return D34ResearchResult(
        contract=str(document["contract"]),
        job_id=str(document["job_id"]),
        request_digest=str(document["request_digest"]),
        selected_experiment=str(document["selected_experiment"]),
        factor_id=str(document["factor_id"]),
        candidate_code_digest=str(document["candidate_code_digest"]),
        qlib_config_digest=str(document["qlib_config_digest"]),
        target_weights_digest=str(document["target_weights_digest"]),
        qlib_receipt_digest=str(document["qlib_receipt_digest"]),
        budget_spent_usd=float(document["budget_spent_usd"]),
        output_dir=output_dir,
        factor_path=factor_path,
        target_weights_path=target_path,
        qlib_receipt_path=qlib_path,
        experiment_trials_path=experiment_trials_path,
        experiment_trials_digest=str(document["experiment_trials_digest"]),
        experiment_trials_file_digest=str(document["experiment_trials_file_digest"]),
        successful_experiment_count=int(document["successful_experiment_count"]),
    )


def _load_existing(output_dir: Path, request: D34ResearchRequest) -> D34ResearchResult:
    try:
        document = json.loads((output_dir / "research_receipt.json").read_text("utf-8"))
        result = _result_from_manifest(output_dir, document)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise D34ResearchError(
            "d34_research_collision", "existing research result is unreadable"
        ) from exc
    if (
        result.contract != RESEARCH_RESULT_CONTRACT
        or result.job_id != request.job_id
        or result.request_digest != request.request_digest
    ):
        raise D34ResearchError(
            "d34_research_collision", "existing research result belongs to another input"
        )
    return result


def execute_research_request(
    request: D34ResearchRequest,
    *,
    output_root: str | Path,
    proposal_provider: ProposalProvider,
    experiment_runner: ExperimentRunner,
    cost_provider: CostProvider,
    trials_root: str | Path | None = None,
) -> D34ResearchResult:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    output_dir = root / f"research-{request.request_digest[:32]}"
    if output_dir.exists():
        return _load_existing(output_dir, request)

    temp = Path(tempfile.mkdtemp(prefix=".research-", dir=root))
    attempt_root = (
        root / f"experiment-trial-attempts-{request.request_digest[:32]}"
    )
    history: list[dict[str, object]] = []
    successes: list[tuple[str, ResearchProposal, QlibExperimentResult]] = []
    experiment_trials: list[dict[str, object]] = []
    fixed_proposal = None
    if request.formula is not None:
        compiled = compile_qlib_expr(request.formula)
        fixed_proposal = ResearchProposal(
            title="给定公式复现",
            thesis=request.objective[:2_000],
            operator="composed",
            long_window=min(252, max(2, compiled.lookback)),
            qlib_expr=request.formula,
            rationale="Reproduce the supplied expression without hypothesis search.",
        )
    iterations = 1 if fixed_proposal else request.max_iterations
    experiments = 1 if fixed_proposal else request.experiments_per_iteration
    try:
        for iteration in range(1, iterations + 1):
            for experiment in range(1, experiments + 1):
                experiment_id = f"iteration-{iteration:02d}-experiment-{experiment:02d}"
                experiment_dir = temp / "experiments" / experiment_id
                experiment_dir.mkdir(parents=True)
                proposal: ResearchProposal | None = None
                try:
                    proposal = fixed_proposal or proposal_provider(
                        request, iteration, experiment, tuple(history)
                    )
                    expression = qlib_expression(proposal)
                    outcome = experiment_runner(
                        request, proposal, expression, experiment_dir
                    )
                    _validate_experiment(outcome, request)
                except Exception as exc:  # noqa: BLE001 - external Qlib boundary
                    failure = {
                        "experiment_id": experiment_id,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:2_000],
                    }
                    if proposal is not None:
                        failure["proposal"] = proposal.model_dump(mode="json")
                    (experiment_dir / "failure.json").write_bytes(
                        _canonical_json(failure) + b"\n"
                    )
                    _write_experiment_trial_attempt(
                        root=attempt_root,
                        request=request,
                        experiment_id=experiment_id,
                        status="failed",
                        failure_type=type(exc).__name__,
                        failure_reason=str(exc)[:2_000],
                    )
                    history.append(failure)
                    continue
                observation = {
                    "experiment_id": experiment_id,
                    "status": "succeeded",
                    "score": float(outcome.score),
                    "metrics": dict(outcome.metrics),
                    "proposal": proposal.model_dump(mode="json"),
                    "qlib_expression": expression,
                    "returns_digest": _digest({
                        "values": [float(value) for value in outcome.daily_returns],
                        "dates": list(outcome.return_dates),
                    }),
                    "return_dates_digest": _digest(list(outcome.return_dates)),
                    "evaluation_contract": _experiment_evaluation_contract(
                        request, outcome, experiment_runner
                    ),
                }
                experiment_receipt_path = experiment_dir / "receipt.json"
                experiment_receipt_path.write_bytes(
                    _canonical_json(observation) + b"\n"
                )
                proposal_digest = _digest(proposal.model_dump(mode="json"))
                experiment_receipt_digest = _file_digest(experiment_receipt_path)
                _write_experiment_trial_attempt(
                    root=attempt_root,
                    request=request,
                    experiment_id=experiment_id,
                    status="succeeded",
                    subject=f"{proposal.operator}:{experiment_id}",
                    proposal_digest=proposal_digest,
                    experiment_receipt_digest=experiment_receipt_digest,
                    daily_returns=outcome.daily_returns,
                    evaluation_contract=observation["evaluation_contract"],
                )
                # R1: each Qlib experiment is one trial for DSR admission.
                from quant_system.config.settings import load_settings
                from quant_system.research.trials import (
                    ResearchTrial,
                    TrialsLedger,
                )

                ledger_root = (
                    Path(trials_root)
                    if trials_root is not None
                    else Path(load_settings().data.data_dir) / "trials"
                )
                run_id = f"{request.job_id}:{experiment_id}"
                trial = ResearchTrial.record(
                    kind="d34_experiment",
                    subject=f"{proposal.operator}:{experiment_id}",
                    universe=request.universe,
                    daily_returns=outcome.daily_returns,
                    window_start=outcome.return_dates[0][:10],
                    window_end=outcome.return_dates[-1][:10],
                    source=run_id,
                    metadata={
                        "run_id": run_id,
                        "job_id": request.job_id,
                        "request_digest": request.request_digest,
                        "experiment_id": experiment_id,
                        "attempt_status": "succeeded",
                        "proposal_digest": proposal_digest,
                        "experiment_receipt_digest": experiment_receipt_digest,
                    },
                )
                TrialsLedger(ledger_root).append(trial)
                experiment_trials.append(
                    {
                        "experiment_id": experiment_id,
                        "subject": trial.subject,
                        "proposal_digest": proposal_digest,
                        "experiment_receipt_digest": experiment_receipt_digest,
                        "daily_returns": [
                            float(value) for value in outcome.daily_returns
                        ],
                        "evaluation_contract": observation["evaluation_contract"],
                    }
                )
                history.append(observation)
                successes.append((experiment_id, proposal, outcome))
        if not successes:
            raise D34ResearchError(
                "d34_research_no_success", "all bounded Qlib experiments failed"
            )
        selected_id, selected_proposal, selected = max(
            successes, key=lambda value: (value[2].score, value[0])
        )
        universe_digest = _digest(list(request.universe))
        calendar_digest = _digest(list(request.calendar))
        experiment_trials_body = {
            "contract": EXPERIMENT_TRIAL_BATCH_CONTRACT,
            "job_id": request.job_id,
            "request_digest": request.request_digest,
            "universe": list(request.universe),
            "universe_digest": universe_digest,
            "calendar_digest": calendar_digest,
            "return_dates": list(request.calendar),
            "experiment_count": len(history),
            "successful_experiment_count": len(experiment_trials),
            "attempts": [
                {
                    "experiment_id": str(item["experiment_id"]),
                    "status": str(item["status"]),
                    "attempt_receipt_digest": _file_digest(
                        attempt_root / f"{item['experiment_id']}.json"
                    ),
                }
                for item in history
            ],
            "selected_experiment": selected_id,
            "experiments": experiment_trials,
        }
        experiment_trials_digest = _digest(experiment_trials_body)
        experiment_trials_path = (
            root / f"experiment-trials-{request.request_digest[:32]}.json"
        )
        _write_once_atomic(
            experiment_trials_path,
            _canonical_json(
                {
                    **experiment_trials_body,
                    "receipt_digest": experiment_trials_digest,
                }
            )
            + b"\n",
        )
        factor_id = "d34_" + hashlib.sha256(
            f"{request.job_id}:{selected_id}".encode()
        ).hexdigest()[:24]
        factor_source, factor_digest = render_factor_source(
            proposal=selected_proposal, factor_id=factor_id
        )
        factor_path = temp / "candidate_factor.py"
        factor_path.write_text(factor_source, encoding="utf-8")
        target_path = temp / "target_weights.parquet"
        selected.target_weights.to_parquet(target_path, index=False)
        target_digest = _file_digest(target_path)
        qlib_config = dict(selected.qlib_config)
        qlib_config_digest = _digest(qlib_config)
        research_summary_digest = _digest(
            selected_proposal.model_dump(mode="json")
        )
        budget_spent = float(cost_provider())
        if (
            not math.isfinite(budget_spent)
            or budget_spent < 0
            or budget_spent > request.budget_reservation_usd
        ):
            raise D34ResearchError(
                "d34_research_budget_invalid", "RD-Agent cost exceeded its job reservation"
            )
        receipt_body = {
            "contract": ENGINE_RECEIPT_CONTRACT,
            "engine": "qlib",
            "job_id": request.job_id,
            "run_id": request.run_id,
            "factor_id": factor_id,
            "candidate_code_digest": factor_digest,
            "snapshot_id": request.snapshot_id,
            "snapshot_digest": request.snapshot_digest,
            "universe_digest": universe_digest,
            "calendar_digest": calendar_digest,
            "target_weights_digest": target_digest,
            "daily_returns": [float(value) for value in selected.daily_returns],
            "return_dates": list(selected.return_dates),
            "terminal_nav": float(selected.terminal_nav),
            "terminal_weights": {
                str(key): float(value)
                for key, value in sorted(selected.terminal_weights.items())
            },
            "metrics": dict(selected.metrics),
            "qlib_config": qlib_config,
            "qlib_config_digest": qlib_config_digest,
            "selected_experiment": selected_id,
            "research_summary_digest": research_summary_digest,
        }
        qlib_receipt_digest = _digest(receipt_body)
        qlib_receipt = {**receipt_body, "receipt_digest": qlib_receipt_digest}
        qlib_path = temp / "qlib_receipt.json"
        qlib_path.write_bytes(_canonical_json(qlib_receipt) + b"\n")
        manifest = {
            "contract": RESEARCH_RESULT_CONTRACT,
            "job_id": request.job_id,
            "run_id": request.run_id,
            "resource_envelope_id": request.resource_envelope_id,
            "resource_policy_digest": request.resource_policy_digest,
            "request_digest": request.request_digest,
            "selected_experiment": selected_id,
            "factor_id": factor_id,
            "candidate_code_digest": factor_digest,
            "qlib_config_digest": qlib_config_digest,
            "target_weights_digest": target_digest,
            "qlib_receipt_digest": qlib_receipt_digest,
            "qlib_receipt_file_digest": _file_digest(qlib_path),
            "budget_spent_usd": budget_spent,
            "factor_file": factor_path.name,
            "target_weights_file": target_path.name,
            "qlib_receipt_file": qlib_path.name,
            "experiment_trials_path": str(experiment_trials_path),
            "experiment_trials_digest": experiment_trials_digest,
            "experiment_trials_file_digest": _file_digest(
                experiment_trials_path
            ),
            "experiment_count": len(history),
            "successful_experiment_count": len(successes),
        }
        (temp / "research_receipt.json").write_bytes(
            _canonical_json(manifest) + b"\n"
        )
        temp.rename(output_dir)
        return _load_existing(output_dir, request)
    finally:
        if temp.exists():
            shutil.rmtree(temp)


__all__ = [
    "D34_TARGET_GROSS_EXPOSURE",
    "D34ResearchError",
    "D34ResearchRequest",
    "D34ResearchResult",
    "EXPERIMENT_TRIAL_BATCH_CONTRACT",
    "HISTORICAL_DSR_REVIEW_NOTES",
    "HUNG_MOMENTUM_CANDIDATE_ID",
    "HUNG_MOMENTUM_CORRECTION_NOTE",
    "QlibExperimentResult",
    "READ_ONLY_DSR_CANDIDATE_ID",
    "ResearchProposal",
    "validate_xnys_calendar",
    "annotate_hung_momentum_candidates",
    "execute_research_request",
    "factor_display_name_zh",
    "qlib_expression",
    "render_factor_source",
]
