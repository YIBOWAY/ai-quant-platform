"""Chat remote: dispatch research and hang are two commands.

Dispatch never creates a hung sleeve. Hang requires an existing verified
candidate. This module is the file-backed book used by isolation preview and
by chat wrappers. D-34 enqueue is attempted when a Mandate exists, but a
missing Mandate still records the ask.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_system.config.settings import Settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategyConfig,
    StrategySleeveMode,
)

BOOK_CONTRACT = "hqa.assistant_remote_book/v1"
DISPATCH_CONTRACT = "hqa.assistant_remote_dispatch/v1"
HANG_CONTRACT = "hqa.assistant_remote_hang/v1"


class AssistantRemoteError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _book_path(settings: Settings) -> Path:
    return Path(settings.data.data_dir) / "assistant_remote" / "book.json"


def load_book(settings: Settings) -> dict[str, Any]:
    path = _book_path(settings)
    if not path.is_file():
        return {
            "contract": BOOK_CONTRACT,
            "candidates": [],
            "requests": [],
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssistantRemoteError("assistant_remote_book_invalid")
    payload.setdefault("candidates", [])
    payload.setdefault("requests", [])
    return payload


def save_book(settings: Settings, book: dict[str, Any]) -> None:
    path = _book_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "contract": BOOK_CONTRACT,
        "candidates": list(book.get("candidates") or []),
        "requests": list(book.get("requests") or []),
    }
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def dispatch_research(
    settings: Settings,
    *,
    objective: str,
    hang_if_pass: bool = False,
) -> dict[str, Any]:
    cleaned = objective.strip()
    if len(cleaned) < 8:
        raise AssistantRemoteError("research_objective_required")
    book = load_book(settings)
    request_id = f"request-{uuid.uuid4().hex[:12]}"
    record = {
        "request_id": request_id,
        "objective": cleaned,
        "hang_if_pass": hang_if_pass is True,
        "status": "requested",
        "job_key": None,
        "created_at": _utc_now(),
    }
    book["requests"].insert(0, record)
    save_book(settings, book)
    return {
        "contract": DISPATCH_CONTRACT,
        "status": "requested",
        "request_id": request_id,
        "candidate_id": None,
        "hang_if_pass": hang_if_pass is True,
        "hung": False,
    }


def record_verified_candidate(
    settings: Settings,
    *,
    candidate_id: str,
    objective: str,
    source: str,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    cleaned = candidate_id.strip()
    if not cleaned:
        raise AssistantRemoteError("candidate_id_required")
    book = load_book(settings)
    existing = next(
        (
            item
            for item in book["candidates"]
            if isinstance(item, dict) and item.get("candidate_id") == cleaned
        ),
        None,
    )
    if existing is not None:
        return existing
    record = {
        "candidate_id": cleaned,
        "objective": objective.strip(),
        "status": "verified",
        "source": source,
        "artifact_id": artifact_id,
        "sleeve_id": None,
        "created_at": _utc_now(),
    }
    book["candidates"].insert(0, record)
    save_book(settings, book)
    return record


def hang_candidate(settings: Settings, *, candidate_id: str) -> dict[str, Any]:
    cleaned = candidate_id.strip()
    if not cleaned:
        raise AssistantRemoteError("candidate_id_required")
    book = load_book(settings)
    candidate = next(
        (
            item
            for item in book["candidates"]
            if isinstance(item, dict) and item.get("candidate_id") == cleaned
        ),
        None,
    )
    if candidate is None:
        raise AssistantRemoteError("candidate_not_found")
    if candidate.get("sleeve_id") or candidate.get("status") == "hung":
        return {
            "contract": HANG_CONTRACT,
            "status": "hung",
            "candidate_id": cleaned,
            "sleeve_id": candidate.get("sleeve_id"),
            "already_hung": True,
        }
    if candidate.get("status") != "verified":
        raise AssistantRemoteError("candidate_not_verified")

    api_runs_dir = Path(settings.data.data_dir) / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    account = account_storage.load()
    if account is None:
        account = PaperAccount.open_new(initial_cash=1_000_000)
        account.kill_switch = True
    config = StrategyConfig.create(
        name=f"挂上 · {cleaned[-8:]}",
        description=str(candidate.get("objective") or "explicit hang"),
        strategy_id="cross_sectional_top_n",
        universe_id="custom",
        symbols=["AAPL", "MSFT"],
        factor_ids=["momentum"],
        weights={"momentum": 1.0},
        lookback=5,
        top_n=1,
        rebalance_frequency="daily",
        max_weight_per_symbol=0.99,
        min_order_value=100.0,
        data_provider="futu",
        execution_timing="next_open",
        metadata={"source": "assistant_remote_hang"},
    )
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "artifact_id": cleaned,
            "mandate_id": "remote-hang",
            "promotion_scope": "paper_only",
            "workspace_id": "default",
            "candidate_id": cleaned,
        },
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    candidate["status"] = "hung"
    candidate["sleeve_id"] = sleeve.sleeve_id
    candidate["hung_at"] = _utc_now()
    save_book(settings, book)
    return {
        "contract": HANG_CONTRACT,
        "status": "hung",
        "candidate_id": cleaned,
        "sleeve_id": sleeve.sleeve_id,
        "already_hung": False,
    }


def project_book(settings: Settings) -> dict[str, Any]:
    book = load_book(settings)
    return {
        "contract": BOOK_CONTRACT,
        "candidates": book["candidates"],
        "requests": book["requests"],
        "verified_count": sum(
            1
            for item in book["candidates"]
            if isinstance(item, dict) and item.get("status") == "verified"
        ),
        "hung_count": sum(
            1
            for item in book["candidates"]
            if isinstance(item, dict) and item.get("status") == "hung"
        ),
    }


__all__ = [
    "AssistantRemoteError",
    "BOOK_CONTRACT",
    "DISPATCH_CONTRACT",
    "HANG_CONTRACT",
    "dispatch_research",
    "hang_candidate",
    "load_book",
    "project_book",
    "record_verified_candidate",
    "save_book",
]
