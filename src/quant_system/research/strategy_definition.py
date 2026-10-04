"""Versioned, source-bound strategy recipes; no storage or execution side effects."""

from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from quant_system.d34.qlib_expr import compile_qlib_expr
from quant_system.factors.registry import build_factor_registry
from quant_system.research.study_profiles import list_study_profiles

_ROOT = Path(__file__).resolve().parents[1]
_COMMON_SOURCES = (
    "research/strategy_definition.py",
    "research/strategy_runtime.py",
    "research/profile_backtests.py",
    "research/reference_backtests.py",
    "backtest/engine.py",
    "backtest/models.py",
    "backtest/broker.py",
    "backtest/order_generation.py",
    "backtest/portfolio.py",
    "backtest/metrics.py",
    "trading_kernel/__init__.py",
    "trading_kernel/accounting.py",
    "trading_kernel/weights.py",
    "trading_kernel/models.py",
    "research/definition_paper.py",
    "execution/definition_open_prices.py",
    "execution/paper_strategy_signal_service.py",
    "execution/paper_strategy_execution_service.py",
)
_PROFILE_FIELDS = (
    "family",
    "symbols",
    "peer_symbols",
    "benchmark_symbol",
    "rebalance",
    "top_n",
    "defensive_symbol",
    "expression",
    "formula_lookback",
    "eligibility_window",
)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile_semantics(profile: dict) -> dict:
    return {key: profile[key] for key in _PROFILE_FIELDS if key in profile}


def formula_factor_id(expression: str) -> str:
    """Stable identity for a frozen whitelist expression, independent of its label."""
    canonical = compile_qlib_expr(expression).qlib
    return "formula_" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _factor_identity(
    factor_id: str,
    lookback: int,
    expression: str | None = None,
) -> tuple[str, str]:
    if expression is not None:
        compiled = compile_qlib_expr(expression)
        return "qlib-expression-v1", _digest(
            {
                "expression": compiled.qlib,
                "compiled_body": compiled.pandas_body,
                "compiler_source": _file_digest(_ROOT / "d34/qlib_expr.py"),
            }
        )
    factor = build_factor_registry().create(factor_id, lookback=lookback)
    paths = {
        Path(inspect.getfile(cls)).resolve()
        for cls in type(factor).__mro__
        if cls.__module__.startswith("quant_system.")
    }
    identity = {str(path.relative_to(_ROOT)): _file_digest(path) for path in sorted(paths)}
    return factor.factor_version, _digest(identity)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class StrategyFactor(_StrictModel):
    factor_id: str
    lookback: int = Field(gt=0, le=1260)
    direction: Literal["higher_is_better", "lower_is_better"]
    weight: float = 1.0
    factor_version: str = ""
    source_digest: str = ""
    expression: str | None = None

    @model_validator(mode="after")
    def bind_source(self):
        if self.expression is not None:
            compiled = compile_qlib_expr(self.expression)
            if self.factor_id != formula_factor_id(compiled.qlib):
                raise ValueError("strategy_formula_factor_id_mismatch")
            if self.lookback < compiled.lookback:
                raise ValueError("strategy_formula_factor_lookback_too_short")
            object.__setattr__(self, "expression", compiled.qlib)
        version, digest = _factor_identity(self.factor_id, self.lookback, self.expression)
        if self.factor_version and self.factor_version != version:
            raise ValueError("strategy_factor_version_mismatch")
        if self.source_digest and self.source_digest != digest:
            raise ValueError("strategy_factor_source_mismatch")
        object.__setattr__(self, "factor_version", version)
        object.__setattr__(self, "source_digest", digest)
        return self


class StrategyFormula(_StrictModel):
    expression: str
    lookback: int = 0
    eligibility_window: int = 0
    require_monthly_history: bool = False

    @model_validator(mode="after")
    def compile_formula(self):
        compiled = compile_qlib_expr(self.expression)
        if self.lookback not in (0, compiled.lookback):
            raise ValueError("strategy_formula_lookback_mismatch")
        window = self.eligibility_window or compiled.lookback
        if window < compiled.lookback:
            raise ValueError("strategy_formula_eligibility_too_short")
        object.__setattr__(self, "expression", compiled.qlib)
        object.__setattr__(self, "lookback", compiled.lookback)
        object.__setattr__(self, "eligibility_window", window)
        return self


