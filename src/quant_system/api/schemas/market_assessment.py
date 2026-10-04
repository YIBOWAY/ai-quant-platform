from typing import Literal

from pydantic import BaseModel


class MarketAssessmentRefreshRequest(BaseModel):
    scope: Literal["us", "asia"] = "us"
    include_ai: bool = True


class MarketHistoryReference(BaseModel):
    samples: int
    frequency: Literal["day", "month", "quarter", "year"]
    start_date: str
    end_date: str
    minimum: float
    median: float
    maximum: float


class MarketAssessmentFactor(BaseModel):
    key: str
    label: str
    value: float | None
    unit: str
    score: float | None
    weight: float
    status: Literal["available", "unavailable"]
    source_url: str | None
    source_date: str | None
    meaning: str
    source_urls: dict[str, str] | None = None
    history_reference: MarketHistoryReference | None = None


class MarketAssessmentScores(BaseModel):
    pressure: float | None
    valuation: float | None
    bubble: float | None


class MarketAssessmentCoverage(BaseModel):
    available: int
    total: int
    weight_pct: float


class MarketRuleAssessment(BaseModel):
    headline: str
    stance: str
    reasons: list[str]
    watch_next: list[str]
    invalidations: list[str]


class MarketAiAnalysis(BaseModel):
    model: str
    reasoning_effort: str | None = None
    input_digest: str
    generated_at: str
    summary: str
    actions: list[str]
    scenarios: list[str]
    evidence_refs: list[str]


class MarketAssessmentRow(BaseModel):
    symbol: str
    label: str
    score: float | None
    valuation_score: float | None
    pressure_score: float | None
    pe: float | None
    pb: float | None
    trend_deviation_pct: float | None
    drawdown_pct: float | None
    source_url: str | None
    source_date: str | None
    status: str


class MarketAssessmentResponse(BaseModel):
    scope: Literal["us", "asia"]
    status: Literal["ready", "partial", "unavailable", "updating", "failed"]
    as_of: str | None
    updated_at: str | None
    input_digest: str | None
    score: float | None
    scores: MarketAssessmentScores
    coverage: MarketAssessmentCoverage
    factors: list[MarketAssessmentFactor]
    rule_assessment: MarketRuleAssessment
    ai_analysis: MarketAiAnalysis | None
    ai_error: str | None
    market_rows: list[MarketAssessmentRow]
