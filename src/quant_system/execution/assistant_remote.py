"""Chat remote: dispatch research and hang are two commands.

Dispatch never creates a hung sleeve. Hang requires an existing verified
candidate bound to source/artifact digest. This module is the file-backed
book used by isolation preview and by chat wrappers.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from quant_system.config.settings import Settings
from quant_system.d34.artifact_factor import load_d34_paper_factor_registry
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

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_FACTOR_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")

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


def _require_digest(value: object, *, code: str = "candidate_digest_required") -> str:
    cleaned = str(value or "").strip().lower()
    if _DIGEST_RE.fullmatch(cleaned) is None:
        raise AssistantRemoteError(code)
    return cleaned


def _require_factor_id(value: object) -> str:
    cleaned = str(value or "").strip()
    if _FACTOR_ID_RE.fullmatch(cleaned) is None:
        raise AssistantRemoteError("candidate_factor_required")
    return cleaned


def _require_universe(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise AssistantRemoteError("candidate_universe_required")
    symbols: list[str] = []
    for item in value:
        symbol = str(item or "").strip().upper()
        if not symbol or symbol != symbol.upper():
            raise AssistantRemoteError("candidate_universe_required")
        symbols.append(symbol)
    if len(set(symbols)) != len(symbols):
        raise AssistantRemoteError("candidate_universe_required")
    return symbols


def _bound_source(
    *,
    source_digest: object,
    source_path: object,
    factor_id: object,
    universe: object,
) -> tuple[str, Path, str, list[str]]:
    digest = _require_digest(source_digest)
    path = Path(str(source_path or "")).expanduser()
    if not path.is_file():
        raise AssistantRemoteError("candidate_source_unavailable")
    path = path.resolve()
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != digest:
        raise AssistantRemoteError("candidate_source_digest_mismatch")
    return digest, path, _require_factor_id(factor_id), _require_universe(universe)


def record_verified_candidate(
    settings: Settings,
    *,
    candidate_id: str,
    objective: str,
    source: str,
    source_digest: str | None = None,
    source_path: str | None = None,
    factor_id: str | None = None,
    universe: Sequence[str] | None = None,
    artifact_id: str | None = None,
    comparison_digest: str | None = None,
) -> dict[str, Any]:
    cleaned = candidate_id.strip()
    if not cleaned:
        raise AssistantRemoteError("candidate_id_required")
    digest, path, bound_factor, bound_universe = _bound_source(
        source_digest=source_digest,
        source_path=source_path,
        factor_id=factor_id,
        universe=universe,
    )
    bound_comparison = None
    if comparison_digest is not None:
        bound_comparison = _require_digest(
            comparison_digest,
            code="candidate_comparison_digest_invalid",
        )
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
        existing_digest = existing.get("source_digest") or existing.get(
            "candidate_code_digest"
        )
        if (
            existing_digest != digest
            or existing.get("factor_id") != bound_factor
            or list(existing.get("universe") or []) != bound_universe
        ):
            raise AssistantRemoteError("candidate_lineage_conflict")
        return existing
    record = {
        "candidate_id": cleaned,
        "objective": objective.strip(),
        "status": "verified",
        "source": source,
        "artifact_id": artifact_id,
        "source_digest": digest,
        "candidate_code_digest": digest,
        "comparison_digest": bound_comparison,
        "source_path": str(path),
        "factor_id": bound_factor,
        "universe": bound_universe,
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
    digest, source_path, factor_id, universe = _bound_source(
        source_digest=candidate.get("source_digest")
        or candidate.get("candidate_code_digest"),
        source_path=candidate.get("source_path"),
        factor_id=candidate.get("factor_id"),
        universe=candidate.get("universe"),
    )
    if candidate.get("sleeve_id") or candidate.get("status") == "hung":
        sleeve_id = candidate.get("sleeve_id")
        if not sleeve_id:
            raise AssistantRemoteError("hung_sleeve_missing")
        api_runs_dir = Path(settings.data.data_dir) / "api_runs"
        try:
            sleeve = PaperStrategySleeveStorage(api_runs_dir).load_sleeve(str(sleeve_id))
        except FileNotFoundError as exc:
            raise AssistantRemoteError("hung_sleeve_missing") from exc
        observed = sleeve.metadata.get("candidate_code_digest") or sleeve.metadata.get(
            "source_digest"
        )
        if observed != digest:
            raise AssistantRemoteError("hung_sleeve_digest_mismatch")
        return {
            "contract": HANG_CONTRACT,
            "status": "hung",
            "candidate_id": cleaned,
            "sleeve_id": sleeve_id,
            "source_digest": digest,
            "factor_id": factor_id,
            "universe": universe,
            "already_hung": True,
        }
    if candidate.get("status") != "verified":
        raise AssistantRemoteError("candidate_not_verified")
    comparison_digest = candidate.get("comparison_digest")
    if comparison_digest is not None:
        comparison_digest = _require_digest(
            comparison_digest,
            code="candidate_comparison_digest_invalid",
        )
    try:
        registry = load_d34_paper_factor_registry(
            code_path=source_path,
            expected_code_digest=digest,
            expected_factor_id=factor_id,
        )
        lookback = registry.create(factor_id).lookback
    except ValueError as exc:
        raise AssistantRemoteError(str(exc)) from exc

    api_runs_dir = Path(settings.data.data_dir) / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    account = account_storage.load()
    if account is None:
        account = PaperAccount.open_new(initial_cash=1_000_000)
        account.kill_switch = True
    metadata = {
        "automation_managed": True,
        "automation_source": "d34",
        "artifact_id": candidate.get("artifact_id") or cleaned,
        "mandate_id": "remote-hang",
        "promotion_scope": "paper_only",
        "workspace_id": "default",
        "candidate_id": cleaned,
        "candidate_code_digest": digest,
        "source_digest": digest,
        "factor_id": factor_id,
        "artifact_code_path": str(source_path.resolve()),
        "reviewer": "auto",
    }
    if comparison_digest is not None:
        metadata["comparison_digest"] = comparison_digest
    config = StrategyConfig.create(
        name=f"挂上 · {factor_id}",
        description=str(candidate.get("objective") or "explicit hang"),
        strategy_id="cross_sectional_top_n",
        universe_id=f"remote:{cleaned}",
        symbols=universe,
        factor_ids=[factor_id],
        weights={factor_id: 1.0},
        lookback=lookback,
        top_n=1,
        rebalance_frequency="daily",
        max_weight_per_symbol=0.99,
        min_order_value=100.0,
        data_provider="futu",
        execution_timing="next_open",
        metadata=metadata,
    )
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000,
        metadata=metadata,
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    candidate["status"] = "hung"
    candidate["sleeve_id"] = sleeve.sleeve_id
    candidate["source_digest"] = digest
    candidate["candidate_code_digest"] = digest
    candidate["factor_id"] = factor_id
    candidate["universe"] = universe
    candidate["hung_at"] = _utc_now()
    save_book(settings, book)
    return {
        "contract": HANG_CONTRACT,
        "status": "hung",
        "candidate_id": cleaned,
        "sleeve_id": sleeve.sleeve_id,
        "source_digest": digest,
        "factor_id": factor_id,
        "universe": universe,
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
            if isinstance(item, dict)
            and item.get("status") == "hung"
            and _DIGEST_RE.fullmatch(
                str(item.get("source_digest") or item.get("candidate_code_digest") or "")
            )
            is not None
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