class StrategyDefinition(_StrictModel):
    schema_version: Literal[1] = 1
    kind: Literal["profile", "formula", "factor_blend"]
    title: str = Field(min_length=1, max_length=200)
    symbols: tuple[str, ...]
    history_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    benchmark_symbol: str = "SPY"
    provider: Literal["futu"] = "futu"
    price_adjustment: Literal["qfq"] = "qfq"
    interval: Literal["1d"] = "1d"
    calendar: Literal["NYSE"] = "NYSE"
    execution_price: Literal["next_open"] = "next_open"
    rebalance: Literal["daily", "weekly", "monthly"] = "daily"
    top_n: int = Field(default=3, gt=0)
    selection: Literal["top", "positive_top", "bottom"] = "top"
    normalization: Literal["rank", "zscore"] = "zscore"
    missing_policy: Literal["complete_intersection"] = "complete_intersection"
    max_weight_per_symbol: float = Field(default=1.0, gt=0, le=1)
    target_gross_exposure: float = Field(default=1.0, ge=0, le=1)
    cash_rule: Literal["unallocated_cash_zero_interest"] = "unallocated_cash_zero_interest"
    initial_cash: float = Field(default=100_000.0, gt=0)
    commission_bps: Literal[1.0] = 1.0
    slippage_bps: Literal[5.0] = 5.0
    min_order_value: float = Field(default=0.0, ge=0)
    whole_share_orders: bool = False
    profile_snapshot: dict[str, Any] | None = None
    formula: StrategyFormula | None = None
    factors: tuple[StrategyFactor, ...] = ()
    source_fingerprints: dict[str, str] = Field(default_factory=dict)
    content_digest: str = ""

    @field_validator("symbols", mode="before")
    @classmethod
    def ordered_symbols(cls, value):
        if isinstance(value, str):
            raise ValueError("strategy_symbols_require_list")
        symbols = tuple(str(item).strip().upper() for item in value)
        if not symbols or any(not item for item in symbols) or len(set(symbols)) != len(symbols):
            raise ValueError("strategy_symbols_empty_or_duplicate")
        return symbols

    @field_validator("benchmark_symbol")
    @classmethod
    def benchmark(cls, value):
        if not value.strip():
            raise ValueError("strategy_benchmark_required")
        return value.strip().upper()

    @field_validator("history_start")
    @classmethod
    def history_origin(cls, value):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise ValueError("strategy_history_start_invalid") from exc

    def calculation_payload(self) -> dict:
        value = self.model_dump(mode="json", exclude={"title", "content_digest"})
        if self.profile_snapshot is not None:
            value["profile_snapshot"] = _profile_semantics(self.profile_snapshot)
        return value

    @model_validator(mode="after")
    def validate_recipe(self):
        if self.top_n > len(self.symbols):
            raise ValueError("strategy_top_n_exceeds_universe")
        if self.kind == "factor_blend":
            if self.formula or self.profile_snapshot or not self.factors:
                raise ValueError("strategy_factor_blend_payload_invalid")
            if len({item.factor_id for item in self.factors}) != len(self.factors):
                raise ValueError("strategy_duplicate_factors")
            if sum(abs(item.weight) for item in self.factors) == 0:
                raise ValueError("strategy_factor_weights_all_zero")
        elif self.kind == "formula":
            if self.formula is None or self.factors:
                raise ValueError("strategy_formula_payload_invalid")
            if self.formula.require_monthly_history and self.rebalance != "monthly":
                raise ValueError("strategy_formula_monthly_history_requires_monthly")
        else:
            if self.profile_snapshot is None or self.formula or self.factors:
                raise ValueError("strategy_profile_payload_invalid")
            current = next(
                (p for p in list_study_profiles() if p["id"] == self.profile_snapshot.get("id")),
                None,
            )
            if current is None or _profile_semantics(current) != _profile_semantics(
                self.profile_snapshot
            ):
                raise ValueError("strategy_profile_snapshot_mismatch")
        if self.profile_snapshot is not None:
            profile = self.profile_snapshot
            if (
                tuple(profile["symbols"]) != self.symbols
                or profile["benchmark_symbol"] != self.benchmark_symbol
                or self.top_n != (profile["top_n"] or 1)
                or self.rebalance
                != ("daily" if profile["rebalance"] == "daily_event" else "monthly")
                or self.selection != "top"
                or self.target_gross_exposure != 1
                or self.max_weight_per_symbol != 1
                or self.initial_cash != 100_000
                or self.min_order_value != 0
                or self.whole_share_orders
            ):
                raise ValueError("strategy_profile_frozen_parameters_mismatch")
            if self.kind == "formula" and (
                profile.get("family") != "formula_hypothesis"
                or profile.get("expression") != self.formula.expression
                or profile.get("eligibility_window") != self.formula.eligibility_window
                or not self.formula.require_monthly_history
            ):
                raise ValueError("strategy_formula_snapshot_mismatch")
        if not self.source_fingerprints:
            object.__setattr__(self, "source_fingerprints", current_source_fingerprints(self))
        expected = _digest(self.calculation_payload())
        if self.content_digest and self.content_digest != expected:
            raise ValueError("strategy_content_digest_mismatch")
        object.__setattr__(self, "content_digest", expected)
        return self


def current_source_fingerprints(definition: StrategyDefinition) -> dict[str, str]:
    paths = list(_COMMON_SOURCES)
    if definition.profile_snapshot is not None:
        paths.append("research/study_profiles.py")
    if definition.kind == "formula" or any(
        item.expression is not None for item in definition.factors
    ):
        paths.append("d34/qlib_expr.py")
    if definition.kind == "factor_blend":
        paths.extend(("factors/base.py", "factors/registry.py", "experiments/scoring.py"))
    result = {path: _file_digest(_ROOT / path) for path in paths}
    result["dependency:exchange_calendars"] = version("exchange_calendars")
    for factor in definition.factors:
        result["factor:" + factor.factor_id] = _factor_identity(
            factor.factor_id, factor.lookback, factor.expression
        )[1]
    return result


