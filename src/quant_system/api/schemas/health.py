from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
    data_provider: dict[str, Any]
    futu_opend: dict[str, Any]
    database: dict[str, Any]
