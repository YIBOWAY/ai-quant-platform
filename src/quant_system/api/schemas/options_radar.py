from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class OptionsStrategyTemplatesResponse(BaseModel):
    templates: list[dict[str, Any]]


class OptionsWatchlistResponse(BaseModel):
    watchlist: list[dict[str, Any]]


class OptionsDailyScanDatesResponse(BaseModel):
    dates: list[str]


class OptionsDailyScanStatusResponse(BaseModel):
    exists: bool
    status_path: str
    status: dict[str, Any] | None = None