def validate_definition(definition: StrategyDefinition | dict) -> StrategyDefinition:
    """Revalidate even model instances: frozen models may contain mutable JSON dicts."""
    raw = (
        definition.model_dump(mode="json")
        if isinstance(definition, StrategyDefinition)
        else definition
    )
    value = StrategyDefinition.model_validate(raw)
    if value.source_fingerprints != current_source_fingerprints(value):
        raise ValueError("strategy_algorithm_source_mismatch")
    return value


def definition_from_study(
    result: dict,
    *,
    history_start: str | None = None,
) -> StrategyDefinition:
    """Freeze a study recipe, not its historical result's eligibility or performance."""
    origin = history_start or (result.get("coverage") or {}).get("loaded_start")
    if not origin:
        raise ValueError("strategy_history_start_required")
    profile = deepcopy(result["profile"])
    is_formula = profile.get("family") == "formula_hypothesis"
    formula = None
    if is_formula:
        formula = StrategyFormula(
            expression=profile["expression"],
            eligibility_window=profile["eligibility_window"],
            require_monthly_history=True,
        )
        profile["expression"] = formula.expression
    return StrategyDefinition(
        kind="formula" if is_formula else "profile",
        title=profile["name"],
        symbols=profile["symbols"],
        history_start=origin,
        benchmark_symbol=profile["benchmark_symbol"],
        rebalance="daily" if profile["rebalance"] == "daily_event" else "monthly",
        top_n=profile["top_n"] or 1,
        profile_snapshot=profile,
        formula=formula,
    )


def definition_from_backtest(
    request,
    symbols: list[str],
    title: str,
    *,
    history_start: str | None = None,
) -> StrategyDefinition:
    """Convert supported backtest parameters; never discard unsupported constraints."""
    raw = request.model_dump(mode="json") if isinstance(request, BaseModel) else dict(request)
    supported = {
        "symbols",
        "universe_id",
        "start",
        "end",
        "provider",
        "strategy_id",
        "factor_ids",
        "weights",
        "benchmark_symbol",
        "lookback",
        "top_n",
        "initial_cash",
        "commission_bps",
        "slippage_bps",
        "min_order_value",
        "whole_share_orders",
        "rebalance_frequency",
        "max_weight_per_symbol",
        "sector_cap",
        "sector_map",
        "factors",
        "normalization",
        "target_gross_exposure",
    }
    if set(raw) - supported:
        raise ValueError(
            "strategy_unsupported_parameters:" + ",".join(sorted(set(raw) - supported))
        )
    if raw.get("sector_cap") is not None or raw.get("sector_map"):
        raise ValueError("strategy_sector_constraints_not_supported")
    strategy = raw.get("strategy_id", "cross_sectional_top_n")
    if strategy not in {"cross_sectional_top_n", "mean_reversion_top_n"}:
        raise ValueError("strategy_kind_not_supported")
    if raw.get("factors") is not None:
        if raw.get("factor_ids") or raw.get("weights"):
            raise ValueError("strategy_ambiguous_factor_parameters")
        factors = tuple(StrategyFactor.model_validate(item) for item in raw["factors"])
    else:
        registry = build_factor_registry()
        ids = raw.get("factor_ids") or ["momentum", "volatility", "liquidity"]
        weights = raw.get("weights", {})
        if set(weights) - set(ids):
            raise ValueError("strategy_weight_for_unselected_factor")
        factors = tuple(
            StrategyFactor(
                factor_id=identifier,
                lookback=raw.get("lookback", 20),
                direction="lower_is_better"
                if registry.create(identifier).direction == "lower_is_better"
                else "higher_is_better",
                weight=weights.get(identifier, 1.0),
            )
            for identifier in ids
        )
    frequency = raw.get("rebalance_frequency", "every_bar")
    if not history_start:
        raise ValueError("strategy_history_start_required")
    return StrategyDefinition(
        kind="factor_blend",
        title=title,
        symbols=symbols,
        history_start=history_start,
        factors=factors,
        provider=raw.get("provider", "futu"),
        benchmark_symbol=raw.get("benchmark_symbol", "SPY"),
        rebalance="daily" if frequency == "every_bar" else frequency,
        selection="positive_top" if strategy == "cross_sectional_top_n" else "bottom",
        normalization=raw.get("normalization", "zscore"),
        top_n=raw.get("top_n", 3),
        initial_cash=raw.get("initial_cash", 100_000),
        commission_bps=raw.get("commission_bps", 1),
        slippage_bps=raw.get("slippage_bps", 5),
        min_order_value=raw.get("min_order_value", 0),
        whole_share_orders=raw.get("whole_share_orders", False),
        max_weight_per_symbol=(
            1 if raw.get("max_weight_per_symbol") is None else raw["max_weight_per_symbol"]
        ),
        target_gross_exposure=raw.get("target_gross_exposure", 1),
    )
