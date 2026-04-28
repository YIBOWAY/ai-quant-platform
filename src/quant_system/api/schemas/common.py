from __future__ import annotations

import json
import math
import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class RunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class SafetyFooter(BaseModel):
    dry_run: bool
    paper_trading: bool
    live_trading_enabled: bool
    kill_switch: bool
    bind_address: str


class ErrorResponse(BaseModel):
    detail: str
    safety: SafetyFooter | None = None


class Pagination(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


def make_run_id(prefix: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


def resolve_run_dir(root: Path, run_id: str) -> Path:
    if _SAFE_ID.fullmatch(run_id) is None:
        raise FileNotFoundError(run_id)
    base = root.resolve()
    path = (base / run_id).resolve()
    if base not in path.parents and path != base:
        raise FileNotFoundError(run_id)
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dataframe_records(frame: pd.DataFrame, *, limit: int | None = None) -> list[dict[str, Any]]:
    if limit is not None:
        frame = frame.head(limit)
    records = frame.reset_index(drop=True).to_dict(orient="records")
    return [_jsonable_record(record) for record in records]


def read_parquet_records(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    return dataframe_records(pd.read_parquet(path), limit=limit)


def _jsonable_record(record: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _jsonable_value(value) for key, value in record.items()}


def _jsonable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "isoformat") and value.__class__.__module__.startswith("datetime"):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value):
        return None
    return value
