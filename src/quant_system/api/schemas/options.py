from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from quant_system.options.models import OptionsScreenerConfig

OptionRecord = dict[str, Any]


class OptionsExpirationsResponse(BaseModel):
    ticker: str
    source: str
    expirations: list[OptionRecord]


class OptionsChainResponse(BaseModel):
    ticker: str
    source: str
    expiration: str
    option_type: str
    contracts: list[OptionRecord]


class OptionsSnapshotResponse(BaseModel):
    success: bool
    ticker: str
    source: str
    price: float
    nearest_expiry: str
    atm_iv: float | None = None
    hv_30d: float | None = None
    iv_rank: float | None = None
    iv_percentile: float | None = None
    iv_rank_source: str
    vrp: float | None = None
    vrp_level: str | None = None
    assumptions: list[str]


class OptionsVolSurface(BaseModel):
    moneyness_axis: list[float]
    expiry_axis: list[str]
    iv_grid: list[list[float | None]]
    points: list[OptionRecord]


class OptionsVolSurfaceResponse(BaseModel):
    success: bool
    ticker: str
    source: str
    price: float
    surface: OptionsVolSurface
    atm_term_structure: dict[str, float]
    shape: str
    assumptions: list[str]


class OptionsVolSmile(BaseModel):
    strikes: list[float | None]
    ivs: list[float | None]
    deltas: list[float | None]
    option_types: list[str]
    moneyness: list[float | None]


class OptionsVolSmileResponse(BaseModel):
    success: bool
    ticker: str
    source: str
    price: float
    expiry: str
    dte: int
    smile: OptionsVolSmile
    skew_metrics: dict[str, float | None]
    shape: str
    assumptions: list[str]


__all__ = [
    "OptionsChainResponse",
    "OptionsExpirationsResponse",
    "OptionsScreenerConfig",
    "OptionsSnapshotResponse",
    "OptionsVolSmileResponse",
    "OptionsVolSurfaceResponse",
]
