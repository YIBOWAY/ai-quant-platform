"""Declared option implied-volatility units.

The canonical internal unit is a decimal *ratio* (0.42 == 42% IV). Some
surfaces speak *percent* (42.0 == 42% IV): the Futu raw SDK frame, the
historically persisted DuckDB cache rows, and the ``/api/options/chain``
response contract.

Unit conversion is driven by a *declared* unit, never by a magnitude guess
such as "anything above 5 must be percent". A value with no declared unit is
assumed to be the canonical ratio, except the DuckDB cache read path where
legacy rows (written before the unit column existed) are a schema-level fact
of percent.
"""

from __future__ import annotations

import logging
import math
from contextlib import suppress
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

IV_UNIT_RATIO = "ratio"
IV_UNIT_PERCENT = "percent"
KNOWN_IV_UNITS = frozenset({IV_UNIT_RATIO, IV_UNIT_PERCENT})

IV_UNIT_ATTR = "implied_volatility_unit"

_LEGACY_CACHE_UNIT = IV_UNIT_PERCENT


def _finite_positive(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return parsed


def to_ratio(value: Any, *, unit: str = IV_UNIT_RATIO) -> float | None:
    """Return ``value`` as a decimal ratio, or None when unusable."""
    parsed = _finite_positive(value)
    if parsed is None:
        return None
    if unit == IV_UNIT_PERCENT:
        return parsed / 100.0
    return parsed


def to_percent(value: Any, *, unit: str = IV_UNIT_RATIO) -> float | None:
    """Return ``value`` as a percent figure, or None when unusable."""
    parsed = _finite_positive(value)
    if parsed is None:
        return None
    if unit == IV_UNIT_PERCENT:
        return parsed
    return parsed * 100.0


def frame_unit(frame: Any) -> str:
    """Declared unit on a DataFrame's ``attrs``; ratio when undeclared."""
    attrs = getattr(frame, "attrs", None)
    unit = attrs.get(IV_UNIT_ATTR) if isinstance(attrs, dict) else None
    return unit if unit in KNOWN_IV_UNITS else IV_UNIT_RATIO


def declare_unit(frame: Any, unit: str = IV_UNIT_RATIO) -> Any:
    """Tag a DataFrame with its IV unit and return it."""
    if unit not in KNOWN_IV_UNITS:
        unit = IV_UNIT_RATIO
    with suppress(AttributeError):
        frame.attrs[IV_UNIT_ATTR] = unit
    return frame


IV_COLUMN_ALIASES: tuple[str, ...] = ("implied_volatility", "option_implied_volatility")

_UNDECLARED_PERCENT_MAGNITUDE = 5.0
_undeclared_percent_warning_emitted = False


def _warn_if_undeclared_percent_magnitude(frame: Any, present: list[str]) -> None:
    """Log-only tripwire for percent-scale values on a unit-undeclared frame.

    Observability for the silent-fail direction left by removing the >5
    magnitude heuristics: values are still treated as the canonical ratio,
    this changes nothing about the returned data. Emitted at most once per
    process to avoid log spam on scan-sized frames.
    """
    global _undeclared_percent_warning_emitted
    if _undeclared_percent_warning_emitted:
        return
    for name in present:
        series = pd.to_numeric(frame[name], errors="coerce")
        if bool((series > _UNDECLARED_PERCENT_MAGNITUDE).any()):
            logger.warning(
                "implied-volatility frame has no declared unit but %s holds "
                "percent-magnitude values; treating as canonical ratio",
                name,
            )
            _undeclared_percent_warning_emitted = True
            return


def frame_to_ratio(
    frame: Any,
    *,
    columns: tuple[str, ...] = IV_COLUMN_ALIASES,
) -> Any:
    """Return a frame whose IV columns are the canonical ratio.

    A frame already declared as ratio (the common case) is returned as-is; a
    percent frame is copied and converted. Callers that need a new object can
    copy the result themselves.
    """
    attrs = getattr(frame, "attrs", None)
    declared = isinstance(attrs, dict) and attrs.get(IV_UNIT_ATTR) in KNOWN_IV_UNITS
    unit = frame_unit(frame)
    present = [name for name in columns if name in getattr(frame, "columns", [])]
    if unit == IV_UNIT_RATIO or not present:
        if not declared:
            _warn_if_undeclared_percent_magnitude(frame, present)
        return frame
    active = frame.copy()
    for name in present:
        active[name] = pd.to_numeric(active[name], errors="coerce").map(
            lambda value, _unit=unit: to_ratio(value, unit=_unit)
        )
    return declare_unit(active, IV_UNIT_RATIO)


def legacy_cache_unit() -> str:
    """Unit of cache rows persisted before the unit column existed."""
    return _LEGACY_CACHE_UNIT


__all__ = [
    "IV_COLUMN_ALIASES",
    "IV_UNIT_ATTR",
    "IV_UNIT_PERCENT",
    "IV_UNIT_RATIO",
    "KNOWN_IV_UNITS",
    "declare_unit",
    "frame_to_ratio",
    "frame_unit",
    "legacy_cache_unit",
    "to_percent",
    "to_ratio",
]
