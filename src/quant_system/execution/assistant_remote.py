"""Chat remote: dispatch research and hang are two commands.

Dispatch never creates a hung sleeve. Hang requires an existing verified
candidate bound to source/artifact digest. This module is the file-backed
book used by isolation preview and by chat wrappers.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import os
import re
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_system.config.settings import Settings
from quant_system.d34.artifact_factor import load_d34_paper_factor_registry
from quant_system.d34.engine_comparison import (
    ComparisonPolicy,
    EngineReceipt,
    compare_engine_receipts,
)
from quant_system.d34.qlib_expr import QlibExprError, compile_qlib_expr
from quant_system.d34.research_driver import (
    HUNG_MOMENTUM_CANDIDATE_ID,
    READ_ONLY_DSR_CANDIDATE_ID,
    annotate_hung_momentum_candidates,
    validate_xnys_calendar,
)
from quant_system.d34.research_request import (
    DEFAULT_JOB_RESERVATION_USD,
    LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
    build_owner_request_input,
    digest_document,
)
from quant_system.execution.account_repository import PaperAccountBootstrapRequired
from quant_system.execution.account_repository_factory import (
    build_paper_account_repository,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    CashAllocationError,
    PaperStrategySleeveService,
    StrategyConfig,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.factors.registry import build_factor_registry
from quant_system.hermes.d34_job_authority import EnqueueJobCommand
from quant_system.research.trials import (
    FACTOR_CORRELATION_MAX,
    TrialsLedger,
    cost_sensitivity_verdict,
    evaluate_candidate_dsr,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_FACTOR_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")

BOOK_CONTRACT = "hqa.assistant_remote_book/v1"
HANG_CONTRACT = "hqa.assistant_remote_hang/v1"
RESEARCH_OPERATION_CONTRACT = "hqa.assistant_remote_research/v1"
RESEARCH_OPERATION_ID_CONTRACT = "hqa.chat_research_operation/v1"
_ACCEPTED_CYCLE_PHASES = frozenset({"candidate_ready", "canary_active"})
_HANG_STRATEGY_IDS = frozenset({"cross_sectional_top_n", "mean_reversion_top_n"})
_DEFAULT_HANG_STRATEGY_ID = "cross_sectional_top_n"
_DEFAULT_HANG_TOP_N = 1
_HANG_ALLOCATION_CASH = 10_000.0
_HANG_ACTIVATION_PENDING = "book_binding_pending"
_HANG_ACTIVATION_ACTIVE = "active"

_EXACT_CANDIDATE_PRESENTATION_ZH = {
    HUNG_MOMENTUM_CANDIDATE_ID: (
        "21 日横截面动量策略",
        "在 SPY、QQQ、NVDA、AAPL 中比较 21 日横截面动量，模拟运行中并按每日信号执行。",
    ),
    READ_ONLY_DSR_CANDIDATE_ID: (
        "低配置横截面选股因子",
        "在 SPY、QQQ、IWM、DIA 中验证横截面选股因子，当前停在已验证候选。",
    ),
}

# Step 4: dispatch can hand the objective to the real D-34 job lane. The book
# then only projects the job's truth; it never invents progress.
_ACTIVE_JOB_REQUEST_STATUSES = frozenset({"queued", "leased", "running"})
_CURRENT_REQUEST_FIELDS = frozenset(
    {
        "request_id",
        "objective",
        "status",
        "job_key",
        "created_at",
        "updated_at",
        "operation_id",
        "material_digest",
        "command_id",
        "platform_session_id",
        "hermes_session_id",
        "hermes_run_id",
        "job_id",
        "job_input_digest",
        "terminal",
        "outcome",
        "result_reply",
        "candidate_id",
        "source_digest",
        "universe",
        "evidence",
    }
)
# PostgresJobAuthority.list rejects anything outside 1..100.
JOB_LIST_LIMIT = 100


class AssistantRemoteError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CandidateEvidenceRef:
    job_id: str
    run_id: str
    manifest_digest: str
    qlib_raw_receipt_digest: str
    platform_raw_receipt_digest: str

    def validated(self) -> dict[str, str]:
        if (
            not self.job_id.startswith("job-")
            or not self.run_id.startswith("attempt-")
            or any(
                _DIGEST_RE.fullmatch(value) is None
                for value in (
                    self.manifest_digest,
                    self.qlib_raw_receipt_digest,
                    self.platform_raw_receipt_digest,
                )
            )
        ):
            raise AssistantRemoteError("candidate_evidence_ref_invalid")
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _book_path(settings: Settings) -> Path:
    return Path(settings.data.data_dir) / "assistant_remote" / "book.json"


def _book_lock_path(settings: Settings) -> Path:
    return Path(settings.data.data_dir) / "assistant_remote" / "book.lock"


@contextmanager
def _book_mutation_lock(
    settings: Settings,
    *,
    timeout_seconds: float = 30.0,
    poll_seconds: float = 0.05,
) -> Iterator[None]:
    """Serialize every assistant-remote book read-modify-write sequence."""
    path = _book_lock_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"timed out waiting for assistant remote book lock {path}"
                    ) from None
                time.sleep(poll_seconds)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
    requests = payload.setdefault("requests", [])
    payload["requests"] = [
        {key: value for key, value in request.items() if key in _CURRENT_REQUEST_FIELDS}
        if isinstance(request, dict)
        else request
        for request in requests
    ]
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


def _job_row_field(job: Any, name: str) -> Any:
    if isinstance(job, dict):
        return job.get(name)
    return getattr(job, name, None)


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


def _has_source_digest(item: dict[str, Any]) -> bool:
    return (
        _DIGEST_RE.fullmatch(
            str(item.get("source_digest") or item.get("candidate_code_digest") or "")
        )
        is not None
    )


def _is_fixture_candidate(item: dict[str, Any]) -> bool:
    """Acceptance fixtures must never count as official hung P&L.

    Step-3 style fixtures declare themselves via ``step3_fixture`` and carry a
    placeholder comparison digest (one repeated hex block). Real dual-engine
    comparison digests never look like that.
    """
    if str(item.get("source") or "") == "step3_fixture":
        return True
    comparison = str(item.get("comparison_digest") or "").strip().lower()
    if _DIGEST_RE.fullmatch(comparison) and (
        len(set(comparison)) == 1 or comparison == comparison[:8] * 8
    ):
        return True
    return False


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


def _stamp_performance_and_dsr(
    record: dict[str, Any],
    settings: Settings,
    *,
    universe: Sequence[str],
    daily_returns: Sequence[float] | None,
    turnover_period: float | None = None,
    return_dates: Sequence[str] | None = None,
) -> None:
    if not daily_returns:
        record["performance"] = None
        record["dsr"] = {"status": "performance_missing", "passed": False}
        return
    result = evaluate_candidate_dsr(
        TrialsLedger(Path(settings.data.data_dir) / "trials"),
        universe=universe,
        daily_returns=daily_returns,
    )
    performance = result.pop("performance", None)
    if not isinstance(performance, dict):
        record["performance"] = None
        record["dsr"] = {**result, "passed": False}
        return
    performance["daily_returns"] = [float(item) for item in daily_returns]
    if turnover_period is not None:
        performance["turnover_period"] = float(turnover_period)
    if return_dates is not None and len(list(return_dates)) == len(performance["daily_returns"]):
        performance["return_dates"] = [str(day)[:10] for day in return_dates]
    record["performance"] = performance
    record["dsr"] = result


def resolve_hang_sleeve_strategy(
    candidate: Mapping[str, Any],
    *,
    universe: Sequence[str],
) -> tuple[str, int]:
    """Pick the hung sleeve from the candidate. D34 scores stay higher-is-better."""

    del universe
    raw_strategy = candidate.get("strategy_id")
    if raw_strategy in _HANG_STRATEGY_IDS:
        strategy_id = str(raw_strategy)
    else:
        strategy_id = _DEFAULT_HANG_STRATEGY_ID
    raw_top = candidate.get("top_n")
    if isinstance(raw_top, int) and raw_top >= 1:
        top_n = raw_top
    else:
        top_n = _DEFAULT_HANG_TOP_N
    return strategy_id, top_n


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
    daily_returns: Sequence[float] | None = None,
    turnover_period: float | None = None,
    return_dates: Sequence[str] | None = None,
    strategy_id: str | None = None,
    top_n: int | None = None,
    operator: str | None = None,
    verification_receipt_digest: str | None = None,
    evidence_ref: CandidateEvidenceRef | None = None,
    require_admission_gates: bool = False,
    admission_ref: dict | None = None,
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
    definition = None
    if source == "strategy_definition":
        from quant_system.research.definition_paper import load_candidate_definition

        try:
            definition = load_candidate_definition(
                path, factor_id=bound_factor, universe=bound_universe,
            )
        except (OSError, ValueError) as exc:
            raise AssistantRemoteError(str(exc)) from exc
    bound_comparison = None
    if comparison_digest is not None:
        bound_comparison = _require_digest(
            comparison_digest,
            code="candidate_comparison_digest_invalid",
        )
    bound_verification_receipt = None
    if verification_receipt_digest is not None:
        bound_verification_receipt = _require_digest(
            verification_receipt_digest,
            code="registered_factor_receipt_digest_invalid",
        )
    if require_admission_gates:
        if return_dates is None:
            raise AssistantRemoteError("research_calendar_required")
        try:
            validate_xnys_calendar(list(return_dates))
        except ValueError as exc:
            raise AssistantRemoteError("research_calendar_invalid") from exc
    bound_evidence_ref = evidence_ref.validated() if evidence_ref is not None else None
    if require_admission_gates and bound_evidence_ref is None:
        raise AssistantRemoteError("candidate_evidence_ref_required")
    from quant_system.research import admission_v2

    try:
        admission_v2.require_protocol_lineage(settings, {
            "candidate_id": cleaned, "source": source, "source_path": str(path),
            "verification_receipt_digest": bound_verification_receipt,
            **({"admission_v2": admission_ref} if admission_ref is not None else {}),
        })
    except (OSError, ValueError) as exc:
        raise AssistantRemoteError(str(exc)) from exc
    tagged = admission_ref is not None or admission_v2.candidate_uses_protocol(
        {"candidate_id": cleaned}
    )
    if tagged:
        try:
            _, recorded_admission = admission_v2.candidate_validation(settings, {
                "candidate_id": cleaned, "admission_v2": admission_ref,
                "source_path": str(path), "source_digest": digest,
                "definition_digest": definition.content_digest if definition else None,
                "verification_receipt_digest": bound_verification_receipt,
                "comparison_digest": bound_comparison,
                "performance": {"daily_returns": list(daily_returns or []),
                                "return_dates": list(return_dates or [])},
            })
            if recorded_admission["mode"] == "authoritative" and (
                recorded_admission["status"] != "passed"
                or recorded_admission["validated_tier"] != "T2"
            ):
                raise ValueError("admission_v2_unfunded_tier")
        except (OSError, ValueError) as exc:
            raise AssistantRemoteError(str(exc)) from exc
    if tagged and recorded_admission["mode"] == "authoritative":
        try:
            admission_v2.verify_for_publication(
                settings, admission_ref, definition_digest=definition.content_digest,
                validation_sha256=bound_verification_receipt, source_sha256=digest,
                book=load_book(settings),
            )
        except (OSError, ValueError) as exc:
            raise AssistantRemoteError(str(exc)) from exc
    with _book_mutation_lock(settings):
        book = load_book(settings)
        if tagged and recorded_admission["mode"] == "authoritative":
            try:
                admission_v2.verify_locked_publication(
                    settings, admission_ref, definition_digest=definition.content_digest,
                    validation_sha256=bound_verification_receipt, source_sha256=digest, book=book,
                )
            except (OSError, ValueError) as exc:
                raise AssistantRemoteError(str(exc)) from exc
        existing = next(
            (
                item
                for item in book["candidates"]
                if isinstance(item, dict) and item.get("candidate_id") == cleaned
            ),
            None,
        )
        if existing is not None:
            if tagged and existing.get("admission_v2") != admission_ref:
                raise AssistantRemoteError("candidate_lineage_conflict")
            if source == "strategy_definition" and (
                existing.get("comparison_digest") != bound_comparison
                or list((existing.get("performance") or {}).get("daily_returns") or []) != list(daily_returns or [])
                or list((existing.get("performance") or {}).get("return_dates") or []) != [str(day)[:10] for day in (return_dates or [])]
            ):
                raise AssistantRemoteError("candidate_validation_changed")
            existing_digest = existing.get("source_digest") or existing.get("candidate_code_digest")
            if (
                existing_digest != digest
                or existing.get("factor_id") != bound_factor
                or list(existing.get("universe") or []) != bound_universe
                or (
                    bound_verification_receipt is not None
                    and existing.get("verification_receipt_digest") != bound_verification_receipt
                )
                or (
                    bound_evidence_ref is not None
                    and existing.get("evidence_ref") != bound_evidence_ref
                )
            ):
                raise AssistantRemoteError("candidate_lineage_conflict")
            if require_admission_gates:
                gates = existing.get("verification_gates")
                if (
                    not isinstance(gates, dict)
                    or not isinstance(gates.get("dsr"), dict)
                    or gates["dsr"].get("passed") is not True
                    or not isinstance(gates.get("cost_sensitivity"), dict)
                    or gates["cost_sensitivity"].get("passed") is not True
                ):
                    raise AssistantRemoteError("candidate_admission_unproven")
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
        display_name_zh, summary_zh = _candidate_presentation_zh(record)
        record["display_name_zh"] = display_name_zh
        record["summary_zh"] = summary_zh
        if operator:
            record["operator"] = str(operator)
        if bound_verification_receipt is not None:
            record["verification_receipt_digest"] = bound_verification_receipt
        if bound_evidence_ref is not None:
            record["evidence_ref"] = bound_evidence_ref
        if tagged:
            record["admission_v2"] = admission_ref
        if strategy_id in _HANG_STRATEGY_IDS:
            record["strategy_id"] = strategy_id
        if isinstance(top_n, int) and top_n >= 1:
            record["top_n"] = top_n
        resolved_strategy, resolved_top = resolve_hang_sleeve_strategy(
            record, universe=bound_universe
        )
        record["strategy_id"] = resolved_strategy
        record["top_n"] = resolved_top
        if definition is not None:
            record["definition_digest"] = definition.content_digest
            record["strategy_id"] = "strategy_definition"
            record["top_n"] = definition.top_n
        _stamp_performance_and_dsr(
            record,
            settings,
            universe=bound_universe,
            daily_returns=daily_returns,
            turnover_period=turnover_period,
            return_dates=return_dates,
        )
        if require_admission_gates:
            dsr = record.get("dsr")
            if not isinstance(dsr, dict) or dsr.get("status") == "performance_missing":
                raise AssistantRemoteError("dsr_performance_required")
            if dsr.get("passed") is not True:
                raise AssistantRemoteError("dsr_failed")
            max_corr = _max_hung_correlation(record, book["candidates"])
            if max_corr is not None and max_corr > FACTOR_CORRELATION_MAX:
                raise AssistantRemoteError("correlated_duplicate")
            paper_costs = settings.paper_account
            cost_verdict = _certify_cost_sensitivity(
                record,
                cost_bps=paper_costs.commission_bps + paper_costs.slippage_bps,
            )
            if cost_verdict is None:
                raise AssistantRemoteError("cost_unmeasured_blocked")
            if cost_verdict.get("passed") is not True:
                raise AssistantRemoteError("cost_sensitivity_failed")
            record["max_hung_correlation"] = max_corr
            record["verification_gates"] = {
                "dsr": dict(dsr),
                "max_hung_correlation": max_corr,
                "cost_sensitivity": dict(cost_verdict),
            }
        book["candidates"].insert(0, record)
        save_book(settings, book)
        return record


def _certify_candidate_dsr(
    settings: Settings,
    candidate: dict[str, Any],
    *,
    universe: Sequence[str],
) -> dict[str, Any] | None:
    """Evaluate DSR at hang time against the current ledger, or None."""
    performance = candidate.get("performance")
    returns = None
    if isinstance(performance, dict):
        raw = performance.get("daily_returns")
        if isinstance(raw, list) and raw:
            returns = [float(item) for item in raw]
    if returns is None:
        return None
    result = evaluate_candidate_dsr(
        TrialsLedger(Path(settings.data.data_dir) / "trials"),
        universe=universe,
        daily_returns=returns,
    )
    result.pop("performance", None)
    candidate["dsr"] = result
    return result


def _certify_cost_sensitivity(
    candidate: dict[str, Any], *, cost_bps: float
) -> dict[str, Any] | None:
    """Apply the existing extra linear penalty to a net-return series.

    The legacy net_return_at_2x key is retained for consumers; it is not an
    independent replay with doubled commissions and slippage.
    """
    performance = candidate.get("performance")
    if not isinstance(performance, dict):
        return None
    turnover_period = performance.get("turnover_period")
    total_return = performance.get("total_return")
    n_periods = performance.get("n_periods")
    if turnover_period is None or total_return is None or not n_periods or n_periods < 20:
        return None
    annual_return = (1.0 + float(total_return)) ** (252.0 / float(n_periods)) - 1.0
    annual_turnover = float(turnover_period) * (252.0 / float(n_periods))
    verdict = cost_sensitivity_verdict(
        annual_return=annual_return,
        annual_turnover=annual_turnover,
        cost_bps=cost_bps,
    )
    verdict.update(
        method="extra_linear_cost_penalty_on_net_return",
        exact_replay=False,
        extra_cost_multiplier=verdict.get("multiplier", 2.0),
    )
    candidate["cost_sensitivity"] = verdict
    return verdict


def _max_hung_correlation(
    candidate: Mapping[str, Any],
    candidates: Sequence[object],
) -> float | None:
    report = _candidate_concentration(candidate, candidates)
    if report["raw_status"] == "not_evaluated":
        raise AssistantRemoteError("correlation_unmeasured_blocked")
    return report["raw_max"]


def _candidate_concentration(candidate, candidates, *, settings=None):
    """Use authenticated physical peers when called by a current validation."""
    from quant_system.research.gate_v2.correlation_v2 import raw_concentration_v2

    own = candidate.get("performance") or {}
    identity = candidate.get("candidate_id")
    peers = [
        {"sleeve_id": item.get("sleeve_id"),
         "returns": (item.get("performance") or {}).get("daily_returns"),
         "dates": (item.get("performance") or {}).get("return_dates")}
        for item in candidates
        if isinstance(item, dict) and item is not candidate
        and not (identity and item.get("candidate_id") == identity)
        and item.get("status") == "hung"
    ]
    evidence_reason = None
    if settings is not None:
        from quant_system.research.capital_evidence import current_peer_exposures

        try:
            physical = _current_exposure_candidates(settings, candidates)
            peers, _ = current_peer_exposures(settings, [row for row in physical
                if not (identity and row.get("candidate_id") == identity)])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            evidence_reason = str(exc)
            peers = [{"sleeve_id": "unresolved-current-exposure", "returns": None, "dates": None}]
    result = raw_concentration_v2(
        candidate_returns=own.get("daily_returns") or [],
        candidate_dates=own.get("return_dates"), hung_sleeves=peers,
        limit=FACTOR_CORRELATION_MAX, require_dates=True,
    )
    return {**result, "applicable": bool(peers), "passed": result["raw_passed"],
            "evidence_reason": evidence_reason}


def _current_exposure_candidates(settings, candidates, *, storage=None, exposure_evidence=None):
    """Exclude a terminal sleeve only when its account proves no remaining exposure."""
    if not any(isinstance(row, dict) and (row.get("sleeve_id") or row.get("status") == "hung")
               for row in candidates):
        return list(candidates)
    storage = storage or PaperStrategySleeveStorage(Path(settings.data.data_dir) / "api_runs")
    result = []
    for row in candidates:
        if not isinstance(row, dict) or not (row.get("sleeve_id") or row.get("status") == "hung"):
            result.append(row)
            continue
        try:
            sleeve = storage.load_sleeve(str(row.get("sleeve_id") or ""))
        except (OSError, ValueError) as exc:
            raise AssistantRemoteError("peer_sleeve_unavailable") from exc
        if (
            sleeve.metadata.get("candidate_id") != row.get("candidate_id")
            or (sleeve.metadata.get("source_digest")
                or sleeve.metadata.get("candidate_code_digest"))
            != (row.get("source_digest") or row.get("candidate_code_digest"))
            or str(sleeve.mode) != "allocated" or sleeve.initial_allocated_cash <= 0
        ):
            raise AssistantRemoteError("peer_sleeve_lineage_mismatch")
        if str(sleeve.status) in {
            "stopped", "flattened", "transferred", "manually_accepted", "demoted_complete",
        } and not storage.load_sleeve_lots(sleeve.sleeve_id):
            # Missing or empty lot files cannot establish that an allocated
            # sleeve has no exposure. Read the same account authority used by
            # the funding transaction; never fall back from canonical to files.
            try:
                repository = build_paper_account_repository(
                    Path(settings.data.data_dir) / "api_runs", settings=settings,
                )
                _require_clean_persisted_account_allocation(repository)
                account = repository.load()
                if account is None or account.account_id != sleeve.account_id:
                    raise ValueError("peer_account_missing_or_mismatched")
                for position in account.positions.values():
                    quantities = list(position.source_quantity.values())
                    if (
                        not math.isfinite(position.quantity) or position.quantity < 0
                        or any(not math.isfinite(qty) or qty < 0 for qty in quantities)
                        # Match the existing stock accounting quantity tolerance.
                        or abs(math.fsum(quantities) - position.quantity) > 1e-9
                    ):
                        raise ValueError("peer_account_sources_incomplete")
                held = {
                    symbol: float(position.source_quantity[f"strategy:{sleeve.sleeve_id}"])
                    for symbol, position in account.positions.items()
                    if f"strategy:{sleeve.sleeve_id}" in position.source_quantity
                }
                if any(not math.isfinite(quantity) or quantity < 0 for quantity in held.values()):
                    raise ValueError("peer_account_position_invalid")
                held = {symbol: quantity for symbol, quantity in held.items() if quantity > 0}
            except Exception as exc:
                raise AssistantRemoteError("peer_account_unavailable") from exc
            if exposure_evidence is not None:
                exposure_evidence[sleeve.sleeve_id] = {
                    "account_id": account.account_id,
                    "mode": settings.paper_account.db_mode,
                    "source_quantities": held,
                }
            if any(quantity > 0 for quantity in held.values()):
                raise AssistantRemoteError("peer_holdings_state_mismatch")
            continue
        if row.get("status") != "hung":
            raise AssistantRemoteError("peer_book_status_mismatch")
        result.append(row)
    return result


def _current_new_capital_quality(settings, candidate, candidates, *, storage=None):
    from quant_system.research.capital_evidence import current_candidate_quality

    peers = _current_exposure_candidates(settings, candidates, storage=storage)
    report = current_candidate_quality(settings, candidate, peers)
    if report.get("eligible") is not True:
        raise AssistantRemoteError("new_capital_quality_failed:" + ",".join(report["reasons"]))
    return report


def _existing_hang_sleeve(
    *,
    account: Any,
    sleeve_storage: PaperStrategySleeveStorage,
    candidate_id: str,
    digest: str,
    factor_id: str,
    universe: list[str],
    strategy_id: str,
    top_n: int,
    lookback: int,
    definition: Any = None,
) -> tuple[Any, StrategyConfig] | None:
    matches = [
        item
        for item in sleeve_storage.list_sleeves()
        if item.metadata.get("candidate_id") == candidate_id
        and item.metadata.get("mandate_id") == "remote-hang"
        and (item.metadata.get("candidate_code_digest") or item.metadata.get("source_digest"))
        == digest
    ]
    if len(matches) > 1:
        raise AssistantRemoteError("existing_hang_lineage_invalid")
    if not matches:
        return None
    sleeve = matches[0]
    original_metadata = dict(sleeve.metadata)
    fossil_reason = original_metadata.get("fossil_reason")
    nonrecoverable_fossil = fossil_reason not in {None, "not_book_bound"}
    recoverable_lineage = not nonrecoverable_fossil and (
        original_metadata.get("hang_activation_state") == _HANG_ACTIVATION_PENDING
        or fossil_reason == "not_book_bound"
        or (
            original_metadata.get("fossil") is not True
            and original_metadata.get("official_observation") is not False
        )
    )
    safe_metadata = dict(original_metadata)
    safe_metadata["official_observation"] = False
    if nonrecoverable_fossil:
        safe_metadata.pop("hang_activation_state", None)
    else:
        safe_metadata["hang_activation_state"] = _HANG_ACTIVATION_PENDING
    sleeve.metadata = safe_metadata
    sleeve.status = StrategySleeveStatus.PAUSED
    sleeve.paused_at = _utc_now()
    sleeve.updated_at = _utc_now()
    try:
        sleeve_storage.save_sleeve(sleeve)
    except OSError as exc:
        raise AssistantRemoteError("hang_recovery_sleeve_outcome_unknown") from exc
    if not recoverable_lineage:
        raise AssistantRemoteError("existing_hang_lineage_invalid")
    try:
        config = sleeve_storage.load_strategy_config(
            sleeve.strategy_config_id,
            version=sleeve.strategy_config_version,
        )
    except FileNotFoundError as exc:
        raise AssistantRemoteError("existing_hang_lineage_invalid") from exc
    allocation = account.sleeve_cash.get(sleeve.sleeve_id)
    allocation_events = [
        entry
        for entry in account.ledger
        if entry.kind == "sleeve_cash_allocated" and entry.source == f"strategy:{sleeve.sleeve_id}"
    ]
    source = f"strategy:{sleeve.sleeve_id}"
    try:
        persisted_activity = bool(
            sleeve_storage.load_signals(sleeve.sleeve_id)
            or sleeve_storage.load_executions(sleeve.sleeve_id)
            or sleeve_storage.load_sleeve_lots(sleeve.sleeve_id)
            or any(
                path.is_file()
                for path in sleeve_storage.execution_journal_dir(sleeve.sleeve_id).glob("*")
            )
            or any(
                entry.source == source and entry.kind != "sleeve_cash_allocated"
                for entry in account.ledger
            )
            or any(
                abs(float(position.source_quantity.get(source, 0.0))) > 1e-9
                for position in account.positions.values()
            )
        )
    except (OSError, ValueError) as exc:
        raise AssistantRemoteError("existing_hang_activity_present") from exc
    if persisted_activity:
        raise AssistantRemoteError("existing_hang_activity_present")
    if (
        abs(float(sleeve.initial_allocated_cash) - _HANG_ALLOCATION_CASH) > 1e-7
        or abs(float(sleeve.cash) - _HANG_ALLOCATION_CASH) > 1e-7
        or allocation is None
        or abs(float(allocation) - _HANG_ALLOCATION_CASH) > 1e-7
    ):
        raise AssistantRemoteError("existing_hang_allocation_invalid")
    if (
        sleeve.account_id != account.account_id
        or abs(float(allocation) - float(sleeve.cash)) > 1e-7
        or len(allocation_events) != 1
        or sleeve.metadata.get("factor_id") != factor_id
        or (definition is None and config.factor_ids != [factor_id])
        or config.symbols != universe
        or config.strategy_id != strategy_id
        or config.top_n != top_n
        or config.lookback != lookback
    ):
        raise AssistantRemoteError("existing_hang_lineage_invalid")
    if definition is not None:
        from quant_system.research.definition_paper import definition_config_fields

        if any(getattr(config, key) != value
               for key, value in definition_config_fields(definition).items()):
            raise AssistantRemoteError("existing_hang_lineage_invalid")
    if sleeve.metadata.get("fossil") is True:
        recovered_metadata = dict(sleeve.metadata)
        for key in (
            "fossil",
            "fossil_at",
            "fossil_reason",
        ):
            recovered_metadata.pop(key, None)
        recovered_metadata["official_observation"] = False
        recovered_metadata["hang_activation_state"] = _HANG_ACTIVATION_PENDING
        sleeve.metadata = recovered_metadata
        try:
            sleeve_storage.save_sleeve(sleeve)
        except OSError as exc:
            raise AssistantRemoteError("hang_recovery_sleeve_outcome_unknown") from exc
    return sleeve, config


def _activate_book_bound_hang_sleeve(
    sleeve_storage: PaperStrategySleeveStorage,
    sleeve: Any,
) -> None:
    metadata = dict(sleeve.metadata)
    metadata.pop("fossil", None)
    metadata.pop("fossil_at", None)
    metadata.pop("fossil_reason", None)
    metadata.pop("official_observation", None)
    metadata["hang_activation_state"] = _HANG_ACTIVATION_ACTIVE
    sleeve.metadata = metadata
    sleeve.status = StrategySleeveStatus.RUNNING
    sleeve.paused_at = None
    sleeve.updated_at = _utc_now()
    sleeve_storage.save_sleeve(sleeve)


def _hang_sleeve_needs_activation_recovery(sleeve: Any) -> bool:
    metadata = sleeve.metadata or {}
    return (
        sleeve.status == StrategySleeveStatus.PAUSED
        and metadata.get("hang_activation_state") == _HANG_ACTIVATION_PENDING
        and metadata.get("official_observation") is False
    )


def _require_clean_persisted_account_allocation(account_storage: Any) -> None:
    integrity = account_storage.allocation_integrity()
    status = integrity.get("status")
    if status in {"in_sync", "missing"}:
        return
    if status == "partition_invalid":
        raise AssistantRemoteError("paper_account_partition_invalid")
    if status == "allocation_ledger_invalid":
        raise AssistantRemoteError("paper_account_allocation_ledger_invalid")
    if status == "corrupt":
        raise AssistantRemoteError("paper_account_storage_corrupt")
    raise AssistantRemoteError("paper_account_unavailable")


def _require_strategy_activation_receipt(candidate, source_path, validation, expected):
    if expected is None:
        return
    from quant_system.research.validation_receipts import require_activation_receipt

    entry = json.loads((Path(source_path).parent / "entry.json").read_text())
    require_activation_receipt(entry, expected)
    if (candidate.get("source") != "strategy_definition"
            or candidate.get("candidate_id") != expected["candidate_id"]
            or candidate.get("verification_receipt_digest") != expected["validation_sha256"]
            or validation.get("evaluation") != expected["evaluation"]
            or entry.get("definition_digest") != candidate.get("definition_digest")
            or entry.get("source_sha256") != candidate.get("source_digest")):
        raise ValueError("strategy_activation_receipt_changed")


def hang_candidate(
    settings: Settings,
    *,
    candidate_id: str,
    expected_source_digest: str,
    expected_receipt: dict | None = None,
    expected_admission_sha: str | None = None,
) -> dict[str, Any]:
    cleaned = candidate_id.strip()
    if not cleaned:
        raise AssistantRemoteError("candidate_id_required")
    expected_digest = _require_digest(expected_source_digest)
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
    candidate_digest = _require_digest(
        candidate.get("source_digest") or candidate.get("candidate_code_digest")
    )
    if candidate_digest != expected_digest:
        raise AssistantRemoteError("candidate_source_digest_mismatch")
    digest, source_path, factor_id, universe = _bound_source(
        source_digest=candidate.get("source_digest") or candidate.get("candidate_code_digest"),
        source_path=candidate.get("source_path"),
        factor_id=candidate.get("factor_id"),
        universe=candidate.get("universe"),
    )
    definition = None
    from quant_system.research import admission_v2

    admission_receipt = None
    try:
        admission_v2.require_protocol_lineage(settings, candidate)
    except (OSError, ValueError) as exc:
        raise AssistantRemoteError(str(exc)) from exc
    tagged = admission_v2.candidate_uses_protocol(candidate)
    if expected_admission_sha is not None and not tagged:
        raise AssistantRemoteError("admission_v2_activation_receipt_changed")
    if expected_receipt is not None and candidate.get("source") != "strategy_definition":
        raise AssistantRemoteError("strategy_activation_receipt_changed")
    if candidate.get("source") == "strategy_definition":
        from quant_system.research.definition_paper import (
            definition_config_fields,
            definition_schedule_available,
            load_candidate_definition,
            require_paper_costs,
        )

        try:
            if not definition_schedule_available():
                raise ValueError("strategy_definition_schedule_unavailable")
            if not candidate.get("definition_digest"):
                raise ValueError("strategy_definition_binding_required")
            definition = load_candidate_definition(
                source_path, factor_id=factor_id, universe=universe,
                expected_digest=candidate["definition_digest"],
            )
            require_paper_costs(definition, settings)
            from quant_system.research.validation_receipts import verify_candidate_validation

            if tagged:
                validation, admission_receipt = admission_v2.candidate_validation(
                    settings, candidate, expected_admission_sha=expected_admission_sha,
                )
                if admission_v2._intent(admission_receipt["protocol"])["kind"] == "replacement":
                    raise ValueError("admission_v2_replacement_requires_lifecycle")
            else:
                validation = verify_candidate_validation(
                    source_path, expected_sha=candidate.get("verification_receipt_digest"),
                    definition_digest=definition.content_digest,
                    comparison_digest=candidate.get("comparison_digest"),
                )
            _require_strategy_activation_receipt(
                candidate, source_path, validation, expected_receipt,
            )
        except (OSError, ValueError) as exc:
            raise AssistantRemoteError(str(exc)) from exc
    bound_activation_recovery = False
    if candidate.get("sleeve_id") or candidate.get("status") == "hung":
        sleeve_id = candidate.get("sleeve_id")
        if not sleeve_id:
            raise AssistantRemoteError("hung_sleeve_missing")
        api_runs_dir = Path(settings.data.data_dir) / "api_runs"
        storage = PaperStrategySleeveStorage(api_runs_dir)
        try:
            sleeve = storage.load_sleeve(str(sleeve_id))
            hung_config = storage.load_strategy_config(
                sleeve.strategy_config_id, version=sleeve.strategy_config_version,
            )
        except FileNotFoundError as exc:
            raise AssistantRemoteError("hung_sleeve_missing") from exc
        observed = sleeve.metadata.get("candidate_code_digest") or sleeve.metadata.get(
            "source_digest"
        )
        if observed != digest:
            raise AssistantRemoteError("hung_sleeve_digest_mismatch")
        if (definition is not None
                and hung_config.strategy_definition != definition.model_dump(mode="json")):
            raise AssistantRemoteError("hung_sleeve_definition_mismatch")
        if not _hang_sleeve_needs_activation_recovery(sleeve):
            return {
                "contract": HANG_CONTRACT,
                "status": "hung",
                "candidate_id": cleaned,
                "sleeve_id": sleeve_id,
                "source_digest": digest,
                "factor_id": factor_id,
                "universe": universe,
                "already_hung": True,
                "strategy_id": hung_config.strategy_id,
                "top_n": hung_config.top_n,
            }
        bound_activation_recovery = True
    if candidate.get("status") != "verified" and not bound_activation_recovery:
        raise AssistantRemoteError("candidate_not_verified")
    authoritative = admission_receipt is not None and admission_receipt["mode"] == "authoritative"
    quality_preflight = None
    if not authoritative and not bound_activation_recovery:
        from quant_system.research.admission_activation import (
            capital_requires_authoritative_job,
        )

        if capital_requires_authoritative_job(
            settings, (admission_receipt or {}).get("protocol")
        ):
            raise AssistantRemoteError("activation_parallel_capital_blocked")
        if not _v2_recovery_possible(settings, candidate):
            quality_preflight = _current_new_capital_quality(
                settings, candidate, book["candidates"],
            )
    if (
        authoritative and not bound_activation_recovery
        and not _v2_recovery_possible(settings, candidate)
    ):
        try:
            admission_v2.verify_for_new_capital(
                settings, candidate["admission_v2"], definition_digest=definition.content_digest,
                validation_sha256=candidate["verification_receipt_digest"], source_sha256=digest,
                book=book,
            )
        except (OSError, ValueError) as exc:
            raise AssistantRemoteError(str(exc)) from exc
    comparison_digest = candidate.get("comparison_digest")
    if comparison_digest is not None:
        comparison_digest = _require_digest(
            comparison_digest,
            code="candidate_comparison_digest_invalid",
        )
    if definition is not None:
        lookback = definition_config_fields(definition)["lookback"]
    elif candidate.get("source") == "registered_factor":
        registered = build_factor_registry(purpose="paper")
        if factor_id not in registered.factor_ids():
            raise AssistantRemoteError("registered_factor_not_found")
        factor = registered.create(factor_id)
        registered_source = Path(inspect.getsourcefile(type(factor)) or "")
        if not registered_source.is_file() or registered_source.resolve() != source_path:
            raise AssistantRemoteError("registered_factor_source_mismatch")
        lookback = factor.lookback
    else:
        try:
            registry = load_d34_paper_factor_registry(
                code_path=source_path,
                expected_code_digest=digest,
                expected_factor_id=factor_id,
            )
            lookback = registry.create(factor_id).lookback
        except ValueError as exc:
            raise AssistantRemoteError(str(exc)) from exc
    strategy_id, top_n = resolve_hang_sleeve_strategy(candidate, universe=universe)
    if definition is not None:
        strategy_id, top_n = "strategy_definition", definition.top_n
    api_runs_dir = Path(settings.data.data_dir) / "api_runs"
    account_storage = build_paper_account_repository(
        api_runs_dir,
        settings=settings,
    )
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    dsr: dict[str, Any] | None = None
    cost_verdict: dict[str, Any] | None = None
    max_corr: float | None = None
    service = PaperStrategySleeveService(sleeve_storage)
    try:
        with (
            account_storage.mutation_lock(),
            sleeve_storage.mutation_lock(),
            _book_mutation_lock(settings),
        ):
            locked_book = load_book(settings)
            locked_candidate = next(
                (
                    item
                    for item in locked_book["candidates"]
                    if isinstance(item, dict) and item.get("candidate_id") == cleaned
                ),
                None,
            )
            if locked_candidate is None:
                raise AssistantRemoteError("candidate_not_found")
            locked_digest = _require_digest(
                locked_candidate.get("source_digest")
                or locked_candidate.get("candidate_code_digest")
            )
            if locked_digest != expected_digest:
                raise AssistantRemoteError("candidate_source_digest_mismatch")
            try:
                admission_v2.require_protocol_lineage(settings, locked_candidate)
            except (OSError, ValueError) as exc:
                raise AssistantRemoteError(str(exc)) from exc
            if definition is not None:
                _, locked_path, locked_factor, locked_universe = _bound_source(
                    source_digest=locked_digest, source_path=locked_candidate.get("source_path"),
                    factor_id=locked_candidate.get("factor_id"),
                    universe=locked_candidate.get("universe"),
                )
                try:
                    if locked_candidate.get("source") != "strategy_definition":
                        raise ValueError("candidate_lineage_conflict")
                    current_definition = load_candidate_definition(
                        locked_path, factor_id=locked_factor, universe=locked_universe,
                        expected_digest=locked_candidate.get("definition_digest"),
                    )
                    if current_definition != definition:
                        raise ValueError("candidate_lineage_conflict")
                    if admission_v2.candidate_uses_protocol(locked_candidate) != tagged:
                        raise ValueError("admission_v2_activation_receipt_changed")
                    if tagged:
                        if locked_candidate.get("admission_v2") != candidate.get("admission_v2"):
                            raise ValueError("admission_v2_activation_receipt_changed")
                        validation, _ = admission_v2.candidate_validation(
                            settings, locked_candidate,
                            expected_admission_sha=expected_admission_sha,
                        )
                    else:
                        validation = verify_candidate_validation(
                            locked_path,
                            expected_sha=locked_candidate.get("verification_receipt_digest"),
                            definition_digest=current_definition.content_digest,
                            comparison_digest=locked_candidate.get("comparison_digest"),
                        )
                    _require_strategy_activation_receipt(
                        locked_candidate, locked_path, validation, expected_receipt,
                    )
                except (OSError, ValueError) as exc:
                    raise AssistantRemoteError(str(exc)) from exc
            if locked_candidate.get("sleeve_id") or locked_candidate.get("status") == "hung":
                existing_id = locked_candidate.get("sleeve_id")
                if not existing_id:
                    raise AssistantRemoteError("hung_sleeve_missing")
                try:
                    existing = sleeve_storage.load_sleeve(str(existing_id))
                    existing_config = sleeve_storage.load_strategy_config(
                        existing.strategy_config_id, version=existing.strategy_config_version,
                    )
                except FileNotFoundError as exc:
                    raise AssistantRemoteError("hung_sleeve_missing") from exc
                observed = existing.metadata.get("candidate_code_digest") or existing.metadata.get(
                    "source_digest"
                )
                if observed != digest:
                    raise AssistantRemoteError("hung_sleeve_digest_mismatch")
                if _hang_sleeve_needs_activation_recovery(existing):
                    _require_clean_persisted_account_allocation(account_storage)
                    account = account_storage.load()
                    if account is None:
                        raise AssistantRemoteError("existing_hang_lineage_invalid")
                    recovered = _existing_hang_sleeve(
                        account=account,
                        sleeve_storage=sleeve_storage,
                        candidate_id=cleaned,
                        digest=digest,
                        factor_id=factor_id,
                        universe=universe,
                        strategy_id=strategy_id,
                        top_n=top_n,
                        lookback=lookback,
                        definition=definition,
                    )
                    if recovered is None:
                        raise AssistantRemoteError("existing_hang_lineage_invalid")
                    existing, existing_config = recovered
                    try:
                        _activate_book_bound_hang_sleeve(
                            sleeve_storage,
                            existing,
                        )
                    except (OSError, ValueError) as exc:
                        raise AssistantRemoteError("hang_sleeve_activation_failed") from exc
                return {
                    "contract": HANG_CONTRACT,
                    "status": "hung",
                    "candidate_id": cleaned,
                    "sleeve_id": existing.sleeve_id,
                    "source_digest": digest,
                    "factor_id": factor_id,
                    "universe": universe,
                    "already_hung": True,
                    "strategy_id": existing_config.strategy_id,
                    "top_n": existing_config.top_n,
                }
            if locked_candidate.get("status") != "verified":
                raise AssistantRemoteError("candidate_not_verified")
            book = locked_book
            candidate = locked_candidate
            locked_admission = None
            if authoritative and not _v2_recovery_possible(settings, candidate):
                try:
                    locked_admission = admission_v2.verify_locked_new_capital(
                        settings, candidate["admission_v2"],
                        definition_digest=definition.content_digest,
                        validation_sha256=candidate["verification_receipt_digest"],
                        source_sha256=digest, book=book,
                    )
                except (OSError, ValueError) as exc:
                    raise AssistantRemoteError(str(exc)) from exc
            _require_clean_persisted_account_allocation(account_storage)
            account = account_storage.load()
            if account is not None:
                try:
                    sleeve_storage.reconcile_pending_sleeves(account)
                except (OSError, ValueError) as exc:
                    raise AssistantRemoteError("hang_sleeve_pending") from exc
            bound_ids = {
                str(item.get("sleeve_id"))
                for item in book["candidates"]
                if isinstance(item, dict) and item.get("sleeve_id")
            }
            unbound_remote = [
                item
                for item in sleeve_storage.list_sleeves()
                if item.sleeve_id not in bound_ids
                and item.metadata.get("mandate_id") == "remote-hang"
            ]
            recovered = None
            if account is not None:
                recovered = _existing_hang_sleeve(
                    account=account,
                    sleeve_storage=sleeve_storage,
                    candidate_id=cleaned,
                    digest=digest,
                    factor_id=factor_id,
                    universe=universe,
                    strategy_id=strategy_id,
                    top_n=top_n,
                    lookback=lookback,
                    definition=definition,
                )
            if recovered is not None:
                sleeve, config = recovered
                candidate["hung_at"] = sleeve.created_at
                # Owner decision 2026-08-21: an already-hung sleeve gets NO new
                # gates on recovery — reused admission stamps are labelled as
                # reused, not re-certified against current history. Stamps that
                # were never persisted (crash before the book save) are
                # certified now and labelled as fresh.
                existing_dsr = candidate.get("dsr")
                if isinstance(existing_dsr, dict):
                    dsr = {**existing_dsr, "recertified_at_hang": False}
                else:
                    dsr = _certify_candidate_dsr(
                        settings,
                        candidate,
                        universe=universe,
                    )
                    if dsr is None:
                        raise AssistantRemoteError("dsr_performance_required")
                    if dsr.get("passed") is not True:
                        raise AssistantRemoteError("dsr_failed")
                    dsr = {**dsr, "recertified_at_hang": True}
                existing_cost = candidate.get("cost_sensitivity")
                if isinstance(existing_cost, dict):
                    cost_verdict = {**existing_cost, "recertified_at_hang": False}
                else:
                    paper_costs = settings.paper_account
                    cost_verdict = _certify_cost_sensitivity(
                        candidate,
                        cost_bps=(paper_costs.commission_bps + paper_costs.slippage_bps),
                    )
                    if cost_verdict is None:
                        raise AssistantRemoteError("cost_unmeasured_blocked")
                    if cost_verdict.get("passed") is not True:
                        raise AssistantRemoteError("cost_sensitivity_failed")
                    cost_verdict = {**cost_verdict, "recertified_at_hang": True}
                observed_corr = sleeve.metadata.get("max_hung_correlation")
                max_corr = float(observed_corr) if observed_corr is not None else None
            else:
                if unbound_remote:
                    if any(item.metadata.get("candidate_id") == cleaned for item in unbound_remote):
                        raise AssistantRemoteError("existing_hang_lineage_invalid")
                    raise AssistantRemoteError("hang_recovery_required")
                if authoritative:
                    try:
                        admission_receipt = (
                            locked_admission or admission_v2.verify_locked_new_capital(
                                settings, candidate["admission_v2"],
                                definition_digest=definition.content_digest,
                                validation_sha256=candidate["verification_receipt_digest"],
                                source_sha256=digest, book=book,
                            )
                        )
                    except (OSError, ValueError) as exc:
                        raise AssistantRemoteError(str(exc)) from exc
                    dsr = {
                        **admission_receipt["gate"]["dsr"],
                        "admission_protocol": admission_v2.PROTOCOL_VERSION,
                    }
                    quality = admission_receipt["minimum_quality"]
                else:
                    quality = _current_new_capital_quality(
                        settings, candidate, book["candidates"], storage=sleeve_storage,
                    )
                    if quality_preflight is not None and quality != quality_preflight:
                        raise AssistantRemoteError("new_capital_evidence_changed")
                    dsr = quality["dsr"]
                if dsr is None:
                    raise AssistantRemoteError("dsr_performance_required")
                if dsr.get("passed") is not True:
                    raise AssistantRemoteError("dsr_failed")
                _current_exposure_candidates(settings, book["candidates"], storage=sleeve_storage)
                max_corr = quality["concentration"]["raw_max"]
                if max_corr is not None and max_corr > FACTOR_CORRELATION_MAX:
                    raise AssistantRemoteError("correlated_duplicate")
                cost_verdict = quality["cost"]
                if cost_verdict is None:
                    raise AssistantRemoteError("cost_unmeasured_blocked")
                if cost_verdict.get("passed") is not True:
                    raise AssistantRemoteError("cost_sensitivity_failed")
                dsr = {**dsr, "recertified_at_hang": True}
                cost_verdict = {**cost_verdict, "recertified_at_hang": True}
                candidate["new_capital_quality_snapshot"] = quality
                if account is None:
                    account = account_storage.load_or_open(initial_cash=1_000_000)
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
                    "max_hung_correlation": max_corr,
                }
                display_name_zh, summary_zh = _candidate_presentation_zh(
                    {**candidate, "status": "hung"}
                )
                metadata["display_name_zh"] = display_name_zh
                metadata["summary_zh"] = summary_zh
                if comparison_digest is not None:
                    metadata["comparison_digest"] = comparison_digest
                metadata["dsr_value"] = dsr.get("value")
                metadata["dsr_n_trials"] = dsr.get("n_trials")
                if account.manual_available_cash() + 1e-9 < _HANG_ALLOCATION_CASH:
                    raise AssistantRemoteError("hang_insufficient_funds")
                config_fields = dict(
                    strategy_id=strategy_id,
                    symbols=universe,
                    factor_ids=[factor_id],
                    weights={factor_id: 1.0},
                    lookback=lookback,
                    top_n=top_n,
                    rebalance_frequency="daily",
                    max_weight_per_symbol=0.99,
                    min_order_value=100.0,
                    data_provider="futu",
                    execution_timing="next_open",
                )
                if definition is not None:
                    config_fields = definition_config_fields(definition)
                    metadata.update({
                        "definition_digest": definition.content_digest,
                        "reference_initial_cash": definition.initial_cash,
                        "simulation_allocation_usd": _HANG_ALLOCATION_CASH,
                    })
                config = StrategyConfig.create(
                    name=display_name_zh, description=summary_zh,
                    universe_id=f"remote:{cleaned}", **config_fields,
                    metadata=metadata,
                )
                try:
                    sleeve_storage.save_strategy_config(config)
                except (OSError, FileExistsError) as exc:
                    raise AssistantRemoteError("hang_strategy_config_persist_failed") from exc
                try:
                    sleeve = service.create_sleeve(
                        account,
                        config=config,
                        mode=StrategySleeveMode.ALLOCATED,
                        allocated_cash=_HANG_ALLOCATION_CASH,
                        metadata=metadata,
                    )
                except CashAllocationError as exc:
                    raise AssistantRemoteError("hang_insufficient_funds") from exc
                sleeve.status = StrategySleeveStatus.PAUSED
                sleeve.paused_at = _utc_now()
                sleeve.metadata = {
                    **dict(sleeve.metadata),
                    "hang_activation_state": _HANG_ACTIVATION_PENDING,
                    "official_observation": False,
                }
                try:
                    sleeve_storage.save_pending_sleeve(sleeve)
                except OSError as exc:
                    raise AssistantRemoteError("hang_sleeve_persist_failed") from exc
                try:
                    account_storage.save(account)
                except Exception as exc:  # noqa: BLE001 - map repository failures
                    try:
                        persisted = account_storage.load()
                    except Exception as load_exc:  # noqa: BLE001 - outcome unknown
                        raise AssistantRemoteError("hang_account_outcome_unknown") from load_exc
                    persisted_allocation = (
                        persisted.sleeve_cash.get(sleeve.sleeve_id)
                        if persisted is not None
                        else None
                    )
                    persisted_events = (
                        [
                            entry
                            for entry in persisted.ledger
                            if entry.kind == "sleeve_cash_allocated"
                            and entry.source == f"strategy:{sleeve.sleeve_id}"
                        ]
                        if persisted is not None
                        else []
                    )
                    if (
                        persisted_allocation is not None
                        and abs(float(persisted_allocation) - float(sleeve.cash)) <= 1e-7
                        and len(persisted_events) == 1
                    ):
                        raise AssistantRemoteError("hang_account_outcome_unknown") from exc
                    sleeve_storage.discard_pending_sleeve(sleeve.sleeve_id)
                    raise AssistantRemoteError("hang_account_persist_failed") from exc
                try:
                    sleeve_storage.finalize_pending_sleeve(sleeve.sleeve_id)
                except (OSError, ValueError) as exc:
                    raise AssistantRemoteError("hang_sleeve_pending") from exc
            candidate["status"] = "hung"
            candidate["sleeve_id"] = sleeve.sleeve_id
            candidate["source_digest"] = digest
            candidate["candidate_code_digest"] = digest
            candidate["factor_id"] = factor_id
            candidate["universe"] = universe
            candidate.setdefault("hung_at", _utc_now())
            if isinstance(dsr, dict):
                candidate["dsr"] = dsr
            if isinstance(cost_verdict, dict):
                candidate["cost_sensitivity"] = cost_verdict
            try:
                save_book(settings, book)
            except OSError as exc:
                raise AssistantRemoteError("hang_book_persist_failed") from exc
            try:
                _activate_book_bound_hang_sleeve(sleeve_storage, sleeve)
            except (OSError, ValueError) as exc:
                raise AssistantRemoteError("hang_sleeve_activation_failed") from exc
    except PaperAccountBootstrapRequired as exc:
        raise AssistantRemoteError("paper_account_bootstrap_required") from exc
    except TimeoutError as exc:
        raise AssistantRemoteError("hang_lock_timeout") from exc
    except RuntimeError as exc:
        raise AssistantRemoteError("paper_account_unavailable") from exc
    return {
        "contract": HANG_CONTRACT,
        "status": "hung",
        "candidate_id": cleaned,
        "sleeve_id": sleeve.sleeve_id,
        "source_digest": digest,
        "factor_id": factor_id,
        "universe": universe,
        "dsr": dsr,
        "max_hung_correlation": max_corr,
        "already_hung": False,
        "strategy_id": strategy_id,
        "top_n": top_n,
    }


_FACTOR_ID_ASSIGN_RE = re.compile(r"factor_id\s*=\s*['\"]([a-z][a-z0-9_-]{0,127})['\"]")


def record_verified_from_dual_engine_artifact(
    settings: Settings,
    *,
    artifact_id: str,
    source_path: str | Path,
    source_digest: str,
    comparison_digest: str,
    universe: Sequence[str],
    objective: str,
    job_key: str | None = None,
    top_n: int | None = None,
    operator: str | None = None,
    strategy_id: str | None = None,
    daily_returns: Sequence[float] | None = None,
    turnover_period: float | None = None,
    return_dates: Sequence[str] | None = None,
    evidence_ref: CandidateEvidenceRef,
) -> dict[str, Any]:
    """Admit a dual-engine qualified artifact as a verified candidate. Never hangs."""

    path = Path(source_path)
    digest = _require_digest(source_digest)
    if not path.is_file():
        raise AssistantRemoteError("candidate_source_unavailable")
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != digest:
        raise AssistantRemoteError("candidate_source_digest_mismatch")
    match = _FACTOR_ID_ASSIGN_RE.search(source.decode("utf-8"))
    if match is None:
        raise AssistantRemoteError("candidate_factor_required")
    factor_id = match.group(1)
    try:
        load_d34_paper_factor_registry(
            code_path=path,
            expected_code_digest=digest,
            expected_factor_id=factor_id,
        )
    except ValueError as exc:
        raise AssistantRemoteError(str(exc)) from exc
    candidate_id = f"artifact-{digest[:16]}"
    if daily_returns is None or turnover_period is None or return_dates is None:
        raise AssistantRemoteError("research_bound_performance_required")
    record = record_verified_candidate(
        settings,
        candidate_id=candidate_id,
        objective=objective,
        source="d34_artifact",
        source_digest=digest,
        source_path=str(path.resolve()),
        factor_id=factor_id,
        universe=universe,
        artifact_id=artifact_id,
        comparison_digest=comparison_digest,
        daily_returns=daily_returns,
        turnover_period=turnover_period,
        return_dates=return_dates,
        strategy_id=strategy_id,
        top_n=top_n,
        operator=operator,
        evidence_ref=evidence_ref,
        require_admission_gates=True,
    )
    if job_key:
        with _book_mutation_lock(settings):
            book = load_book(settings)
            for item in book["candidates"]:
                if isinstance(item, dict) and item.get("candidate_id") == record["candidate_id"]:
                    item["job_key"] = job_key
                    record = item
            save_book(settings, book)
    return record


def _research_material_digest(
    *,
    note: str,
    formula: str,
    universe: Sequence[str],
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "note": note,
                "formula": formula,
                "universe": list(universe),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _research_operation_id(
    *,
    platform_session_id: str,
    hermes_session_id: str,
    material_digest: str,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "contract": RESEARCH_OPERATION_ID_CONTRACT,
                "hermes_session_id": hermes_session_id,
                "material_digest": material_digest,
                "platform_session_id": platform_session_id,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _require_research_identity(value: object, *, code: str) -> str:
    cleaned = str(value or "").strip()
    if not 1 <= len(cleaned) <= 255:
        raise AssistantRemoteError(code)
    return cleaned


def _research_request_projection(item: Mapping[str, Any]) -> dict[str, Any]:
    projection = {
        "contract": RESEARCH_OPERATION_CONTRACT,
        "operation_id": item["operation_id"],
        "material_digest": item["material_digest"],
        "request_id": item["request_id"],
        "job_id": item["job_id"],
        "job_key": item["job_key"],
        "status": item["status"],
        "terminal": item.get("terminal") is True,
        "outcome": item.get("outcome") or str(item["status"]),
        "result_reply": dict(item["result_reply"]),
        "command_id": item["command_id"],
        "platform_session_id": item["platform_session_id"],
        "hermes_session_id": item["hermes_session_id"],
        "hermes_run_id": item["hermes_run_id"],
        "evidence": (dict(item["evidence"]) if isinstance(item.get("evidence"), dict) else None),
    }
    candidate_id = item.get("candidate_id")
    source_digest = item.get("source_digest")
    if candidate_id is not None:
        projection["candidate_id"] = candidate_id
    if source_digest is not None:
        projection["source_digest"] = source_digest
    return projection


def project_research_request(
    settings: Settings,
    *,
    operation_id: str,
) -> dict[str, Any] | None:
    """Read one chat-research operation without reconciling or writing."""

    cleaned_operation = _require_digest(
        operation_id,
        code="research_operation_id_required",
    )
    book = load_book(settings)
    item = next(
        (
            request
            for request in book["requests"]
            if isinstance(request, dict) and request.get("operation_id") == cleaned_operation
        ),
        None,
    )
    return None if item is None else _research_request_projection(item)


def project_research_evidence(
    settings: Settings,
    *,
    operation_id: str,
    manifest_digest: str,
) -> dict[str, Any] | None:
    projection = project_research_request(settings, operation_id=operation_id)
    if projection is None:
        return None
    evidence = projection.get("evidence")
    cleaned_digest = _require_digest(
        manifest_digest,
        code="research_evidence_digest_required",
    )
    if not isinstance(evidence, dict) or evidence.get("manifest_digest") != cleaned_digest:
        return None
    return {
        "contract": "hqa.assistant_remote_evidence/v1",
        "operation_id": projection["operation_id"],
        "material_digest": projection["material_digest"],
        "status": projection["status"],
        "outcome": projection["outcome"],
        "candidate_id": projection.get("candidate_id"),
        "source_digest": projection.get("source_digest"),
        "evidence": dict(evidence),
    }


def intake_research_operation(
    settings: Settings,
    *,
    jobs: Any,
    operation_id: str,
    material_digest: str,
    command_id: str,
    platform_session_id: str,
    hermes_session_id: str,
    hermes_run_id: str,
    note: str,
    formula: str,
    universe: Sequence[str],
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Enqueue one digest-stable chat research operation. Never hangs."""

    cleaned_operation = _require_digest(
        operation_id,
        code="research_operation_id_required",
    )
    supplied_material_digest = _require_digest(
        material_digest,
        code="research_material_digest_required",
    )
    attempt_identities = {
        "command_id": _require_research_identity(command_id, code="research_command_id_required"),
        "hermes_run_id": _require_research_identity(
            hermes_run_id, code="research_hermes_run_id_required"
        ),
    }
    session_identities = {
        "platform_session_id": _require_research_identity(
            platform_session_id,
            code="research_platform_session_id_required",
        ),
        "hermes_session_id": _require_research_identity(
            hermes_session_id,
            code="research_hermes_session_id_required",
        ),
    }
    expected_operation = _research_operation_id(
        platform_session_id=session_identities["platform_session_id"],
        hermes_session_id=session_identities["hermes_session_id"],
        material_digest=supplied_material_digest,
    )
    if cleaned_operation != expected_operation:
        raise AssistantRemoteError("research_operation_id_mismatch")
    cleaned_note = note.strip()
    if len(cleaned_note) < 8:
        raise AssistantRemoteError("research_objective_required")
    cleaned_formula = formula.strip()
    if not cleaned_formula:
        raise AssistantRemoteError("intake_formula_required")
    symbols = _require_universe(universe)
    observed_material_digest = _research_material_digest(
        note=cleaned_note,
        formula=cleaned_formula,
        universe=symbols,
    )
    if observed_material_digest != supplied_material_digest:
        raise AssistantRemoteError("research_material_digest_mismatch")
    try:
        compile_qlib_expr(cleaned_formula)
    except QlibExprError as exc:
        raise AssistantRemoteError("research_formula_unsupported") from exc
    objective = f"{cleaned_note}\nformula: {cleaned_formula}\nuniverse: {','.join(symbols)}"
    with _book_mutation_lock(settings):
        book = load_book(settings)
        existing = next(
            (
                item
                for item in book["requests"]
                if isinstance(item, dict) and item.get("operation_id") == cleaned_operation
            ),
            None,
        )
        if existing is not None:
            if existing.get("material_digest") != supplied_material_digest or any(
                existing.get(key) != value for key, value in session_identities.items()
            ):
                raise AssistantRemoteError("research_operation_conflict")
            if any(existing.get(key) != value for key, value in attempt_identities.items()):
                existing.update(attempt_identities)
                existing["updated_at"] = _utc_now()
                save_book(settings, book)
            return _research_request_projection(existing)
        active = [
            item
            for item in book["requests"]
            if isinstance(item, dict)
            and item.get("job_key")
            and str(item.get("status")) in _ACTIVE_JOB_REQUEST_STATUSES
        ]
        if active:
            raise AssistantRemoteError("research_job_already_active")
        job_key = f"assistant-remote:{cleaned_operation}"
        input_document = build_owner_request_input(
            objective=objective,
            universe=symbols,
        )
        input_document.update(
            {
                "formula": cleaned_formula,
                "operation_id": cleaned_operation,
                "material_digest": supplied_material_digest,
                "job_key": job_key,
                **session_identities,
            }
        )
        job_input_digest = digest_document(input_document)
        job = jobs.enqueue(
            EnqueueJobCommand(
                resource_envelope_id=LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
                workspace_id=workspace_id,
                job_key=job_key,
                input_digest=job_input_digest,
                input_document=input_document,
                budget_reserved_usd=DEFAULT_JOB_RESERVATION_USD,
                max_attempts=1,
            )
        )
        job_id = str(_job_row_field(job, "job_id") or "").strip()
        observed_job_key = str(_job_row_field(job, "job_key") or "").strip()
        if not job_id.startswith("job-") or observed_job_key != job_key:
            raise AssistantRemoteError("research_job_enqueue_failed")
        request_id = f"request-{cleaned_operation[:12]}"
        provenance = {
            "operation_id": cleaned_operation,
            "material_digest": supplied_material_digest,
            "job_id": job_id,
            "job_key": job_key,
        }
        record = {
            "request_id": request_id,
            "objective": objective,
            "status": "queued",
            "job_key": job_key,
            "job_id": job_id,
            "job_input_digest": job_input_digest,
            "operation_id": cleaned_operation,
            "material_digest": supplied_material_digest,
            "universe": symbols,
            **session_identities,
            **attempt_identities,
            "terminal": False,
            "outcome": "queued",
            "result_reply": {
                "status": "queued",
                "code": "research_queued",
                "message": "Research request queued.",
                "provenance": provenance,
            },
            "evidence": None,
            "created_at": _utc_now(),
        }
        book["requests"].insert(0, record)
        save_book(settings, book)
        return _research_request_projection(record)


