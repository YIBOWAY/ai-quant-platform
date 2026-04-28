from __future__ import annotations

from pydantic import BaseModel


class ExperimentSummary(BaseModel):
    id: str
    path: str
