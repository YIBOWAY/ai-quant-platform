from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from quant_system.experiments.models import WalkForwardConfig


class ExperimentSummary(BaseModel):
    id: str
    path: str
    best_run_id: str | None = None
    created_at: str | None = None


class ExperimentsResponse(BaseModel):
    experiments: list[ExperimentSummary]


class ExperimentRunPathsResponse(BaseModel):
    config: str
    runs: str
    folds: str
    agent_summary: str
    report: str


class ExperimentRunResponse(BaseModel):
    experiment_id: str
    raw_experiment_id: str
    provider: str
    source: str
    run_count: int
    best_run_id: str | None = None
    paths: ExperimentRunPathsResponse


ExperimentRecord = dict[str, Any]


class ExperimentDetailResponse(BaseModel):
    id: str
    path: str
    experiment_config: dict[str, Any] | None = None
    agent_summary: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    runs: list[ExperimentRecord] = Field(default_factory=list)
    folds: list[ExperimentRecord] = Field(default_factory=list)


PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


class ExperimentRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"], min_length=2)
    start: str
    end: str
    provider: Literal["sample", "futu", "tiingo"] = "sample"
    lookbacks: list[PositiveInt] = Field(default_factory=lambda: [3, 5], min_length=1)
    top_ns: list[PositiveInt] = Field(default_factory=lambda: [1, 2], min_length=1)
    initial_cash: NonNegativeFloat = 100_000.0
    commission_bps: NonNegativeFloat = 1.0
    slippage_bps: NonNegativeFloat = 5.0
    rebalance_every_n_bars: PositiveInt = 1
    walk_forward: WalkForwardConfig = Field(default_factory=WalkForwardConfig)