def _d34_job_roots(settings: Settings) -> tuple[Path, ...]:
    data_dir = Path(settings.data.data_dir)
    return (
        data_dir / "d34" / "jobs",
        data_dir / "_runtime" / "d34" / "jobs",
    )


def _research_job_root(settings: Settings, *, job_id: str) -> Path | None:
    cleaned = job_id.strip()
    if not cleaned.startswith("job-") or len(cleaned) > 200:
        raise AssistantRemoteError("research_job_id_required")
    matches = [
        candidate
        for root in _d34_job_roots(settings)
        for candidate in (root / cleaned,)
        if candidate.is_dir()
        and not candidate.is_symlink()
        and candidate.resolve().parent == root.resolve()
    ]
    if len(matches) > 1:
        raise AssistantRemoteError("research_result_ambiguous")
    return matches[0] if matches else None


def _load_json_mapping(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _strict_json_mapping(path: Path) -> dict[str, Any] | None:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise ValueError("duplicate JSON field")
            document[key] = value
        return document

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _write_strict_json(path: Path, document: Mapping[str, Any]) -> None:
    raw = (
        json.dumps(
            dict(document),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def _recover_terminal_bundle(job_root: Path) -> dict[str, Any] | None:
    bundle = _strict_json_mapping(job_root / "terminal_bundle.json")
    if bundle is None:
        return None
    bundle_digest = str(bundle.pop("bundle_digest", ""))
    cycle = bundle.get("cycle_receipt")
    evidence = bundle.get("evidence_manifest")
    if (
        set(bundle) != {"contract", "job_id", "cycle_receipt", "evidence_manifest"}
        or bundle.get("contract") != "hqa.d34_terminal_bundle/v1"
        or bundle_digest != digest_document(bundle)
        or not isinstance(cycle, dict)
        or not isinstance(evidence, dict)
        or cycle.get("job_id") != bundle.get("job_id")
        or evidence.get("job_id") != bundle.get("job_id")
    ):
        raise AssistantRemoteError("research_terminal_bundle_invalid")
    unsigned_evidence = dict(evidence)
    manifest_digest = str(unsigned_evidence.pop("manifest_digest", ""))
    if manifest_digest != digest_document(unsigned_evidence) or unsigned_evidence.get(
        "cycle_receipt_digest"
    ) != digest_document(cycle):
        raise AssistantRemoteError("research_terminal_bundle_invalid")
    for path, expected in (
        (job_root / "cycle_receipt.json", cycle),
        (job_root / "evidence_manifest.json", evidence),
    ):
        existing = _strict_json_mapping(path)
        if existing is None:
            if path.exists():
                raise AssistantRemoteError("research_terminal_bundle_conflict")
            _write_strict_json(path, expected)
        elif existing != expected:
            raise AssistantRemoteError("research_terminal_bundle_conflict")
    return cycle


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job_evidence_path(
    job_root: Path,
    raw: object,
    *,
    require_research: bool = False,
) -> Path:
    relative = Path(str(raw or ""))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise AssistantRemoteError("research_evidence_path_invalid")
    candidate = job_root / relative
    resolved = candidate.resolve()
    authority = (job_root / "research").resolve() if require_research else job_root.resolve()
    try:
        resolved.relative_to(authority)
    except ValueError as exc:
        raise AssistantRemoteError("research_evidence_path_invalid") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise AssistantRemoteError("research_evidence_path_invalid")
    return candidate


def _bound_engine_receipt(
    path: Path,
    *,
    job_root: Path,
    job_id: str,
    run_id: str,
    resource_envelope_id: str,
    engine: str,
) -> dict[str, Any]:
    document = _strict_json_mapping(path)
    if document is None:
        raise AssistantRemoteError("research_engine_receipt_invalid")
    receipt_digest = str(document.pop("receipt_digest", ""))
    engine_receipt = document.get("engine_receipt")
    raw_path = _job_evidence_path(job_root, document.get("raw_receipt_path"))
    raw_document = _strict_json_mapping(raw_path)
    if raw_document is None:
        raise AssistantRemoteError("research_engine_receipt_invalid")
    raw_receipt_digest = str(raw_document.pop("receipt_digest", ""))
    raw_daily_returns = raw_document.get("daily_returns")
    raw_terminal_nav = raw_document.get("terminal_nav")
    raw_terminal_weights = raw_document.get("terminal_weights")
    engine_daily_returns = (
        engine_receipt.get("daily_returns") if isinstance(engine_receipt, dict) else None
    )
    engine_terminal_nav = (
        engine_receipt.get("terminal_nav") if isinstance(engine_receipt, dict) else None
    )
    engine_terminal_weights = (
        engine_receipt.get("terminal_weights") if isinstance(engine_receipt, dict) else None
    )

    def finite_number(value: object) -> bool:
        return type(value) in {int, float} and math.isfinite(float(value))

    def finite_number_list(value: object) -> bool:
        return type(value) is list and bool(value) and all(finite_number(item) for item in value)

    def finite_weight_map(value: object) -> bool:
        return type(value) is dict and all(
            type(symbol) is str and bool(symbol) and finite_number(weight)
            for symbol, weight in value.items()
        )

    if (
        set(document)
        != {
            "contract",
            "job_id",
            "run_id",
            "resource_envelope_id",
            "engine",
            "raw_receipt_path",
            "raw_receipt_file_digest",
            "engine_receipt",
            "turnover_period",
        }
        or document.get("contract") != "hqa.d34_bound_engine_receipt/v2"
        or document.get("job_id") != job_id
        or document.get("run_id") != run_id
        or document.get("resource_envelope_id") != resource_envelope_id
        or document.get("engine") != engine
        or receipt_digest != digest_document(document)
        or _file_sha256(raw_path) != document.get("raw_receipt_file_digest")
        or raw_receipt_digest != digest_document(raw_document)
        or raw_document.get("contract") != "hqa.d34_engine_receipt/v1"
        or raw_document.get("engine") != engine
        or raw_document.get("job_id") != job_id
        or raw_document.get("run_id") != run_id
        or not isinstance(engine_receipt, dict)
        or set(engine_receipt)
        != {
            "engine",
            "snapshot_digest",
            "universe_digest",
            "calendar_digest",
            "target_weights_digest",
            "daily_returns",
            "return_dates",
            "terminal_nav",
            "terminal_weights",
            "receipt_digest",
        }
        or engine_receipt.get("engine") != engine
        or engine_receipt.get("receipt_digest") != raw_receipt_digest
        or not finite_number_list(raw_daily_returns)
        or not finite_number(raw_terminal_nav)
        or not finite_weight_map(raw_terminal_weights)
        or not finite_number_list(engine_daily_returns)
        or not finite_number(engine_terminal_nav)
        or not finite_weight_map(engine_terminal_weights)
        or not isinstance(engine_receipt.get("return_dates"), list)
        or len(engine_receipt["daily_returns"]) != len(engine_receipt["return_dates"])
        or any(
            raw_document.get(key) != engine_receipt.get(key)
            for key in (
                "snapshot_digest",
                "universe_digest",
                "calendar_digest",
                "target_weights_digest",
                "daily_returns",
                "return_dates",
                "terminal_nav",
                "terminal_weights",
            )
        )
    ):
        raise AssistantRemoteError("research_engine_receipt_invalid")
    try:
        validate_xnys_calendar(engine_receipt["return_dates"])
    except (TypeError, ValueError) as exc:
        raise AssistantRemoteError("research_engine_receipt_invalid") from exc
    turnover = document.get("turnover_period")
    if turnover is not None:
        if not finite_number(turnover) or float(turnover) < 0:
            raise AssistantRemoteError("research_engine_receipt_invalid")
        turnover = float(turnover)
    return {
        "engine_receipt": engine_receipt,
        "turnover_period": turnover,
        "raw_receipt_path": raw_path,
        "raw_receipt_digest": raw_receipt_digest,
        "raw_document": raw_document,
    }


def verify_registered_factor(
    settings: Settings,
    *,
    factor_id: str,
    universe: Sequence[str],
    boundary: Any | None = None,
    now: Any | None = None,
) -> dict[str, Any]:
    """Generate, verify and admit one registered factor; never hangs."""

    from quant_system.d34.registered_verification import (
        RegisteredVerificationError,
        generate_registered_factor_evidence,
        registered_factor_spec,
    )

    cleaned_factor_id = _require_factor_id(factor_id)
    symbols = _require_universe(universe)
    kwargs: dict[str, Any] = {
        "factor_id": cleaned_factor_id,
        "universe": symbols,
        "boundary": boundary,
    }
    if now is not None:
        kwargs["now"] = now
    try:
        evidence = generate_registered_factor_evidence(settings, **kwargs)
    except RegisteredVerificationError as exc:
        raise AssistantRemoteError(exc.code) from exc
    manifest = dict(evidence.manifest)
    manifest_digest = str(manifest.pop("manifest_digest", ""))
    expected_fields = {
        "contract",
        "job_id",
        "run_id",
        "factor_id",
        "factor_identity_digest",
        "source_digest",
        "compute_source_digest",
        "qlib_expression",
        "qlib_expression_digest",
        "universe",
        "market_session",
        "source_path",
        "source_file_digest",
        "snapshot_path",
        "snapshot_file_digest",
        "snapshot_digest",
        "calendar",
        "calendar_digest",
        "qlib_receipt_path",
        "qlib_receipt_file_digest",
        "qlib_receipt_digest",
        "qlib_bound_path",
        "qlib_bound_file_digest",
        "platform_receipt_path",
        "platform_receipt_file_digest",
        "platform_receipt_digest",
        "platform_bound_path",
        "platform_bound_file_digest",
        "comparison_digest",
        "comparison",
        "turnover_period",
        "cost_model",
    }
    if (
        set(manifest) != expected_fields
        or manifest.get("contract") != "hqa.registered_factor_evidence/v1"
        or manifest_digest != digest_document(manifest)
        or manifest.get("job_id") != evidence.job_id
        or manifest.get("run_id") != evidence.run_id
        or manifest.get("factor_id") != cleaned_factor_id
        or manifest.get("universe") != symbols
        or manifest.get("calendar_digest") != digest_document(manifest.get("calendar"))
    ):
        raise AssistantRemoteError("registered_evidence_invalid")
    try:
        validate_xnys_calendar(list(manifest["calendar"]))
    except (TypeError, ValueError) as exc:
        raise AssistantRemoteError("registered_evidence_calendar_invalid") from exc
    registry = build_factor_registry(purpose="paper")
    if cleaned_factor_id not in registry.factor_ids():
        raise AssistantRemoteError("registered_factor_not_found")
    factor = registry.create(cleaned_factor_id)
    try:
        factor_spec = registered_factor_spec(factor)
    except RegisteredVerificationError as exc:
        raise AssistantRemoteError(exc.code) from exc
    source_file = Path(inspect.getsourcefile(type(factor)) or "")
    source_copy = evidence.root / str(manifest["source_path"])
    source_digest = _require_digest(
        manifest.get("source_digest"),
        code="registered_factor_source_digest_invalid",
    )
    if (
        not source_file.is_file()
        or _file_sha256(source_file) != source_digest
        or _file_sha256(source_copy) != source_digest
        or manifest.get("source_file_digest") != source_digest
        or manifest.get("compute_source_digest") != factor_spec.compute_source_digest
        or manifest.get("qlib_expression") != factor_spec.qlib_expression
        or manifest.get("qlib_expression_digest") != factor_spec.expression_digest
        or manifest.get("factor_identity_digest")
        != digest_document(
            {
                "contract": "hqa.registered_factor_identity/v1",
                "compute_source_digest": factor_spec.compute_source_digest,
                "expression_digest": factor_spec.expression_digest,
                "factor_id": cleaned_factor_id,
                "source_digest": source_digest,
            }
        )
    ):
        raise AssistantRemoteError("registered_factor_source_mismatch")
    qlib_bound_path = _job_evidence_path(evidence.root, manifest["qlib_bound_path"])
    platform_bound_path = _job_evidence_path(evidence.root, manifest["platform_bound_path"])
    qlib = _bound_engine_receipt(
        qlib_bound_path,
        job_root=evidence.root,
        job_id=evidence.job_id,
        run_id=evidence.run_id,
        resource_envelope_id=LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
        engine="qlib",
    )
    platform = _bound_engine_receipt(
        platform_bound_path,
        job_root=evidence.root,
        job_id=evidence.job_id,
        run_id=evidence.run_id,
        resource_envelope_id=LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
        engine="platform",
    )
    qlib_receipt = qlib["engine_receipt"]
    platform_receipt = platform["engine_receipt"]
    qlib_raw = qlib["raw_document"]
    qlib_config = qlib_raw.get("qlib_config") if isinstance(qlib_raw, dict) else None
    if (
        qlib_receipt["return_dates"] != manifest["calendar"]
        or platform_receipt["return_dates"] != manifest["calendar"]
        or qlib["raw_receipt_digest"] != manifest["qlib_receipt_digest"]
        or platform["raw_receipt_digest"] != manifest["platform_receipt_digest"]
        or not isinstance(qlib_raw, dict)
        or qlib_raw.get("factor_id") != cleaned_factor_id
        or qlib_raw.get("source_digest") != source_digest
        or not isinstance(qlib_config, dict)
        or qlib_config.get("expression") != factor_spec.qlib_expression
        or qlib_raw.get("qlib_config_digest") != digest_document(qlib_config)
    ):
        raise AssistantRemoteError("registered_engine_receipt_mismatch")
    comparison = compare_engine_receipts(
        qlib=EngineReceipt(
            engine="qlib",
            snapshot_digest=qlib_receipt["snapshot_digest"],
            universe_digest=qlib_receipt["universe_digest"],
            calendar_digest=qlib_receipt["calendar_digest"],
            target_weights_digest=qlib_receipt["target_weights_digest"],
            daily_returns=tuple(qlib_receipt["daily_returns"]),
            return_dates=tuple(qlib_receipt["return_dates"]),
            terminal_nav=float(qlib_receipt["terminal_nav"]),
            terminal_weights=dict(qlib_receipt["terminal_weights"]),
            receipt_digest=qlib_receipt["receipt_digest"],
        ),
        platform=EngineReceipt(
            engine="platform",
            snapshot_digest=platform_receipt["snapshot_digest"],
            universe_digest=platform_receipt["universe_digest"],
            calendar_digest=platform_receipt["calendar_digest"],
            target_weights_digest=platform_receipt["target_weights_digest"],
            daily_returns=tuple(platform_receipt["daily_returns"]),
            return_dates=tuple(platform_receipt["return_dates"]),
            terminal_nav=float(platform_receipt["terminal_nav"]),
            terminal_weights=dict(platform_receipt["terminal_weights"]),
            receipt_digest=platform_receipt["receipt_digest"],
        ),
        policy=ComparisonPolicy.initial(),
    )
    if (
        not comparison.accepted
        or comparison.comparison_digest != manifest.get("comparison_digest")
        or manifest.get("comparison")
        != {
            "accepted": True,
            "daily_return_correlation": comparison.daily_return_correlation,
            "terminal_nav_difference_bps": comparison.terminal_nav_difference_bps,
            "max_symbol_weight_difference_bps": comparison.max_symbol_weight_difference_bps,
        }
        or manifest.get("cost_model")
        != {
            "commission_bps": settings.paper_account.commission_bps,
            "slippage_bps": settings.paper_account.slippage_bps,
        }
    ):
        raise AssistantRemoteError("registered_factor_dual_engine_rejected")
    turnover = manifest.get("turnover_period")
    if type(turnover) not in {int, float} or not math.isfinite(float(turnover)):
        raise AssistantRemoteError("registered_factor_turnover_invalid")
    return record_verified_candidate(
        settings,
        candidate_id=(f"artifact-{evidence.job_id.removeprefix('job-registered-')}"),
        objective=f"Verify registered factor {cleaned_factor_id}",
        source="registered_factor",
        source_digest=source_digest,
        source_path=str(source_file.resolve()),
        factor_id=cleaned_factor_id,
        universe=symbols,
        artifact_id=f"registered-{manifest_digest[:16]}",
        comparison_digest=comparison.comparison_digest,
        daily_returns=platform_receipt["daily_returns"],
        turnover_period=float(turnover),
        return_dates=platform_receipt["return_dates"],
        verification_receipt_digest=manifest_digest,
        evidence_ref=CandidateEvidenceRef(
            job_id=evidence.job_id,
            run_id=evidence.run_id,
            manifest_digest=manifest_digest,
            qlib_raw_receipt_digest=str(manifest["qlib_receipt_digest"]),
            platform_raw_receipt_digest=str(manifest["platform_receipt_digest"]),
        ),
        require_admission_gates=True,
    )


def _verified_research_evidence(
    *,
    settings: Settings,
    job_root: Path,
    request: Mapping[str, Any],
    cycle: Mapping[str, Any],
    registry: Any,
) -> dict[str, Any]:
    manifest = _strict_json_mapping(job_root / "evidence_manifest.json")
    if manifest is None:
        raise AssistantRemoteError("research_evidence_manifest_missing")
    manifest_digest = str(manifest.pop("manifest_digest", ""))
    expected_fields = {
        "contract",
        "job_id",
        "run_id",
        "job_key",
        "operation_id",
        "material_digest",
        "job_input_digest",
        "research_request_digest",
        "cycle_receipt_digest",
        "terminal_recovery_digest",
        "artifact_id",
        "artifact_version",
        "candidate_code_path",
        "candidate_code_digest",
        "qlib_receipt_path",
        "qlib_receipt_file_digest",
        "qlib_receipt_digest",
        "qlib_raw_receipt_path",
        "qlib_raw_receipt_file_digest",
        "platform_receipt_path",
        "platform_receipt_file_digest",
        "platform_receipt_digest",
        "platform_raw_receipt_path",
        "platform_raw_receipt_file_digest",
        "comparison_digest",
        "comparison",
        "cost_model",
    }
    if (
        set(manifest) != expected_fields
        or manifest.get("contract") != "hqa.d34_research_evidence/v1"
        or manifest_digest != digest_document(manifest)
        or manifest.get("job_id") != request.get("job_id")
        or manifest.get("job_key") != request.get("job_key")
        or manifest.get("operation_id") != request.get("operation_id")
        or manifest.get("material_digest") != request.get("material_digest")
        or manifest.get("cycle_receipt_digest") != digest_document(dict(cycle))
    ):
        raise AssistantRemoteError("research_evidence_manifest_invalid")

    input_receipt = _strict_json_mapping(job_root / "job_input.json")
    if input_receipt is None:
        raise AssistantRemoteError("research_job_input_receipt_missing")
    input_receipt_digest = str(input_receipt.pop("receipt_digest", ""))
    input_document = input_receipt.get("input_document")
    if (
        set(input_receipt) != {"contract", "job_id", "input_digest", "input_document"}
        or input_receipt.get("contract") != "hqa.d34_job_input_receipt/v1"
        or input_receipt.get("job_id") != request.get("job_id")
        or input_receipt_digest != digest_document(input_receipt)
        or input_receipt.get("input_digest") != manifest.get("job_input_digest")
        or not isinstance(input_document, dict)
        or digest_document(input_document) != manifest.get("job_input_digest")
        or input_document.get("operation_id") != request.get("operation_id")
        or input_document.get("material_digest") != request.get("material_digest")
        or input_document.get("platform_session_id") != request.get("platform_session_id")
        or input_document.get("hermes_session_id") != request.get("hermes_session_id")
        or input_document.get("job_key") != request.get("job_key")
        or input_document.get("research_only") is not True
        or input_document.get("paper_execution_allowed") is not False
    ):
        raise AssistantRemoteError("research_job_input_receipt_invalid")

    research_request = _strict_json_mapping(job_root / "research_request.json")
    if (
        research_request is None
        or digest_document(research_request) != manifest.get("research_request_digest")
        or research_request.get("job_id") != request.get("job_id")
        or research_request.get("run_id") != manifest.get("run_id")
        or research_request.get("job_key") != request.get("job_key")
        or research_request.get("objective") != request.get("objective")
        or research_request.get("universe") != request.get("universe")
    ):
        raise AssistantRemoteError("research_result_request_mismatch")

    recovery = _strict_json_mapping(job_root / "terminal_recovery.json")
    if recovery is None:
        raise AssistantRemoteError("research_terminal_recovery_missing")
    recovery_digest = str(recovery.pop("recovery_digest", ""))
    qlib_receipt = recovery.get("qlib_receipt")
    platform_receipt = recovery.get("platform_receipt")
    comparison = recovery.get("comparison")
    manifest_comparison = manifest.get("comparison")
    cost_model = manifest.get("cost_model")
    if (
        recovery_digest != digest_document(recovery)
        or recovery_digest != manifest.get("terminal_recovery_digest")
        or recovery.get("job_id") != request.get("job_id")
        or recovery.get("run_id") != manifest.get("run_id")
        or recovery.get("resource_envelope_id") != input_document.get("resource_envelope_id")
        or recovery.get("resource_policy_digest") != input_document.get("resource_policy_digest")
        or recovery.get("universe") != request.get("universe")
        or not isinstance(qlib_receipt, dict)
        or not isinstance(platform_receipt, dict)
        or not isinstance(comparison, dict)
        or not isinstance(manifest_comparison, dict)
        or not isinstance(cost_model, dict)
        or qlib_receipt.get("receipt_digest") != manifest.get("qlib_receipt_digest")
        or platform_receipt.get("receipt_digest") != manifest.get("platform_receipt_digest")
        or comparison.get("comparison_digest") != manifest.get("comparison_digest")
        or comparison.get("accepted") is not True
        or manifest_comparison
        != {
            "accepted": comparison.get("accepted"),
            "daily_return_correlation": comparison.get("daily_return_correlation"),
            "terminal_nav_difference_bps": comparison.get("terminal_nav_difference_bps"),
            "max_symbol_weight_difference_bps": comparison.get("max_symbol_weight_difference_bps"),
        }
        or cost_model
        != {
            "commission_bps": settings.paper_account.commission_bps,
            "slippage_bps": settings.paper_account.slippage_bps,
        }
        or recovery.get("candidate_code_digest") != manifest.get("candidate_code_digest")
    ):
        raise AssistantRemoteError("research_terminal_recovery_invalid")

    factor_path = _job_evidence_path(
        job_root,
        manifest.get("candidate_code_path"),
        require_research=True,
    )
    qlib_path = _job_evidence_path(job_root, manifest.get("qlib_receipt_path"))
    platform_path = _job_evidence_path(job_root, manifest.get("platform_receipt_path"))
    if (
        _file_sha256(factor_path) != manifest.get("candidate_code_digest")
        or _file_sha256(qlib_path) != manifest.get("qlib_receipt_file_digest")
        or _file_sha256(platform_path) != manifest.get("platform_receipt_file_digest")
    ):
        raise AssistantRemoteError("research_evidence_file_digest_mismatch")
    qlib_bound = _bound_engine_receipt(
        qlib_path,
        job_root=job_root,
        job_id=str(request.get("job_id") or ""),
        run_id=str(manifest.get("run_id") or ""),
        resource_envelope_id=str(input_document.get("resource_envelope_id") or ""),
        engine="qlib",
    )
    platform_bound = _bound_engine_receipt(
        platform_path,
        job_root=job_root,
        job_id=str(request.get("job_id") or ""),
        run_id=str(manifest.get("run_id") or ""),
        resource_envelope_id=str(input_document.get("resource_envelope_id") or ""),
        engine="platform",
    )
    if (
        qlib_bound["engine_receipt"] != qlib_receipt
        or platform_bound["engine_receipt"] != platform_receipt
        or qlib_bound["raw_receipt_path"].resolve()
        != _job_evidence_path(job_root, manifest.get("qlib_raw_receipt_path")).resolve()
        or platform_bound["raw_receipt_path"].resolve()
        != _job_evidence_path(job_root, manifest.get("platform_raw_receipt_path")).resolve()
        or _file_sha256(qlib_bound["raw_receipt_path"])
        != manifest.get("qlib_raw_receipt_file_digest")
        or _file_sha256(platform_bound["raw_receipt_path"])
        != manifest.get("platform_raw_receipt_file_digest")
        or qlib_bound["raw_receipt_digest"] != manifest.get("qlib_receipt_digest")
        or platform_bound["raw_receipt_digest"] != manifest.get("platform_receipt_digest")
        or qlib_receipt.get("return_dates") != research_request.get("calendar")
        or platform_receipt.get("return_dates") != research_request.get("calendar")
        or qlib_receipt.get("calendar_digest")
        != digest_document(list(research_request.get("calendar") or []))
    ):
        raise AssistantRemoteError("research_engine_receipt_mismatch")

    artifact = registry.get_artifact_for_job(
        workspace_id="default",
        job_id=str(request.get("job_id") or ""),
        artifact_id=str(manifest.get("artifact_id") or ""),
    )
    artifact_comparison = _job_row_field(artifact, "comparison") if artifact else None
    if (
        artifact is None
        or _job_row_field(artifact, "version") != manifest.get("artifact_version")
        or _job_row_field(artifact, "status") != "qualified"
        or _job_row_field(artifact, "qualification_scope") != "paper_only"
        or _job_row_field(artifact, "candidate_code_digest")
        != manifest.get("candidate_code_digest")
        or _job_row_field(artifact, "qlib_receipt_digest") != manifest.get("qlib_receipt_digest")
        or _job_row_field(artifact, "platform_receipt_digest")
        != manifest.get("platform_receipt_digest")
        or _job_row_field(artifact, "comparison_digest") != manifest.get("comparison_digest")
        or _job_row_field(artifact_comparison, "accepted") is not True
    ):
        raise AssistantRemoteError("research_registry_artifact_mismatch")
    platform_engine = platform_bound["engine_receipt"]
    return {
        **manifest,
        "manifest_digest": manifest_digest,
        "_candidate_code": factor_path.read_text(encoding="utf-8"),
        "_daily_returns": list(platform_engine["daily_returns"]),
        "_return_dates": list(platform_engine["return_dates"]),
        "_turnover_period": platform_bound["turnover_period"],
    }


def _verified_failure_evidence(
    *,
    job_root: Path,
    request: Mapping[str, Any],
    cycle: Mapping[str, Any],
) -> dict[str, Any] | None:
    manifest = _strict_json_mapping(job_root / "evidence_manifest.json")
    if manifest is None:
        return None
    manifest_digest = str(manifest.pop("manifest_digest", ""))
    if (
        set(manifest)
        != {
            "contract",
            "job_id",
            "job_key",
            "operation_id",
            "material_digest",
            "job_input_digest",
            "cycle_receipt_digest",
            "terminal_status",
            "failed_phase",
            "failure_code",
            "preflight_receipt_digest",
        }
        or manifest.get("contract") != "hqa.d34_research_evidence/v1"
        or manifest_digest != digest_document(manifest)
        or manifest.get("job_id") != request.get("job_id")
        or manifest.get("job_key") != request.get("job_key")
        or manifest.get("operation_id") != request.get("operation_id")
        or manifest.get("material_digest") != request.get("material_digest")
        or manifest.get("cycle_receipt_digest") != digest_document(dict(cycle))
        or (
            manifest.get("preflight_receipt_digest") is not None
            and _DIGEST_RE.fullmatch(str(manifest.get("preflight_receipt_digest"))) is None
        )
    ):
        return None
    return {**manifest, "manifest_digest": manifest_digest}


def _research_request_for_job(
    settings: Settings,
    *,
    job_id: str,
) -> dict[str, Any] | None:
    book = load_book(settings)
    return next(
        (
            item
            for item in book["requests"]
            if isinstance(item, dict) and item.get("job_id") == job_id
        ),
        None,
    )


def _terminal_research_reply(
    request: Mapping[str, Any],
    *,
    status: str,
    code: str,
    message: str,
    candidate: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = {
        "operation_id": request["operation_id"],
        "material_digest": request["material_digest"],
        "job_id": request["job_id"],
        "job_key": request["job_key"],
    }
    if candidate is not None:
        provenance.update(
            {
                "candidate_id": candidate["candidate_id"],
                "source_digest": candidate["source_digest"],
            }
        )
    if evidence is not None:
        provenance.update(
            {
                "evidence_manifest_digest": evidence["manifest_digest"],
                "evidence_href": evidence["href"],
            }
        )
    reply = {
        "status": status,
        "code": code,
        "message": message,
        "provenance": provenance,
    }
    if candidate is not None:
        display_name_zh, summary_zh = _candidate_presentation_zh(candidate)
        reply["display_name_zh"] = display_name_zh
        reply["summary_zh"] = summary_zh
    return reply


def _store_terminal_research_projection(
    settings: Settings,
    *,
    job_id: str,
    status: str,
    outcome: str,
    code: str,
    message: str,
    candidate: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    with _book_mutation_lock(settings):
        book = load_book(settings)
        request = next(
            (
                item
                for item in book["requests"]
                if isinstance(item, dict) and item.get("job_id") == job_id
            ),
            None,
        )
        if request is None:
            return None
        if request.get("terminal") is True and not (
            request.get("outcome") == "outcome_unknown"
            and (
                outcome == "verified_candidate"
                or (
                    outcome == "outcome_unknown"
                    and (request.get("result_reply") or {}).get("code") != code
                )
            )
        ):
            return _research_request_projection(request)
        request["status"] = status
        request["terminal"] = True
        request["outcome"] = outcome
        evidence_summary = None
        if evidence is not None:
            evidence_href = (
                f"/api/assistant/remote/evidence/"
                f"{request['operation_id']}/{evidence['manifest_digest']}"
            )
            performance = candidate.get("performance") if candidate is not None else None
            gates = candidate.get("verification_gates") if candidate is not None else None
            evidence_summary = {
                "manifest_digest": evidence["manifest_digest"],
                "href": evidence_href,
                "candidate_code_digest": evidence.get("candidate_code_digest"),
                "candidate_code": evidence.get("_candidate_code"),
                "candidate_code_href": f"{evidence_href}#candidate-code",
                "qlib_receipt_digest": evidence.get("qlib_receipt_digest"),
                "qlib_receipt_href": f"{evidence_href}#qlib-receipt",
                "platform_receipt_digest": evidence.get("platform_receipt_digest"),
                "platform_receipt_href": f"{evidence_href}#platform-receipt",
                "comparison_digest": evidence.get("comparison_digest"),
                "comparison_href": f"{evidence_href}#comparison",
                "comparison": evidence.get("comparison"),
                "cost_model": evidence.get("cost_model"),
                "failed_phase": evidence.get("failed_phase"),
                "failure_code": evidence.get("failure_code"),
                "dsr": candidate.get("dsr") if candidate is not None else None,
                "verification_gates": dict(gates) if isinstance(gates, dict) else None,
                "performance": (
                    {
                        "total_return": performance.get("total_return"),
                        "sharpe_annual": performance.get("sharpe_annual"),
                        "max_drawdown": performance.get("max_drawdown"),
                        "turnover_period": performance.get("turnover_period"),
                        "n_periods": performance.get("n_periods"),
                        "window_start": (
                            performance.get("return_dates", [None])[0]
                            if performance.get("return_dates")
                            else None
                        ),
                        "window_end": (
                            performance.get("return_dates", [None])[-1]
                            if performance.get("return_dates")
                            else None
                        ),
                    }
                    if isinstance(performance, dict)
                    else None
                ),
            }
        request["evidence"] = evidence_summary
        request["result_reply"] = _terminal_research_reply(
            request,
            status=status,
            code=code,
            message=message,
            candidate=candidate,
            evidence=evidence_summary,
        )
        request["updated_at"] = _utc_now()
        if candidate is None:
            request.pop("candidate_id", None)
            request.pop("source_digest", None)
        else:
            request["candidate_id"] = candidate["candidate_id"]
            request["source_digest"] = candidate["source_digest"]
        save_book(settings, book)
        return _research_request_projection(request)


def _accepted_research_source_path(
    *,
    job_root: Path,
    factor_path: object,
) -> Path:
    workspace_root = job_root.parent.parent
    raw = str(factor_path or "").strip()
    if not raw:
        raise AssistantRemoteError("research_result_factor_missing")
    marker = "/workspace/d34/"
    if marker in raw:
        path = workspace_root / raw.split(marker, 1)[1]
    else:
        candidate = Path(raw)
        path = candidate if candidate.is_absolute() else workspace_root / candidate
    resolved = path.resolve()
    try:
        resolved.relative_to(workspace_root.resolve())
    except ValueError as exc:
        raise AssistantRemoteError("research_result_factor_outside_workspace") from exc
    return resolved


def reconcile_research_result(
    settings: Settings,
    *,
    job_id: str,
    registry: Any | None = None,
) -> dict[str, Any] | None:
    """Project one exact terminal D-34 job into its originating chat request."""

    cleaned_job_id = job_id.strip()
    request = _research_request_for_job(settings, job_id=cleaned_job_id)
    if request is None:
        return None
    if request.get("terminal") is True and request.get("outcome") != "outcome_unknown":
        return _research_request_projection(request)
    job_root = _research_job_root(settings, job_id=cleaned_job_id)
    if job_root is None:
        return None
    try:
        cycle = _recover_terminal_bundle(job_root) or _load_json_mapping(
            job_root / "cycle_receipt.json"
        )
    except AssistantRemoteError as exc:
        return _store_terminal_research_projection(
            settings,
            job_id=cleaned_job_id,
            status="outcome_unknown",
            outcome="outcome_unknown",
            code=exc.code,
            message="Research terminal evidence is inconsistent.",
        )
    if cycle is None:
        return None
    if str(cycle.get("job_id") or "") != cleaned_job_id:
        return _store_terminal_research_projection(
            settings,
            job_id=cleaned_job_id,
            status="outcome_unknown",
            outcome="outcome_unknown",
            code="research_result_job_mismatch",
            message="Research result job lineage could not be verified.",
        )
    phase = str(cycle.get("phase") or "")
    recovery_universe: object | None = None
    accepted = (
        cycle.get("contract") == "hqa.d34_job_outcome/v1"
        and cycle.get("comparison_accepted") is True
        and phase in _ACCEPTED_CYCLE_PHASES
    )
    if not accepted and phase in _ACCEPTED_CYCLE_PHASES and cycle.get("recovered") is True:
        recovery = _load_json_mapping(job_root / "terminal_recovery.json")
        if recovery is not None:
            recovery_digest = str(recovery.pop("recovery_digest", ""))
            comparison = recovery.get("comparison")
            if (
                recovery.get("contract") == "hqa.d34_terminal_recovery/v1"
                and recovery.get("job_id") == cleaned_job_id
                and recovery_digest == digest_document(recovery)
                and isinstance(comparison, dict)
                and comparison.get("accepted") is True
            ):
                accepted = True
                recovery_universe = recovery.get("universe")
    if accepted:
        if registry is None:
            from quant_system.hermes.d34_registry_authority import (
                PostgresRegistryAuthority,
            )

            registry = PostgresRegistryAuthority(settings)
        try:
            evidence = _verified_research_evidence(
                settings=settings,
                job_root=job_root,
                request=request,
                cycle=cycle,
                registry=registry,
            )
        except Exception as exc:  # noqa: BLE001 - evidence authority boundary
            code = getattr(exc, "code", "research_evidence_unavailable")
            return _store_terminal_research_projection(
                settings,
                job_id=cleaned_job_id,
                status="outcome_unknown",
                outcome="outcome_unknown",
                code=str(code),
                message="Research evidence could not be verified.",
            )
        research_request = _load_json_mapping(job_root / "research_request.json")
        artifact_id = str(evidence.get("artifact_id") or "").strip()
        if (
            research_request is None
            or not artifact_id
            or research_request.get("job_id") != cleaned_job_id
            or research_request.get("job_key") != request.get("job_key")
            or research_request.get("objective") != request.get("objective")
            or research_request.get("universe") != request.get("universe")
            or (
                recovery_universe is not None
                and recovery_universe != research_request.get("universe")
            )
        ):
            return _store_terminal_research_projection(
                settings,
                job_id=cleaned_job_id,
                status="outcome_unknown",
                outcome="outcome_unknown",
                code="research_result_request_mismatch",
                message="Research request lineage could not be verified.",
            )
        try:
            candidate = record_verified_from_dual_engine_artifact(
                settings,
                artifact_id=artifact_id,
                source_path=_job_evidence_path(
                    job_root,
                    evidence.get("candidate_code_path"),
                    require_research=True,
                ),
                source_digest=str(evidence.get("candidate_code_digest") or ""),
                comparison_digest=str(evidence.get("comparison_digest") or ""),
                universe=research_request.get("universe") or [],
                objective=str(research_request.get("objective") or ""),
                job_key=str(request["job_key"]),
                top_n=(
                    int(research_request["top_k"])
                    if isinstance(research_request.get("top_k"), int)
                    and research_request["top_k"] >= 1
                    else None
                ),
                operator=(
                    str(research_request["operator"]) if research_request.get("operator") else None
                ),
                daily_returns=evidence["_daily_returns"],
                turnover_period=evidence["_turnover_period"],
                return_dates=evidence["_return_dates"],
                evidence_ref=CandidateEvidenceRef(
                    job_id=cleaned_job_id,
                    run_id=str(evidence.get("run_id") or ""),
                    manifest_digest=str(evidence.get("manifest_digest") or ""),
                    qlib_raw_receipt_digest=str(evidence.get("qlib_receipt_digest") or ""),
                    platform_raw_receipt_digest=str(evidence.get("platform_receipt_digest") or ""),
                ),
            )
        except AssistantRemoteError as exc:
            return _store_terminal_research_projection(
                settings,
                job_id=cleaned_job_id,
                status="outcome_unknown",
                outcome="outcome_unknown",
                code=exc.code,
                message="Accepted research could not be admitted as a verified candidate.",
            )
        try:
            activation = hang_candidate(
                settings,
                candidate_id=candidate["candidate_id"],
                expected_source_digest=candidate["source_digest"],
            )
        except AssistantRemoteError as exc:
            if exc.code in {
                "hang_account_outcome_unknown",
                "hang_sleeve_pending",
                "hang_book_persist_failed",
                "hang_sleeve_activation_failed",
                "hang_recovery_sleeve_outcome_unknown",
            }:
                activation_evidence = {
                    "job_id": cleaned_job_id,
                    "candidate_id": candidate["candidate_id"],
                    "candidate_code_digest": candidate["source_digest"],
                    "research_manifest_digest": evidence["manifest_digest"],
                    "failed_phase": "paper_activation",
                    "failure_code": exc.code,
                }
                return _store_terminal_research_projection(
                    settings,
                    job_id=cleaned_job_id,
                    status="outcome_unknown",
                    outcome="outcome_unknown",
                    code=exc.code,
                    message="研究已验证，模拟资金分配或启用尚待对账；将沿原候选恢复。",
                    evidence={
                        **activation_evidence,
                        "manifest_digest": digest_document(activation_evidence),
                    },
                )
            result_code = f"paper_activation_failed:{exc.code}"
            result_message = (
                "双引擎研究已通过，候选已保留；自动启用模拟运行未完成："
                f"{exc.code}。可在策略库查看并处理。"
            )
        else:
            result_code = "paper_running"
            result_message = (
                "双引擎研究已通过，已分配 $10,000 并启用模拟运行"
                f"（{activation['sleeve_id']}）；后续按每日计划生成信号和模拟成交。"
            )
        return _store_terminal_research_projection(
            settings,
            job_id=cleaned_job_id,
            status="candidate_ready",
            outcome="verified_candidate",
            code=result_code,
            message=result_message,
            candidate=candidate,
            evidence=evidence,
        )
    failure_evidence = _verified_failure_evidence(
        job_root=job_root,
        request=request,
        cycle=cycle,
    )
    if phase in _ACCEPTED_CYCLE_PHASES:
        return _store_terminal_research_projection(
            settings,
            job_id=cleaned_job_id,
            status="outcome_unknown",
            outcome="outcome_unknown",
            code=str(cycle.get("code") or "accepted_receipt_invalid"),
            message="Terminal research receipt did not prove an accepted candidate.",
            evidence=failure_evidence,
        )
    if phase in {"rejected", "failed"}:
        unknown = phase == "failed" and cycle.get("failed_phase") == "research"
        status = "outcome_unknown" if unknown else "failed"
        return _store_terminal_research_projection(
            settings,
            job_id=cleaned_job_id,
            status=status,
            outcome=status,
            code=str(cycle.get("code") or "research_failed"),
            message="Research did not produce a verified candidate.",
            evidence=failure_evidence,
        )
    if phase == "needs_recovery":
        return _store_terminal_research_projection(
            settings,
            job_id=cleaned_job_id,
            status="outcome_unknown",
            outcome="outcome_unknown",
            code=str(
                cycle.get("code") or cycle.get("last_recovery_code") or "research_needs_recovery"
            ),
            message="Research outcome requires recovery.",
            evidence=failure_evidence,
        )
    return None


def project_terminal_research_results(
    settings: Settings,
    *,
    jobs: Any | None = None,
    registry: Any | None = None,
) -> dict[str, Any]:
    """Mutating worker-side projector for all durable chat-research receipts."""

    status_updates = 0
    rows: dict[str, Any] = {}
    if jobs is not None:
        rows = {
            str(_job_row_field(item, "job_id") or ""): item
            for item in jobs.list(
                workspace_id="default",
                limit=JOB_LIST_LIMIT,
                state=None,
            )
        }
        with _book_mutation_lock(settings):
            status_book = load_book(settings)
            for item in status_book["requests"]:
                if (
                    not isinstance(item, dict)
                    or not item.get("operation_id")
                    or item.get("terminal") is True
                ):
                    continue
                row = rows.get(str(item.get("job_id") or ""))
                state = str(_job_row_field(row, "state") or "") if row is not None else ""
                projected_state = "running" if state in {"leased", "running"} else "queued"
                if state not in {"queued", "leased", "running"}:
                    continue
                if item.get("status") == projected_state:
                    continue
                item["status"] = projected_state
                item["outcome"] = projected_state
                item["result_reply"] = {
                    "status": projected_state,
                    "code": f"research_{projected_state}",
                    "message": (
                        "Research job is running."
                        if projected_state == "running"
                        else "Research request queued."
                    ),
                    "provenance": {
                        "operation_id": item["operation_id"],
                        "material_digest": item["material_digest"],
                        "job_id": item["job_id"],
                        "job_key": item["job_key"],
                    },
                }
                item["updated_at"] = _utc_now()
                status_updates += 1
            if status_updates:
                save_book(settings, status_book)
    book = load_book(settings)
    job_ids = list(
        dict.fromkeys(
            str(item.get("job_id") or "").strip()
            for item in book["requests"]
            if isinstance(item, dict)
            and item.get("operation_id")
            and str(item.get("job_id") or "").startswith("job-")
            and (item.get("terminal") is not True or item.get("outcome") == "outcome_unknown")
        )
    )
    projected = 0
    for pending_job_id in job_ids:
        projection = reconcile_research_result(
            settings,
            job_id=pending_job_id,
            registry=registry,
        )
        if projection is not None:
            projected += 1
            continue
        row = rows.get(pending_job_id)
        state = str(_job_row_field(row, "state") or "") if row is not None else ""
        if state not in {"succeeded", "rejected", "outcome_unknown", "cancelled"}:
            continue
        request = next(
            (
                item
                for item in book["requests"]
                if isinstance(item, dict) and item.get("job_id") == pending_job_id
            ),
            None,
        )
        if request is None:
            continue
        expected_job_key = str(request.get("job_key") or "")
        expected_input_digest = str(request.get("job_input_digest") or "")
        observed_job_key = str(_job_row_field(row, "job_key") or "")
        observed_input_digest = str(_job_row_field(row, "input_digest") or "")
        authority_bound = (
            expected_job_key == observed_job_key
            and _DIGEST_RE.fullmatch(expected_input_digest) is not None
            and expected_input_digest == observed_input_digest
        )
        evidence_body = {
            "contract": "hqa.d34_research_authority_evidence/v1",
            "job_id": pending_job_id,
            "job_key": observed_job_key,
            "job_input_digest": observed_input_digest,
            "terminal_state": state,
            "outcome_code": str(_job_row_field(row, "outcome_code") or ""),
            "failed_phase": "worker_lease",
            "failure_code": (
                str(_job_row_field(row, "outcome_code") or "research_worker_terminal")
                if authority_bound
                else "research_job_authority_mismatch"
            ),
        }
        evidence = {**evidence_body, "manifest_digest": digest_document(evidence_body)}
        failed = authority_bound and state in {"rejected", "cancelled"}
        terminal = _store_terminal_research_projection(
            settings,
            job_id=pending_job_id,
            status="failed" if failed else "outcome_unknown",
            outcome="failed" if failed else "outcome_unknown",
            code=str(evidence["failure_code"]),
            message=(
                "Research job ended without a verified candidate."
                if failed
                else "Research outcome is unknown; inspect the content-addressed worker evidence."
            ),
            evidence=evidence,
        )
        if terminal is not None:
            projected += 1
    return {
        "contract": "hqa.assistant_remote_projector/v1",
        "requests_checked": len(job_ids),
        "requests_projected": projected,
        "status_updates": status_updates,
    }


def _sleeve_store_fossils(settings: Settings, book_sleeve_ids: set[str]) -> list[dict[str, Any]]:
    """Automation sleeves the book never hung: visible as history, never official.

    Old-lane automation sleeves (for example the D-34 canaries) were never hung
    through the remote book, so they can never count as official hung P&L —
    even when they carry their own lane's digest lineage. They must still be
    visible on the desk as fossil/history rows instead of hiding in the deep
    paper pages. Manual sleeves and book-hung sleeves stay out.
    """
    api_runs_dir = Path(settings.data.data_dir) / "api_runs"
    storage = PaperStrategySleeveStorage(api_runs_dir)
    rows: list[dict[str, Any]] = []
    for sleeve in storage.list_sleeves():
        metadata = sleeve.metadata or {}
        if metadata.get("automation_managed") is not True:
            continue
        if sleeve.sleeve_id in book_sleeve_ids:
            continue
        digest = str(metadata.get("candidate_code_digest") or metadata.get("source_digest") or "")
        preview = metadata.get("preview_label") == "hung_observation_demo"
        seed = metadata.get("automation_source") == "preview_seed" or preview
        digest_ok = _DIGEST_RE.fullmatch(digest) is not None
        if seed:
            fallback_reason = "preview_seed"
        elif not digest_ok:
            fallback_reason = "digest_less"
        else:
            fallback_reason = "not_book_bound"
        reason = metadata.get("fossil_reason") or fallback_reason
        rows.append(
            {
                "candidate_id": metadata.get("candidate_id"),
                "sleeve_id": sleeve.sleeve_id,
                "reason": reason,
                "sleeve_status": str(sleeve.status),
                "origin": "sleeve_store",
            }
        )
    return rows


def _digest_bound_source_display_name_zh(item: Mapping[str, Any]) -> str | None:
    source_path = item.get("source_path")
    source_digest = str(
        item.get("source_digest") or item.get("candidate_code_digest") or ""
    )
    if not isinstance(source_path, str) or _DIGEST_RE.fullmatch(source_digest) is None:
        return None
    path = Path(source_path).expanduser()
    try:
        source = path.read_bytes()
    except OSError:
        return None
    if len(source) > 1_000_000 or hashlib.sha256(source).hexdigest() != source_digest:
        return None
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "display_name_zh"
            for target in targets
        ):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            cleaned = value.value.strip()
            if 1 <= len(cleaned) <= 120:
                return cleaned
    return None


def _frozen_definition_title_zh(item: Mapping[str, Any]) -> str | None:
    """Frozen ``definition.json`` title for a strategy_definition candidate.

    Display only: the name must come from the same frozen file the strategy
    directory shows, bound byte-for-byte to the recorded digest. Any mismatch
    (wrong source, missing path, digest drift, unreadable or oversized file,
    absent or non-string title) returns None so the caller falls back to a
    deterministic label instead of inventing a name.
    """
    if str(item.get("source") or "") != "strategy_definition":
        return None
    source_path = item.get("source_path")
    source_digest = str(
        item.get("source_digest") or item.get("candidate_code_digest") or ""
    )
    if not isinstance(source_path, str) or _DIGEST_RE.fullmatch(source_digest) is None:
        return None
    path = Path(source_path).expanduser()
    try:
        source = path.read_bytes()
    except OSError:
        return None
    if len(source) > 1_000_000 or hashlib.sha256(source).hexdigest() != source_digest:
        return None
    try:
        raw = json.loads(source.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    # Same display rule as the strategy library directory (definition_catalog).
    return (
        title.strip()[:200]
        .replace(" / baseline", " · 原组合")
        .replace(" / augmented", " · 加入新因子")
    )


def _definition_digest_label_zh(item: Mapping[str, Any]) -> str:
    """Deterministic fallback name for a strategy_definition candidate."""
    marker = str(
        item.get("definition_digest")
        or item.get("source_digest")
        or item.get("candidate_code_digest")
        or ""
    ).strip()
    if marker:
        return f"策略定义 {marker[:12]}"
    factor_id = str(item.get("factor_id") or "").strip()
    if factor_id:
        return factor_id
    return "策略定义"


def _candidate_presentation_zh(item: Mapping[str, Any]) -> tuple[str, str]:
    candidate_id = str(item.get("candidate_id") or "")
    exact = _EXACT_CANDIDATE_PRESENTATION_ZH.get(candidate_id)
    if exact is not None:
        return exact
    if str(item.get("source") or "") == "strategy_definition":
        name = _frozen_definition_title_zh(item) or _definition_digest_label_zh(item)
    else:
        stored_name = item.get("display_name_zh")
        if isinstance(stored_name, str) and stored_name.strip():
            name = stored_name.strip()[:120]
        else:
            name = _digest_bound_source_display_name_zh(item) or (
                "均值回归研究因子"
                if item.get("strategy_id") == "mean_reversion_top_n"
                else "横截面选股研究因子"
            )
    symbols = [
        str(symbol).strip().upper()
        for symbol in item.get("universe") or []
        if str(symbol).strip()
    ]
    scope = "、".join(symbols) if symbols else "未标注"
    state = "模拟运行中" if item.get("status") == "hung" else "研究验证已完成"
    return name, f"标的范围：{scope}；{state}。"


def _project_activation_eligibility(
    settings: Settings,
    candidate: dict[str, Any],
    candidates: Sequence[object],
) -> dict[str, Any]:
    from quant_system.research import admission_v2

    try:
        admission_v2.require_protocol_lineage(settings, candidate)
    except (OSError, ValueError) as exc:
        return {"eligible": False, "reason": str(exc)}
    from quant_system.research.admission_activation import capital_requires_authoritative_job

    if (not admission_v2.candidate_uses_protocol(candidate)
            and capital_requires_authoritative_job(settings, None)):
        return {"eligible": False, "reason": "activation_parallel_capital_blocked"}
    if admission_v2.candidate_uses_protocol(candidate):
        try:
            _, receipt = admission_v2.candidate_validation(settings, candidate)
            if receipt["mode"] == "authoritative":
                admission_v2.project_new_capital_eligibility(
                    settings, candidate["admission_v2"],
                    definition_digest=candidate["definition_digest"],
                    validation_sha256=candidate["verification_receipt_digest"],
                    source_sha256=candidate["source_digest"],
                )
                return {
                    "eligible": True,
                    "reason": "preflight_on_enable",
                    "protocol": admission_v2.PROTOCOL_VERSION,
                }
            from quant_system.research.admission_activation import (
                capital_requires_authoritative_job,
            )

            if capital_requires_authoritative_job(settings, receipt["protocol"]):
                return {
                    "eligible": False,
                    "reason": "activation_parallel_capital_blocked",
                    "protocol": admission_v2.PROTOCOL_VERSION,
                }
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {
                "eligible": False, "reason": str(exc), "protocol": admission_v2.PROTOCOL_VERSION,
            }
    try:
        quality = _current_new_capital_quality(settings, candidate, candidates)
    except (OSError, ValueError) as exc:
        return {"eligible": False, "reason": str(exc)}
    return {"eligible": True, "reason": "preflight_on_enable",
            "quality_tier": quality["tier"], "quality_family_digest": quality["family_digest"]}


def _v2_recovery_possible(settings, candidate):
    """A hint only: locked recovery still proves exact account/allocation lineage.

    PG may commit before its response is lost, leaving a pending (not finalized)
    sleeve. That already-funded transaction must not acquire new admission gates.
    Unallocated pending material cannot fund: the existing locked reconciliation
    validates it, and the fresh-allocation branch still checks the full gate.
    """
    if _has_recoverable_hang_sleeve(settings, candidate):
        return True
    storage = PaperStrategySleeveStorage(Path(settings.data.data_dir) / "api_runs")
    matches = [
        sleeve for sleeve in storage.list_pending_sleeves()
        if sleeve.metadata.get("candidate_id") == candidate.get("candidate_id")
        and sleeve.metadata.get("mandate_id") == "remote-hang"
        and sleeve.metadata.get("source_digest") == candidate.get("source_digest")
        and sleeve.initial_allocated_cash == _HANG_ALLOCATION_CASH
    ]
    return len(matches) == 1


def _has_recoverable_hang_sleeve(
    settings: Settings,
    candidate: Mapping[str, Any],
) -> bool:
    candidate_id = str(candidate.get("candidate_id") or "")
    digest = str(
        candidate.get("source_digest") or candidate.get("candidate_code_digest") or ""
    )
    if not candidate_id or _DIGEST_RE.fullmatch(digest) is None:
        return False
    storage = PaperStrategySleeveStorage(Path(settings.data.data_dir) / "api_runs")
    matches = [
        sleeve
        for sleeve in storage.list_sleeves()
        if sleeve.metadata.get("candidate_id") == candidate_id
        and sleeve.metadata.get("mandate_id") == "remote-hang"
        and (
            sleeve.metadata.get("candidate_code_digest")
            or sleeve.metadata.get("source_digest")
        )
        == digest
    ]
    if len(matches) != 1:
        return False
    metadata = matches[0].metadata
    fossil_reason = metadata.get("fossil_reason")
    return fossil_reason in {None, "not_book_bound"} and (
        metadata.get("hang_activation_state") == _HANG_ACTIVATION_PENDING
        or fossil_reason == "not_book_bound"
        or (
            metadata.get("fossil") is not True
            and metadata.get("official_observation") is not False
        )
    )


def _project_candidate(
    settings: Settings,
    item: object,
    candidates: Sequence[object],
) -> object:
    if not isinstance(item, dict):
        return item
    projected = dict(item)
    name, summary = _candidate_presentation_zh(projected)
    projected["display_name_zh"] = name
    projected["summary_zh"] = summary
    if projected.get("status") == "verified" and projected.get("sleeve_id") is None:
        projected["activation_eligibility"] = (
            {"eligible": True, "reason": "recovery_available"}
            if _has_recoverable_hang_sleeve(settings, projected)
            else _project_activation_eligibility(
                settings,
                projected,
                candidates,
            )
        )
    return projected


def project_book(settings: Settings) -> dict[str, Any]:
    book = load_book(settings)
    projected_requests = [
        _research_request_projection(item)
        if isinstance(item, dict) and item.get("operation_id")
        else item
        for item in book["requests"]
    ]
    fossils = [
        {
            "candidate_id": item.get("candidate_id"),
            "sleeve_id": item.get("sleeve_id"),
            "reason": item.get("fossil_reason") or "digest_less",
            "sleeve_status": None,
            "origin": "book",
        }
        for item in book["candidates"]
        if isinstance(item, dict)
        and item.get("status") == "hung"
        and (
            item.get("fossil") is True
            or not _has_source_digest(item)
            or _is_fixture_candidate(item)
        )
    ]
    book_sleeve_ids = {
        item.get("sleeve_id") for item in book["candidates"] if isinstance(item, dict)
    }
    fossils.extend(_sleeve_store_fossils(settings, book_sleeve_ids))
    annotated_candidates = annotate_hung_momentum_candidates(book["candidates"])
    return {
        "contract": BOOK_CONTRACT,
        "candidates": [
            _project_candidate(settings, item, annotated_candidates)
            for item in annotated_candidates
        ],
        "requests": projected_requests,
        "verified_count": sum(
            1
            for item in book["candidates"]
            if isinstance(item, dict)
            and item.get("status") == "verified"
            and _has_source_digest(item)
        ),
        "hung_count": sum(
            1
            for item in book["candidates"]
            if isinstance(item, dict)
            and item.get("status") == "hung"
            and _has_source_digest(item)
            and item.get("fossil") is not True
        ),
        "fossil_count": len(fossils),
        "fossils": fossils,
    }


__all__ = [
    "AssistantRemoteError",
    "BOOK_CONTRACT",
    "HANG_CONTRACT",
    "RESEARCH_OPERATION_CONTRACT",
    "hang_candidate",
    "intake_research_operation",
    "load_book",
    "project_book",
    "project_research_evidence",
    "project_research_request",
    "project_terminal_research_results",
    "reconcile_research_result",
    "record_verified_candidate",
    "record_verified_from_dual_engine_artifact",
    "save_book",
    "verify_registered_factor",
]
