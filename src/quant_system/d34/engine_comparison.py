"""Deterministic comparison of Qlib research and Platform execution replay."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

COMPARISON_CONTRACT = "hqa.d34_comparison/v1"


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class EngineReceipt:
    engine: Literal["qlib", "platform"]
    snapshot_digest: str
    universe_digest: str
    calendar_digest: str
    target_weights_digest: str
    daily_returns: tuple[float, ...]
    terminal_nav: float
    terminal_weights: dict[str, float]
    receipt_digest: str
    return_dates: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        digests = (
            self.snapshot_digest,
            self.universe_digest,
            self.calendar_digest,
            self.target_weights_digest,
            self.receipt_digest,
        )
        if (
            any(
                len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
                for value in digests
            )
            or len(self.daily_returns) < 2
            or (self.return_dates and len(self.return_dates) != len(self.daily_returns))
            or not math.isfinite(self.terminal_nav)
            or self.terminal_nav <= 0
            or any(not math.isfinite(value) for value in self.daily_returns)
            or any(
                not symbol or not math.isfinite(weight) or abs(weight) > 10
                for symbol, weight in self.terminal_weights.items()
            )
        ):
            raise ValueError("engine receipt is invalid")


@dataclass(frozen=True)
class ComparisonPolicy:
    version: str
    min_daily_return_correlation: float
    max_terminal_nav_difference_bps: float
    max_symbol_weight_difference_bps: float
    digest: str

    @classmethod
    def initial(cls) -> ComparisonPolicy:
        document = {
            "contract": "hqa.d34_comparison_policy/v1",
            "version": "1.0",
            "min_daily_return_correlation": 0.995,
            "max_terminal_nav_difference_bps": 25.0,
            "max_symbol_weight_difference_bps": 50.0,
            "exact_input_digests_required": True,
        }
        return cls(
            version="1.0",
            min_daily_return_correlation=0.995,
            max_terminal_nav_difference_bps=25.0,
            max_symbol_weight_difference_bps=50.0,
            digest=_digest(document),
        )


@dataclass(frozen=True)
class EngineComparison:
    contract: str
    accepted: bool
    reason_codes: tuple[str, ...]
    exact_inputs: bool
    daily_return_correlation: float
    terminal_nav_difference_bps: float
    max_symbol_weight_difference_bps: float
    policy_digest: str
    qlib_receipt_digest: str
    platform_receipt_digest: str
    comparison_digest: str
    per_symbol_weight_difference_bps: dict[str, float]


def _correlation(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        return -1.0
    left_array, right_array = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    if np.std(left_array) == 0 or np.std(right_array) == 0:
        return 1.0 if np.array_equal(left_array, right_array) else 0.0
    value = float(np.corrcoef(left_array, right_array)[0, 1])
    return value if math.isfinite(value) else -1.0


def compare_engine_receipts(
    *,
    qlib: EngineReceipt,
    platform: EngineReceipt,
    policy: ComparisonPolicy,
) -> EngineComparison:
    if qlib.engine != "qlib" or platform.engine != "platform":
        raise ValueError("comparison requires Qlib and Platform receipts")
    reasons: list[str] = []
    exact_fields = (
        ("snapshot_digest", "snapshot_digest_mismatch"),
        ("universe_digest", "universe_digest_mismatch"),
        ("calendar_digest", "calendar_digest_mismatch"),
        ("target_weights_digest", "target_weights_digest_mismatch"),
    )
    for field_name, reason in exact_fields:
        if getattr(qlib, field_name) != getattr(platform, field_name):
            reasons.append(reason)
    if qlib.return_dates != platform.return_dates:
        reasons.append("return_dates_mismatch")
    correlation = _correlation(qlib.daily_returns, platform.daily_returns)
    nav_difference = abs(platform.terminal_nav - qlib.terminal_nav) / qlib.terminal_nav * 10_000
    symbols = sorted(set(qlib.terminal_weights) | set(platform.terminal_weights))
    weight_differences = {
        symbol: abs(
            platform.terminal_weights.get(symbol, 0.0) - qlib.terminal_weights.get(symbol, 0.0)
        )
        * 10_000
        for symbol in symbols
    }
    max_weight_difference = max(weight_differences.values(), default=0.0)
    if correlation < policy.min_daily_return_correlation:
        reasons.append("daily_return_correlation_below_minimum")
    if nav_difference > policy.max_terminal_nav_difference_bps:
        reasons.append("terminal_nav_difference_above_maximum")
    if max_weight_difference > policy.max_symbol_weight_difference_bps:
        reasons.append("symbol_weight_difference_above_maximum")
    reason_codes = tuple(dict.fromkeys(reasons))
    document = {
        "contract": COMPARISON_CONTRACT,
        "accepted": not reason_codes,
        "reason_codes": list(reason_codes),
        "daily_return_correlation": correlation,
        "terminal_nav_difference_bps": nav_difference,
        "max_symbol_weight_difference_bps": max_weight_difference,
        "per_symbol_weight_difference_bps": weight_differences,
        "policy_digest": policy.digest,
        "qlib_receipt_digest": qlib.receipt_digest,
        "platform_receipt_digest": platform.receipt_digest,
    }
    return EngineComparison(
        contract=COMPARISON_CONTRACT,
        accepted=not reason_codes,
        reason_codes=reason_codes,
        exact_inputs=not any(
            reason.endswith("_digest_mismatch") or reason == "return_dates_mismatch"
            for reason in reason_codes
        ),
        daily_return_correlation=correlation,
        terminal_nav_difference_bps=nav_difference,
        max_symbol_weight_difference_bps=max_weight_difference,
        policy_digest=policy.digest,
        qlib_receipt_digest=qlib.receipt_digest,
        platform_receipt_digest=platform.receipt_digest,
        comparison_digest=_digest(document),
        per_symbol_weight_difference_bps=weight_differences,
    )


__all__ = [
    "COMPARISON_CONTRACT",
    "ComparisonPolicy",
    "EngineComparison",
    "EngineReceipt",
    "compare_engine_receipts",
]
