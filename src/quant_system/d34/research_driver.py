"""Durable RD-Agent/Qlib research loop for one D-34 experiment job.

RD-Agent selects and iterates a bounded factor specification.  The specification
is rendered deterministically into both a Qlib expression and a digest-bound
Platform ``BaseFactor``.  Qlib owns research calculation/backtesting; Platform
later consumes only the emitted target weights for an independent execution
replay.
"""

from __future__ import annotations

import hashlib
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

RESEARCH_REQUEST_CONTRACT = "hqa.d34_research_request/v1"
RESEARCH_RESULT_CONTRACT = "hqa.d34_research_result/v1"
ENGINE_RECEIPT_CONTRACT = "hqa.d34_engine_receipt/v1"
D34_TARGET_GROSS_EXPOSURE = 0.99

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._:-]{0,31}$")
_FACTOR_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class D34ResearchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


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


class D34ResearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract: Literal[RESEARCH_REQUEST_CONTRACT]
    job_id: str = Field(pattern=r"^job-[A-Za-z0-9._:-]{8,200}$")
    mandate_id: str = Field(pattern=r"^mandate-[A-Za-z0-9._:-]{8,200}$")
    snapshot_id: str = Field(pattern=r"^snapshot-[A-Za-z0-9._:-]{8,200}$")
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_source: Literal["futu"]
    provider_uri: Path
    universe: tuple[str, ...]
    calendar: tuple[str, ...]
    max_iterations: int = Field(default=3, ge=1, le=20)
    experiments_per_iteration: int = Field(default=3, ge=1, le=20)
    top_k: int = Field(default=1, ge=1, le=100)
    initial_cash: float = Field(default=100_000, gt=0, le=1_000_000_000)
    budget_reservation_usd: float = Field(default=10, ge=0, le=100_000)
    objective: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def validate_contract_inputs(self) -> D34ResearchRequest:
        symbols = tuple(value.strip().upper() for value in self.universe)
        if (
            symbols != self.universe
            or not 1 <= len(symbols) <= 100
            or len(set(symbols)) != len(symbols)
            or any(_SYMBOL_RE.fullmatch(value) is None for value in symbols)
            or self.top_k > len(symbols)
            or not self.provider_uri.is_absolute()
            or not self.provider_uri.is_dir()
        ):
            raise ValueError("d34_research_request_invalid")
        try:
            calendar = pd.to_datetime(list(self.calendar), utc=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("d34_research_calendar_invalid") from exc
        if (
            len(calendar) < 3
            or calendar.has_duplicates
            or not calendar.is_monotonic_increasing
            or any(
                pd.Timestamp(value).isoformat() != raw
                for value, raw in zip(calendar, self.calendar, strict=True)
            )
        ):
            raise ValueError("d34_research_calendar_invalid")
        return self

    @property
    def experiment_count(self) -> int:
        return self.max_iterations * self.experiments_per_iteration

    @property
    def request_digest(self) -> str:
        return _digest(self.model_dump(mode="json"))


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
    short_window: int = Field(default=1, ge=1, le=252)
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
        if self.operator == "moving_average_spread" and self.short_window >= self.long_window:
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
            "    factor_version = \"1.0.0\"\n"
            f"    default_lookback = {window}\n"
            "    direction = \"higher_is_better\"\n"
            f"    description = {proposal.thesis!r}\n\n"
            "    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:\n"
            f"{compute}\n\n\n"
            "D34_FACTOR = D34GeneratedFactor\n"
        )
        return source, hashlib.sha256(source.encode("utf-8")).hexdigest()
    compute = {
        "momentum": (
            "        return group[\"close\"].transform(\n"
            "            lambda values: values.pct_change(self.lookback)\n"
            "        )"
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
    expected = {
        factor_path: str(document["candidate_code_digest"]),
        target_path: str(document["target_weights_digest"]),
        qlib_path: str(document["qlib_receipt_file_digest"]),
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
) -> D34ResearchResult:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    output_dir = root / f"research-{request.request_digest[:32]}"
    if output_dir.exists():
        return _load_existing(output_dir, request)

    temp = Path(tempfile.mkdtemp(prefix=".research-", dir=root))
    history: list[dict[str, object]] = []
    successes: list[tuple[str, ResearchProposal, QlibExperimentResult]] = []
    try:
        for iteration in range(1, request.max_iterations + 1):
            for experiment in range(1, request.experiments_per_iteration + 1):
                experiment_id = f"iteration-{iteration:02d}-experiment-{experiment:02d}"
                experiment_dir = temp / "experiments" / experiment_id
                experiment_dir.mkdir(parents=True)
                proposal: ResearchProposal | None = None
                try:
                    proposal = proposal_provider(
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
                    history.append(failure)
                    continue
                observation = {
                    "experiment_id": experiment_id,
                    "status": "succeeded",
                    "score": float(outcome.score),
                    "metrics": dict(outcome.metrics),
                    "proposal": proposal.model_dump(mode="json"),
                    "qlib_expression": expression,
                }
                (experiment_dir / "receipt.json").write_bytes(
                    _canonical_json(observation) + b"\n"
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
        universe_digest = _digest(list(request.universe))
        calendar_digest = _digest(list(request.calendar))
        receipt_body = {
            "contract": ENGINE_RECEIPT_CONTRACT,
            "engine": "qlib",
            "job_id": request.job_id,
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
            "mandate_id": request.mandate_id,
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
    "QlibExperimentResult",
    "ResearchProposal",
    "execute_research_request",
    "qlib_expression",
    "render_factor_source",
]
