from __future__ import annotations

import errno
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from quant_system.agent.candidate_fs import (
    assert_entry_is_open_fd,
    open_absolute_directory,
)
from quant_system.agent.candidate_manifest import CandidateIntegrityError
from quant_system.agent.candidate_pool import CandidatePool, CandidatePoolScanLimitExceeded
from quant_system.api.schemas.common import resolve_run_dir
from quant_system.config.settings import Settings
from quant_system.hermes.artifact_catalog import HermesArtifactCatalog
from quant_system.hermes.command_ledger import (
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
    HermesCommandValidationError,
    HermesRunLink,
    HermesRunLinkPage,
    hermes_run_link_digest,
)
from quant_system.storage.runs_repository import KIND_DIRS, _created_at_from_run_id


@dataclass(frozen=True)
class _Collection:
    items: list[dict[str, Any]]
    source: dict[str, Any]
    warnings: list[dict[str, Any]]
    count_exact: bool = True


_ORIGINAL_HREFS = {
    "backtest": "/api/backtests/{resource_id}",
    "factor": "/api/factors/{resource_id}",
    "paper": "/api/paper/{resource_id}",
    "replication": "/api/replications/reversal-momentum/{resource_id}",
}
_HQA_KINDS = {
    "portfolio_risk",
    "prediction",
    "market_foresight",
    "weekly_review",
    "opportunity_summary",
    "automation_status",
}
_SAFE_RESULT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_MAX_RESPONSE_WARNINGS = 200
_MAX_DETAIL_WARNINGS = 20
_MAX_REFERENCE_JSON_BYTES = 1024 * 1024
_MAX_SOURCE_REFERENCE_JSON_BYTES = 32 * 1024 * 1024
_MAX_PARQUET_FOOTER_BYTES = 16 * 1024 * 1024
_MAX_STATUS_CHARS = 128
_MAX_DISPLAY_TITLE_CHARS = 256
_MAX_SUMMARY_CHARS = 1000
_MAX_CANDIDATE_PREVIEW_CHARS = 64 * 1024
_MAX_SOURCE_ENTRIES = 10_000
_MAX_HQA_SOURCE_ENTRIES = 1_000
# CandidatePool verifies exact artifact bytes before returning a list item. Keep
# this projection deliberately small until the catalog is backed by a cursor or
# trusted index; the current per-candidate integrity bounds make this a bounded
# (well below 64 MiB for the normal verified path) source scan.
_MAX_CANDIDATE_SOURCE_ENTRIES = 8
_MAX_LIST_RUN_LINKS_PER_RESOURCE = 3
_MAX_DETAIL_RUN_LINKS_PER_RESOURCE = 100
_RUN_DETAIL_PATHS = {
    "backtest": (
        "metadata.json",
        "backtests/benchmark_metrics.json",
        "backtests/metrics.json",
        "backtests/equity_curve.parquet",
        "backtests/benchmark_curve.parquet",
        "backtests/orders.parquet",
        "backtests/positions.parquet",
        "backtests/trade_blotter.parquet",
        "backtests/attribution.parquet",
    ),
    "factor": (
        "metadata.json",
        "factors/factor_results.parquet",
        "factors/factor_signals.parquet",
        "factors/factor_ic.parquet",
        "factors/quantile_returns.parquet",
    ),
    "paper": (
        "metadata.json",
        "paper/orders.parquet",
        "paper/order_events.parquet",
        "paper/trades.parquet",
        "paper/risk_breaches.parquet",
    ),
    "replication": ("metadata.json", "result.json"),
}
_RUN_COMPLETION_ARTIFACTS = {
    "backtest": ("backtests/metrics.json",),
    "factor": ("factors/factor_results.parquet",),
    "paper": ("paper/orders.parquet",),
    "replication": ("result.json",),
}
_RUN_REFERENCE_JSON_PATHS = {
    "backtest": ("backtests/metrics.json", "backtests/benchmark_metrics.json"),
    "factor": (),
    "paper": (),
    "replication": ("result.json",),
}
_EXPERIMENT_DETAIL_PATHS = (
    "metadata.json",
    "experiment_config.json",
    "agent_summary.json",
    "experiment_runs.parquet",
    "runs.parquet",
    "walk_forward_folds.parquet",
    "folds.parquet",
)


class HermesResultResourceTooLarge(ValueError):
    """The authoritative resource is valid JSON but exceeds the BFF response budget."""


class HermesResultSourceBudgetExceeded(ValueError):
    """A source exceeded its bounded metadata-read budget before enumeration completed."""


@dataclass
class _JsonReadBudget:
    remaining_bytes: int = _MAX_SOURCE_REFERENCE_JSON_BYTES

    def charge(self, size: int) -> None:
        if size > self.remaining_bytes:
            raise HermesResultSourceBudgetExceeded("source JSON read budget exceeded")
        self.remaining_bytes -= size


def _safe_result_id(value: str) -> bool:
    return _SAFE_RESULT_ID.fullmatch(value) is not None


def _bounded_warnings(
    warnings: list[dict[str, Any]], *, limit: int = _MAX_RESPONSE_WARNINGS
) -> list[dict[str, Any]]:
    if len(warnings) <= limit:
        return warnings
    return [
        *warnings[: limit - 1],
        {
            "source": "results_catalog",
            "code": "warnings_truncated",
            "kind": None,
            "resource_id": None,
        },
    ]


def _warning_code(value: object) -> str:
    """Keep upstream diagnostics inside our stable response contract."""
    if isinstance(value, str) and value.strip() and len(value) <= 128:
        return value
    return "source_warning_invalid"


def _bounded_directory_entries(root: Path) -> tuple[list[Path], bool]:
    entries = list(islice(root.iterdir(), _MAX_SOURCE_ENTRIES + 1))
    return entries[:_MAX_SOURCE_ENTRIES], len(entries) > _MAX_SOURCE_ENTRIES


def _ensure_resource_bound(resource: dict[str, Any]) -> None:
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    size = 0
    try:
        for chunk in encoder.iterencode(resource):
            size += len(chunk.encode("utf-8"))
            if size > _MAX_REFERENCE_JSON_BYTES:
                raise HermesResultResourceTooLarge("detail resource exceeds the response bound")
    except HermesResultResourceTooLarge:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError("detail resource is not bounded JSON") from exc


def _oversized_detail(
    *, item: dict[str, Any], source: str, kind: str, resource_id: str
) -> dict[str, Any]:
    return {
        "read_status": "degraded",
        "item": item,
        "resource": None,
        "warnings": [
            {
                "source": source,
                "code": "resource_payload_too_large",
                "kind": kind,
                "resource_id": resource_id,
            }
        ],
    }


def _status(value: object, *, default: str = "unknown") -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip() or len(value) > _MAX_STATUS_CHARS:
        raise ValueError("result status is outside the read-model contract")
    return value


def _projection_text(value: object, *, maximum: int) -> str | None:
    """Return one bounded display line without granting it domain authority."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text:
        return None
    if len(text) <= maximum:
        return text
    return f"{text[: maximum - 1]}…"


def _bounded_preview(value: bytes) -> str:
    text = value.decode("utf-8", errors="replace")
    if len(text) <= _MAX_CANDIDATE_PREVIEW_CHARS:
        return text
    return f"{text[: _MAX_CANDIDATE_PREVIEW_CHARS - 1]}…"


def _projection_symbols(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    symbols = [text for item in value if (text := _projection_text(item, maximum=32)) is not None]
    if not symbols:
        return None
    visible = ", ".join(symbols[:3])
    return f"{visible} +{len(symbols) - 3}" if len(symbols) > 3 else visible


def _run_projection(
    *, kind: str, resource_id: str, metadata: dict[str, Any]
) -> tuple[str, str | None]:
    request = metadata.get("request")
    request = request if isinstance(request, dict) else {}
    primary = next(
        (
            text
            for value in (
                request.get("strategy_id"),
                request.get("factor_id"),
                metadata.get("strategy_id"),
                metadata.get("factor_id"),
            )
            if (text := _projection_text(value, maximum=160)) is not None
        ),
        None,
    )
    if primary is None and isinstance(request.get("factor_ids"), list):
        primary = _projection_symbols(request.get("factor_ids"))
    symbols = _projection_symbols(request.get("symbols") or metadata.get("symbols"))
    title = " · ".join(part for part in (primary, symbols) if part)
    display_title = (
        _projection_text(title or resource_id, maximum=_MAX_DISPLAY_TITLE_CHARS) or f"{kind} result"
    )

    start = _projection_text(request.get("start"), maximum=64)
    end = _projection_text(request.get("end"), maximum=64)
    provider = _projection_text(request.get("provider"), maximum=160)
    summary_parts: list[str] = []
    if start and end:
        summary_parts.append(f"{start} → {end}")
    elif start or end:
        summary_parts.append(start or end or "")
    if provider:
        summary_parts.append(f"provider {provider}")
    summary = _projection_text(" · ".join(summary_parts), maximum=_MAX_SUMMARY_CHARS)
    return display_title, summary


def _candidate_projection(
    *,
    resource_id: str,
    goal: object,
    artifact_type: object,
    universe: object,
) -> tuple[str, str | None]:
    display_title = _projection_text(goal, maximum=_MAX_DISPLAY_TITLE_CHARS) or resource_id
    summary_parts = [
        part
        for part in (
            _projection_text(artifact_type, maximum=128),
            _projection_symbols(universe),
        )
        if part
    ]
    return display_title, _projection_text(" · ".join(summary_parts), maximum=_MAX_SUMMARY_CHARS)


def _hqa_projection(artifact: dict[str, Any]) -> tuple[str, str | None]:
    kind = artifact["kind"]
    resource_id = artifact["id"]
    data = artifact.get("data")
    data = data if isinstance(data, dict) else {}
    if kind == "portfolio_risk":
        account = _projection_text(data.get("account_id"), maximum=96)
        title = f"{account} portfolio risk" if account else resource_id
        largest = _projection_text(data.get("largest_symbol"), maximum=32)
        summary = f"largest position {largest}" if largest else None
    elif kind == "prediction":
        symbol = _projection_text(data.get("symbol"), maximum=32)
        direction = _projection_text(data.get("direction"), maximum=32)
        title = " ".join(part for part in (symbol, direction, "prediction") if part)
        horizon = _projection_text(data.get("horizon_date"), maximum=64)
        confidence = data.get("confidence")
        summary = (
            f"horizon {horizon} · confidence {confidence}"
            if horizon and isinstance(confidence, (int, float))
            else (f"horizon {horizon}" if horizon else None)
        )
    elif kind == "market_foresight":
        title = _projection_text(data.get("summary"), maximum=256) or resource_id
        count = data.get("candidate_count")
        summary = f"{count} candidates" if isinstance(count, int) else None
    elif kind == "weekly_review":
        week_id = _projection_text(data.get("week_id"), maximum=64)
        title = f"Weekly review · {week_id}" if week_id else resource_id
        confirmed = data.get("review_confirmed_count")
        summary = f"{confirmed} confirmed reviews" if isinstance(confirmed, int) else None
    elif kind == "opportunity_summary":
        end = _projection_text(data.get("window_end"), maximum=64)
        title = f"Opportunity summary · {end}" if end else resource_id
        total = data.get("total_count")
        summary = f"{total} observed opportunities" if isinstance(total, int) else None
    elif kind == "automation_status":
        overall = _projection_text(data.get("overall_status"), maximum=64)
        title = f"Automation · {overall}" if overall else resource_id
        jobs = data.get("jobs")
        summary = f"{len(jobs)} scheduled jobs" if isinstance(jobs, list) else None
    else:
        title, summary = resource_id, None
    return (
        _projection_text(title, maximum=_MAX_DISPLAY_TITLE_CHARS) or resource_id,
        _projection_text(summary, maximum=_MAX_SUMMARY_CHARS),
    )


def _reject_symlink_components(root: Path, relative_paths: tuple[str, ...]) -> None:
    if root.is_symlink():
        raise ValueError("result directory symlinks are not allowed")
    for relative in relative_paths:
        current = root
        for part in Path(relative).parts:
            current /= part
            if current.is_symlink():
                raise ValueError("result artifact symlinks are not allowed")


def _read_json_object(
    path: Path,
    *,
    budget: _JsonReadBudget | None = None,
) -> dict[str, Any]:
    with _open_stable_regular_file(path) as (fd, opened):
        if opened.st_size > _MAX_REFERENCE_JSON_BYTES:
            raise ValueError("reference JSON exceeds the safe byte limit")
        raw = os.pread(fd, opened.st_size + 1, 0)
        if len(raw) != opened.st_size:
            raise ValueError("reference JSON changed during read")
        if budget is not None:
            budget.charge(len(raw))
        value = json.loads(raw.decode("utf-8", errors="strict"))
        if not isinstance(value, dict):
            raise ValueError("reference JSON must be an object")
        return value


@contextmanager
def _open_stable_regular_file(path: Path) -> Iterator[tuple[int, os.stat_result]]:
    """Hold one O_NOFOLLOW file descriptor and verify path identity before/after use."""
    fd: int | None = None
    try:
        with open_absolute_directory(path.parent, create=False) as parent:
            entry = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
            if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
                raise ValueError("result artifact must be a single-link regular file")
            fd = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent.fd,
            )
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                raise ValueError("result artifact identity changed during open")
            yield fd, opened
            final = os.fstat(fd)
            current = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
            if (final.st_dev, final.st_ino, final.st_size) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
            ) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise ValueError("result artifact identity changed during read")
            assert_entry_is_open_fd(parent.parent_fd, parent.name, parent.fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError("result artifact symlinks are not allowed") from exc
        raise
    except CandidateIntegrityError as exc:
        raise ValueError("result artifact path is not stable") from exc
    finally:
        if fd is not None:
            os.close(fd)


def _stable_regular_file_size(path: Path) -> int:
    with _open_stable_regular_file(path) as (_fd, opened):
        return opened.st_size


def _validate_parquet_metadata(
    path: Path,
    *,
    budget: _JsonReadBudget | None = None,
) -> None:
    """Validate bounded Parquet footer metadata without materializing table rows."""
    import pyarrow.parquet as pq

    with _open_stable_regular_file(path) as (fd, opened):
        if opened.st_size < 12:
            raise ValueError("parquet artifact is too small")
        if os.pread(fd, 4, 0) != b"PAR1":
            raise ValueError("parquet header is invalid")
        trailer = os.pread(fd, 8, opened.st_size - 8)
        if len(trailer) != 8 or trailer[4:] != b"PAR1":
            raise ValueError("parquet footer is invalid")
        footer_size = int.from_bytes(trailer[:4], byteorder="little", signed=False)
        if footer_size > _MAX_PARQUET_FOOTER_BYTES or footer_size + 12 > opened.st_size:
            raise ValueError("parquet footer exceeds the metadata bound")
        if budget is not None:
            # PyArrow may read the complete footer metadata. Charge it before
            # parsing so thousands of individually valid files cannot bypass
            # the source-wide metadata budget.
            budget.charge(footer_size + 12)
        with os.fdopen(os.dup(fd), "rb", closefd=True) as handle:
            _metadata = pq.ParquetFile(handle).metadata


def _completed_run_has_artifact(
    kind: str,
    run_dir: Path,
    *,
    budget: _JsonReadBudget | None = None,
) -> bool:
    required = _RUN_COMPLETION_ARTIFACTS[kind]
    _reject_symlink_components(run_dir, required)
    for relative in required:
        path = run_dir / relative
        if not path.is_file():
            return False
        if path.suffix == ".parquet":
            _validate_parquet_metadata(path, budget=budget)
        elif path.suffix == ".json":
            _read_json_object(path, budget=budget)
    return True


def _bounded_artifact_manifest(
    root: Path,
    relative_paths: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Describe a fixed artifact allowlist without loading artifact bodies."""
    _reject_symlink_components(root, relative_paths)
    manifest: list[dict[str, Any]] = []
    for relative in relative_paths:
        path = root / relative
        if not path.exists():
            continue
        manifest.append(
            {
                "path": relative,
                "size_bytes": _stable_regular_file_size(path),
            }
        )
    return manifest


def _bounded_run_resource(kind: str, resource_id: str, run_dir: Path) -> dict[str, Any]:
    """Return a bounded metadata/manifest view; never materialize parquet rows."""
    metadata = _read_json_object(run_dir / "metadata.json")
    reference_json: dict[str, dict[str, Any]] = {}
    for relative in _RUN_REFERENCE_JSON_PATHS[kind]:
        path = run_dir / relative
        if path.exists():
            reference_json[relative] = _read_json_object(path)
    return {
        "resource_id": resource_id,
        "kind": kind,
        "detail_mode": "bounded_manifest",
        "metadata": metadata,
        "reference_json": reference_json,
        "artifacts": _bounded_artifact_manifest(run_dir, _RUN_DETAIL_PATHS[kind]),
        "original_href": _ORIGINAL_HREFS[kind].format(resource_id=resource_id),
    }


def _bounded_experiment_resource(resource_id: str, experiment_dir: Path) -> dict[str, Any]:
    """Return bounded experiment JSON and file metadata without reading parquet."""
    reference_json: dict[str, dict[str, Any]] = {}
    for relative in ("metadata.json", "experiment_config.json", "agent_summary.json"):
        path = experiment_dir / relative
        if path.exists():
            reference_json[relative] = _read_json_object(path)
    return {
        "resource_id": resource_id,
        "kind": "experiment",
        "detail_mode": "bounded_manifest",
        "reference_json": reference_json,
        "artifacts": _bounded_artifact_manifest(
            experiment_dir,
            _EXPERIMENT_DETAIL_PATHS,
        ),
        "original_href": f"/api/experiments/{resource_id}",
    }


def _experiment_item(
    experiment_dir: Path,
    *,
    budget: _JsonReadBudget | None = None,
) -> dict[str, Any]:
    resource_id = experiment_dir.name
    metadata_path = experiment_dir / "metadata.json"
    summary_path = experiment_dir / "agent_summary.json"
    config_path = experiment_dir / "experiment_config.json"
    metadata: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    config: dict[str, Any] = {}
    _reject_symlink_components(experiment_dir, _EXPERIMENT_DETAIL_PATHS)
    has_authoritative_artifact = False
    for relative in _EXPERIMENT_DETAIL_PATHS:
        try:
            _stable_regular_file_size(experiment_dir / relative)
        except FileNotFoundError:
            continue
        has_authoritative_artifact = True
    if not has_authoritative_artifact:
        raise FileNotFoundError("experiment has no authoritative artifacts")
    if metadata_path.exists():
        metadata = _read_json_object(metadata_path, budget=budget)
        if metadata.get("run_id") not in {None, resource_id}:
            raise ValueError("experiment metadata identity mismatch")
        if metadata.get("kind") not in {None, "experiment"}:
            raise ValueError("experiment metadata kind mismatch")
    if summary_path.exists():
        summary = _read_json_object(summary_path, budget=budget)
    if config_path.exists():
        config = _read_json_object(config_path, budget=budget)
    display_title = (
        _projection_text(
            config.get("experiment_name") or metadata.get("experiment_name"),
            maximum=_MAX_DISPLAY_TITLE_CHARS,
        )
        or resource_id
    )
    symbols = _projection_symbols(config.get("symbols") or metadata.get("symbols"))
    best_run = _projection_text(summary.get("best_run_id"), maximum=256)
    projection_summary = _projection_text(
        " · ".join(
            part
            for part in (
                symbols,
                f"best run {best_run}" if best_run else None,
            )
            if part
        ),
        maximum=_MAX_SUMMARY_CHARS,
    )
    return {
        "kind": "experiment",
        "resource_id": resource_id,
        "display_title": display_title,
        "summary": projection_summary,
        "status": _status(metadata.get("status"), default="unknown"),
        "occurred_at": _utc_timestamp(
            metadata.get("created_at") or summary.get("created_at"),
            fallback_path=experiment_dir,
            resource_id=resource_id,
        ),
        "source": "platform_experiments",
        "authority": "platform_experiment_artifact",
        "freshness": "not_applicable",
        "read_status": "available" if metadata else "degraded",
        "detail_href": f"/api/hermes/results/experiment/{resource_id}",
        "original_href": f"/api/experiments/{resource_id}",
        "run_links": None,
    }


def _experiment_failure_item(experiment_dir: Path, *, read_status: str) -> dict[str, Any]:
    resource_id = experiment_dir.name
    return {
        "kind": "experiment",
        "resource_id": resource_id,
        "display_title": resource_id,
        "summary": None,
        "status": "unknown",
        "occurred_at": _utc_timestamp(None, fallback_path=experiment_dir, resource_id=resource_id),
        "source": "platform_experiments",
        "authority": "platform_experiment_artifact",
        "freshness": "unknown",
        "read_status": read_status,
        "detail_href": f"/api/hermes/results/experiment/{resource_id}",
        "original_href": f"/api/experiments/{resource_id}",
        "run_links": None,
    }


def _candidate_item(
    *,
    candidate_id: str,
    status: str | None,
    integrity_state: str,
    candidate_dir: Path,
    created_at: object = None,
    goal: object = None,
    artifact_type: object = None,
    universe: object = None,
    approval_binding: object = None,
) -> dict[str, Any]:
    read_status = {
        "verified": "available",
        "migration_required": "degraded",
        "corrupt": "corrupt",
    }[integrity_state]
    if approval_binding == "legacy_unbound":
        read_status = "degraded"
    display_title, summary = _candidate_projection(
        resource_id=candidate_id,
        goal=goal,
        artifact_type=artifact_type,
        universe=universe,
    )
    return {
        "kind": "factor_candidate",
        "resource_id": candidate_id,
        "display_title": display_title,
        "summary": summary,
        "status": (
            "legacy_unbound"
            if approval_binding == "legacy_unbound"
            else (status or integrity_state)
        ),
        "occurred_at": _utc_timestamp(
            created_at, fallback_path=candidate_dir, resource_id=candidate_id
        ),
        "source": "platform_candidates",
        "authority": "platform_candidate_repository",
        "freshness": "unknown" if integrity_state == "corrupt" else "not_applicable",
        "read_status": read_status,
        "detail_href": f"/api/hermes/results/factor_candidate/{candidate_id}",
        "original_href": f"/api/agent/candidates/{candidate_id}",
        "run_links": None,
    }


def _hqa_item(artifact: dict[str, Any], *, feed_stale: bool) -> dict[str, Any]:
    quality = artifact["quality"]
    read_status = {
        "available": "available",
        "degraded": "degraded",
        "not_applicable": "degraded",
        "unavailable": "unavailable",
    }[quality]
    kind = artifact["kind"]
    resource_id = artifact["id"]
    display_title, summary = _hqa_projection(artifact)
    return {
        "kind": kind,
        "resource_id": resource_id,
        "display_title": display_title,
        "summary": summary,
        "status": artifact["status"],
        "occurred_at": artifact["occurred_at"],
        "source": "hqa_artifact_feed",
        "authority": "hqa_artifact_manifest",
        "freshness": "stale" if feed_stale else "fresh",
        "read_status": read_status,
        "detail_href": f"/api/hermes/results/{kind}/{resource_id}",
        "original_href": "/api/hermes/artifacts",
        "run_links": None,
    }


def _utc_timestamp(value: object, *, fallback_path: Path, resource_id: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        text = _created_at_from_run_id(resource_id) or ""
    if text:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
    try:
        modified_at = fallback_path.stat().st_mtime
        return datetime.fromtimestamp(modified_at, tz=UTC).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return "1970-01-01T00:00:00Z"


def _run_item(
    kind: str,
    run_dir: Path,
    *,
    budget: _JsonReadBudget | None = None,
) -> dict[str, Any]:
    resource_id = run_dir.name
    metadata_path = run_dir / "metadata.json"
    metadata = _read_json_object(metadata_path, budget=budget)
    if metadata.get("run_id") not in {None, resource_id}:
        raise ValueError("run metadata identity does not match its directory")
    if metadata.get("kind") not in {None, kind}:
        raise ValueError("run metadata kind does not match its directory")
    if kind == "replication":
        result = _read_json_object(run_dir / "result.json", budget=budget)
        if result.get("run_id") not in {None, resource_id}:
            raise ValueError("replication result identity does not match its directory")
        if result.get("kind") not in {None, "replication"}:
            raise ValueError("replication result kind does not match its directory")
    display_title, summary = _run_projection(kind=kind, resource_id=resource_id, metadata=metadata)
    status = _status(metadata.get("status"))
    return {
        "kind": kind,
        "resource_id": resource_id,
        "display_title": display_title,
        "summary": summary,
        "status": status,
        "occurred_at": _utc_timestamp(
            metadata.get("created_at"), fallback_path=run_dir, resource_id=resource_id
        ),
        "source": "platform_runs",
        "authority": "platform_run_artifact",
        "freshness": "not_applicable",
        "read_status": "available" if status != "unknown" else "degraded",
        "detail_href": f"/api/hermes/results/{kind}/{resource_id}",
        "original_href": _ORIGINAL_HREFS[kind].format(resource_id=resource_id),
        "run_links": None,
    }


def _run_failure_item(kind: str, run_dir: Path, *, read_status: str) -> dict[str, Any]:
    resource_id = run_dir.name
    return {
        "kind": kind,
        "resource_id": resource_id,
        "display_title": resource_id,
        "summary": None,
        "status": "unknown",
        "occurred_at": _utc_timestamp(None, fallback_path=run_dir, resource_id=resource_id),
        "source": "platform_runs",
        "authority": "platform_run_artifact",
        "freshness": "unknown",
        "read_status": read_status,
        "detail_href": f"/api/hermes/results/{kind}/{resource_id}",
        "original_href": _ORIGINAL_HREFS[kind].format(resource_id=resource_id),
        "run_links": None,
    }


def _run_link_payload(
    link: HermesRunLink,
    *,
    platform_resource_type: str,
    platform_resource_id: str,
) -> dict[str, Any]:
    if (
        link.platform_resource_type != platform_resource_type
        or link.platform_resource_id != platform_resource_id
    ):
        raise ValueError("exact run-link identity mismatch")
    expected_digest = hermes_run_link_digest(
        command_id=link.command_id,
        platform_resource_type=link.platform_resource_type,
        platform_resource_id=link.platform_resource_id,
        relation=link.relation,
        hermes_session_id=link.hermes_session_id,
        resolved_hermes_session_id=(
            link.resolved_hermes_session_id or link.hermes_session_id
        ),
        hermes_run_id=link.hermes_run_id,
        source_event_id=link.source_event_id,
    )
    if link.link_digest != expected_digest:
        raise ValueError("exact run-link digest mismatch")
    if link.observed_at.tzinfo is None or link.observed_at.utcoffset() is None:
        raise ValueError("exact run-link observed_at must be timezone-aware")
    return {
        "command_id": str(link.command_id),
        "relation": link.relation,
        "hermes_session_id": link.hermes_session_id,
        "resolved_hermes_session_id": (
            link.resolved_hermes_session_id or link.hermes_session_id
        ),
        "hermes_run_id": link.hermes_run_id,
        "link_digest": link.link_digest,
        "source_event_id": link.source_event_id,
        "observed_at": link.observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }


class HermesResultsCatalog:
    """Build a read-only reference projection over authoritative result stores."""

    def __init__(
        self,
        *,
        api_runs_dir: Path,
        output_dir: Path | None = None,
        agent_output_dir: Path | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._api_runs_dir = Path(api_runs_dir)
        self._output_dir = Path(output_dir) if output_dir is not None else self._api_runs_dir.parent
        self._agent_output_dir = (
            Path(agent_output_dir) if agent_output_dir is not None else self._output_dir
        )
        self._settings = settings or Settings()

    def _runs(self, *, kind: str | None = None) -> _Collection:
        items: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        source_failed = False
        count_exact = True
        budget = _JsonReadBudget(remaining_bytes=_MAX_SOURCE_REFERENCE_JSON_BYTES)
        budget_exhausted = False
        if self._api_runs_dir.is_symlink():
            return _Collection(
                items=[],
                source={
                    "source": "platform_runs",
                    "read_status": "unavailable",
                    "item_count": 0,
                },
                warnings=[
                    {
                        "source": "platform_runs",
                        "code": "symlink_source_rejected",
                        "kind": None,
                        "resource_id": None,
                    }
                ],
                count_exact=False,
            )
        for run_kind, dirname in KIND_DIRS.items():
            if kind is not None and run_kind != kind:
                continue
            root = self._api_runs_dir / dirname
            if root.is_symlink():
                source_failed = True
                count_exact = False
                warnings.append(
                    {
                        "source": "platform_runs",
                        "code": "symlink_source_rejected",
                        "kind": run_kind,
                        "resource_id": None,
                    }
                )
                continue
            if not root.exists():
                continue
            try:
                entries, truncated = _bounded_directory_entries(root)
            except OSError:
                source_failed = True
                count_exact = False
                warnings.append(
                    {
                        "source": "platform_runs",
                        "code": "source_unavailable",
                        "kind": run_kind,
                        "resource_id": None,
                    }
                )
                continue
            if truncated:
                source_failed = True
                count_exact = False
                warnings.append(
                    {
                        "source": "platform_runs",
                        "code": "source_scan_limit_exceeded",
                        "kind": run_kind,
                        "resource_id": None,
                    }
                )
                # A partial directory slice cannot support an exact total or
                # stable offset. Keep detail-by-ID available, but omit this kind
                # from the catalog until a cursor/index is introduced.
                continue
            run_dirs: list[Path] = []
            for path in entries:
                if path.is_symlink():
                    source_failed = True
                    warnings.append(
                        {
                            "source": "platform_runs",
                            "code": "symlink_resource_rejected",
                            "kind": run_kind,
                            "resource_id": path.name,
                        }
                    )
                elif path.is_dir():
                    run_dirs.append(path)
            for run_dir in run_dirs:
                read_status: str | None = None
                code: str | None = None
                if not _safe_result_id(run_dir.name):
                    source_failed = True
                    warnings.append(
                        {
                            "source": "platform_runs",
                            "code": "invalid_resource_id",
                            "kind": run_kind,
                            "resource_id": run_dir.name,
                        }
                    )
                    continue
                metadata_path = run_dir / "metadata.json"
                result_path = run_dir / "result.json"
                if metadata_path.is_symlink() or (
                    run_kind == "replication" and result_path.is_symlink()
                ):
                    read_status, code = "corrupt", "symlink_resource_rejected"
                elif not metadata_path.is_file() or (
                    run_kind == "replication" and not result_path.is_file()
                ):
                    read_status, code = "missing", "result_missing"
                else:
                    try:
                        item = _run_item(run_kind, run_dir, budget=budget)
                        if item[
                            "status"
                        ].casefold() == "completed" and not _completed_run_has_artifact(
                            run_kind,
                            run_dir,
                            budget=budget,
                        ):
                            read_status, code = "missing", "completion_artifact_missing"
                        else:
                            items.append(item)
                            if item["read_status"] != "available":
                                source_failed = True
                                warnings.append(
                                    {
                                        "source": "platform_runs",
                                        "code": "run_status_missing",
                                        "kind": run_kind,
                                        "resource_id": run_dir.name,
                                    }
                                )
                    except HermesResultSourceBudgetExceeded:
                        source_failed = True
                        count_exact = False
                        budget_exhausted = True
                        warnings.append(
                            {
                                "source": "platform_runs",
                                "code": "source_read_budget_exceeded",
                                "kind": run_kind,
                                "resource_id": None,
                            }
                        )
                        break
                    except PermissionError:
                        read_status, code = "unavailable", "result_unavailable"
                    except (
                        OSError,
                        json.JSONDecodeError,
                        TypeError,
                        ValueError,
                        OverflowError,
                        RecursionError,
                    ):
                        read_status, code = "corrupt", "result_corrupt"
                if read_status is not None and code is not None:
                    source_failed = True
                    items.append(_run_failure_item(run_kind, run_dir, read_status=read_status))
                    warnings.append(
                        {
                            "source": "platform_runs",
                            "code": code,
                            "kind": run_kind,
                            "resource_id": run_dir.name,
                        }
                    )
            if budget_exhausted:
                break
        return _Collection(
            items=items,
            source={
                "source": "platform_runs",
                "read_status": (
                    "degraded" if source_failed else ("available" if items else "empty")
                ),
                "item_count": len(items),
            },
            warnings=warnings,
            count_exact=count_exact,
        )

    def _experiments(self) -> _Collection:
        root = self._output_dir / "experiments"
        if root.is_symlink():
            return _Collection(
                items=[],
                source={
                    "source": "platform_experiments",
                    "read_status": "unavailable",
                    "item_count": 0,
                },
                warnings=[
                    {
                        "source": "platform_experiments",
                        "code": "symlink_source_rejected",
                        "kind": None,
                        "resource_id": None,
                    }
                ],
            )
        if not root.exists():
            return _Collection(
                items=[],
                source={
                    "source": "platform_experiments",
                    "read_status": "empty",
                    "item_count": 0,
                },
                warnings=[],
            )
        try:
            entries, truncated = _bounded_directory_entries(root)
        except OSError:
            return _Collection(
                items=[],
                source={
                    "source": "platform_experiments",
                    "read_status": "unavailable",
                    "item_count": 0,
                },
                warnings=[
                    {
                        "source": "platform_experiments",
                        "code": "source_unavailable",
                        "kind": None,
                        "resource_id": None,
                    }
                ],
            )
        experiment_dirs: list[Path] = []
        entry_warnings: list[dict[str, Any]] = []
        if truncated:
            return _Collection(
                items=[],
                source={
                    "source": "platform_experiments",
                    "read_status": "unavailable",
                    "item_count": 0,
                },
                warnings=[
                    {
                        "source": "platform_experiments",
                        "code": "source_scan_limit_exceeded",
                        "kind": "experiment",
                        "resource_id": None,
                    }
                ],
            )
        for path in entries:
            if path.is_symlink():
                entry_warnings.append(
                    {
                        "source": "platform_experiments",
                        "code": "symlink_resource_rejected",
                        "kind": "experiment",
                        "resource_id": path.name,
                    }
                )
            elif path.is_dir():
                experiment_dirs.append(path)
        items: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = entry_warnings
        budget = _JsonReadBudget(remaining_bytes=_MAX_SOURCE_REFERENCE_JSON_BYTES)
        count_exact = True
        for experiment_dir in experiment_dirs:
            if not _safe_result_id(experiment_dir.name):
                warnings.append(
                    {
                        "source": "platform_experiments",
                        "code": "invalid_resource_id",
                        "kind": "experiment",
                        "resource_id": experiment_dir.name,
                    }
                )
                continue
            try:
                item = _experiment_item(experiment_dir, budget=budget)
                items.append(item)
                if item["read_status"] != "available":
                    warnings.append(
                        {
                            "source": "platform_experiments",
                            "code": "experiment_metadata_missing",
                            "kind": "experiment",
                            "resource_id": experiment_dir.name,
                        }
                    )
            except HermesResultSourceBudgetExceeded:
                count_exact = False
                warnings.append(
                    {
                        "source": "platform_experiments",
                        "code": "source_read_budget_exceeded",
                        "kind": "experiment",
                        "resource_id": None,
                    }
                )
                break
            except FileNotFoundError:
                read_status, code = "missing", "result_missing"
            except PermissionError:
                read_status, code = "unavailable", "result_unavailable"
            except (
                OSError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
                OverflowError,
                RecursionError,
            ):
                read_status, code = "corrupt", "result_corrupt"
            else:
                continue
            items.append(_experiment_failure_item(experiment_dir, read_status=read_status))
            warnings.append(
                {
                    "source": "platform_experiments",
                    "code": code,
                    "kind": "experiment",
                    "resource_id": experiment_dir.name,
                }
            )
        return _Collection(
            items=items,
            source={
                "source": "platform_experiments",
                "read_status": ("degraded" if warnings else ("available" if items else "empty")),
                "item_count": len(items),
            },
            warnings=warnings,
            count_exact=count_exact,
        )

    def _candidates(self) -> _Collection:
        pool = CandidatePool(self._agent_output_dir)
        try:
            read_items = pool.list_for_read(max_entries=_MAX_CANDIDATE_SOURCE_ENTRIES)
        except CandidatePoolScanLimitExceeded:
            return _Collection(
                items=[],
                source={
                    "source": "platform_candidates",
                    "read_status": "unavailable",
                    "item_count": 0,
                },
                warnings=[
                    {
                        "source": "platform_candidates",
                        "code": "source_scan_limit_exceeded",
                        "kind": "factor_candidate",
                        "resource_id": None,
                    }
                ],
                count_exact=False,
            )
        except (
            CandidateIntegrityError,
            OSError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            return _Collection(
                items=[],
                source={
                    "source": "platform_candidates",
                    "read_status": "unavailable",
                    "item_count": 0,
                },
                warnings=[
                    {
                        "source": "platform_candidates",
                        "code": "source_unavailable",
                        "kind": None,
                        "resource_id": None,
                    }
                ],
            )
        items: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for read_item in read_items:
            if not _safe_result_id(read_item.candidate_id):
                warnings.append(
                    {
                        "source": "platform_candidates",
                        "code": "invalid_resource_id",
                        "kind": "factor_candidate",
                        "resource_id": read_item.candidate_id,
                    }
                )
                continue
            candidate_dir = pool.candidates_dir / read_item.candidate_id
            integrity_state = read_item.integrity_state
            try:
                item = _candidate_item(
                    candidate_id=read_item.candidate_id,
                    status=read_item.status,
                    integrity_state=integrity_state,
                    candidate_dir=candidate_dir,
                    created_at=read_item.created_at,
                    goal=read_item.goal,
                    artifact_type=read_item.artifact_type,
                    universe=read_item.universe,
                    approval_binding=(
                        read_item.approval_binding if integrity_state != "corrupt" else None
                    ),
                )
            except (TypeError, ValueError, OverflowError, RecursionError):
                integrity_state = "corrupt"
                item = _candidate_item(
                    candidate_id=read_item.candidate_id,
                    status=None,
                    integrity_state=integrity_state,
                    candidate_dir=candidate_dir,
                    created_at=None,
                )
            items.append(item)
            if item["read_status"] != "available":
                warnings.append(
                    {
                        "source": "platform_candidates",
                        "code": (
                            "candidate_migration_required"
                            if integrity_state == "migration_required"
                            else (
                                "candidate_legacy_unbound"
                                if read_item.approval_binding == "legacy_unbound"
                                and integrity_state == "verified"
                                else "result_corrupt"
                            )
                        ),
                        "kind": "factor_candidate",
                        "resource_id": read_item.candidate_id,
                    }
                )
        return _Collection(
            items=items,
            source={
                "source": "platform_candidates",
                "read_status": ("degraded" if warnings else ("available" if items else "empty")),
                "item_count": len(items),
            },
            warnings=warnings,
        )

    def _artifact_feed(self) -> dict[str, Any]:
        artifact_settings = self._settings.hermes_artifacts
        return HermesArtifactCatalog(
            artifact_settings.feed_path,
            freshness_budget_seconds=artifact_settings.freshness_budget_seconds,
            max_future_clock_skew_seconds=(artifact_settings.max_future_clock_skew_seconds),
            max_manifest_bytes=artifact_settings.max_manifest_bytes,
        # The manifest byte limit bounds full validation. Preserve the complete
        # validated feed here so exact-ID detail lookup cannot misreport an
        # older artifact as missing merely because the list projection is
        # capped below.
        ).latest(limit=None)

    def _hqa_artifacts(self) -> _Collection:
        try:
            feed = self._artifact_feed()
        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            return _Collection(
                items=[],
                source={
                    "source": "hqa_artifact_feed",
                    "read_status": "unavailable",
                    "item_count": 0,
                },
                warnings=[
                    {
                        "source": "hqa_artifact_feed",
                        "code": "source_unavailable",
                        "kind": None,
                        "resource_id": None,
                    }
                ],
            )
        feed_stale = any(warning.get("code") == "feed_stale" for warning in feed["warnings"])
        feed_truncated = len(feed["items"]) > _MAX_HQA_SOURCE_ENTRIES
        items: list[dict[str, Any]] = []
        invalid_id_warnings: list[dict[str, Any]] = []
        for item in feed["items"][:_MAX_HQA_SOURCE_ENTRIES]:
            if not _safe_result_id(item["id"]):
                invalid_id_warnings.append(
                    {
                        "source": "hqa_artifact_feed",
                        "code": "invalid_resource_id",
                        "kind": item["kind"],
                        "resource_id": item["id"],
                    }
                )
                continue
            items.append(_hqa_item(item, feed_stale=feed_stale))
        warnings = [
            {
                "source": "hqa_artifact_feed",
                "code": _warning_code(warning.get("code")),
                "kind": None,
                "resource_id": None,
            }
            for warning in feed["warnings"]
        ] + invalid_id_warnings
        if feed_truncated:
            warnings.append(
                {
                    "source": "hqa_artifact_feed",
                    "code": "source_scan_limit_exceeded",
                    "kind": None,
                    "resource_id": None,
                }
            )
        source_status = feed["read_status"]
        if source_status == "available" and (
            feed_truncated
            or invalid_id_warnings
            or any(item["read_status"] != "available" for item in items)
        ):
            source_status = "degraded"
        return _Collection(
            items=items,
            source={
                "source": "hqa_artifact_feed",
                "read_status": source_status,
                "item_count": len(items),
            },
            warnings=warnings,
            count_exact=not feed_truncated,
        )

    def list(
        self,
        *,
        limit: int,
        offset: int,
        kind: str | None = None,
        status: str | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        kind_source = {
            **{run_kind: "platform_runs" for run_kind in KIND_DIRS},
            "experiment": "platform_experiments",
            "factor_candidate": "platform_candidates",
            **{hqa_kind: "hqa_artifact_feed" for hqa_kind in _HQA_KINDS},
        }
        requested_source = source or (kind_source.get(kind) if kind is not None else None)
        providers = {
            "platform_runs": lambda: self._runs(kind=kind if kind in KIND_DIRS else None),
            "platform_experiments": self._experiments,
            "platform_candidates": self._candidates,
            "hqa_artifact_feed": self._hqa_artifacts,
        }
        collections = [
            provider()
            for provider_source, provider in providers.items()
            if requested_source is None or provider_source == requested_source
        ]
        items = [item for collection in collections for item in collection.items]
        if kind is not None:
            items = [item for item in items if item["kind"] == kind]
        if status is not None:
            normalized_status = status.casefold()
            items = [item for item in items if str(item["status"]).casefold() == normalized_status]
        if source is not None:
            items = [item for item in items if item["source"] == source]
        if search is not None:
            term = search.casefold()
            items = [
                item
                for item in items
                if term
                in " ".join(
                    part
                    for part in (
                        item["resource_id"],
                        item["kind"],
                        item["status"],
                        item["display_title"],
                        item["summary"],
                    )
                    if isinstance(part, str)
                ).casefold()
            ]
        items.sort(
            key=lambda item: (item["occurred_at"], item["kind"], item["resource_id"]),
            reverse=True,
        )
        total_is_exact = all(_collection_count_is_exact(collection) for collection in collections)
        total = len(items) if total_is_exact else None
        page = items[offset : offset + limit]
        page, link_collection = self._attach_exact_run_links(
            page,
            limit_per_resource=_MAX_LIST_RUN_LINKS_PER_RESOURCE,
        )
        status_collections = [*collections, link_collection]
        read_status = _aggregate_status(collections, has_items=bool(items))
        if read_status != "unavailable" and link_collection.source["read_status"] in {
            "degraded",
            "unavailable",
        }:
            read_status = "degraded"
        return {
            "read_status": read_status,
            "total": total,
            "total_is_exact": total_is_exact,
            "limit": limit,
            "offset": offset,
            # Unknown global total does not erase pagination over the records
            # that were safely enumerated before a source degraded.
            "has_more": offset + len(page) < len(items),
            "items": page,
            "sources": [collection.source for collection in status_collections],
            "warnings": _bounded_warnings(
                [warning for collection in status_collections for warning in collection.warnings]
            ),
        }

    def _attach_exact_run_links(
        self,
        items: list[dict[str, Any]],
        *,
        limit_per_resource: int = _MAX_DETAIL_RUN_LINKS_PER_RESOURCE,
    ) -> tuple[list[dict[str, Any]], _Collection]:
        if not self._settings.database.enabled:
            return items, _Collection(
                items=[],
                source={
                    "source": "platform_run_links",
                    "read_status": "unavailable",
                    "item_count": 0,
                },
                warnings=[
                    {
                        "source": "platform_run_links",
                        "code": "exact_links_not_configured",
                        "kind": None,
                        "resource_id": None,
                    }
                ],
            )
        ledger = HermesCommandLedger(self._settings)
        linked_items: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        link_count = 0
        if not items:
            return items, _Collection(
                items=[],
                source={
                    "source": "platform_run_links",
                    "read_status": "empty",
                    "item_count": 0,
                },
                warnings=[],
            )
        resources = tuple(dict.fromkeys((item["kind"], item["resource_id"]) for item in items))
        try:
            pages = ledger.list_run_links_for_resources(
                resources=resources,
                limit_per_resource=limit_per_resource,
            )
        except (HermesCommandLedgerUnavailable, HermesCommandValidationError):
            for item in items:
                linked_item = dict(item)
                linked_item["run_links"] = None
                linked_items.append(linked_item)
                warnings.append(
                    {
                        "source": "platform_run_links",
                        "code": "exact_links_unavailable",
                        "kind": item["kind"],
                        "resource_id": item["resource_id"],
                    }
                )
            return linked_items, _Collection(
                items=[],
                source={
                    "source": "platform_run_links",
                    "read_status": "unavailable",
                    "item_count": 0,
                },
                warnings=warnings,
            )
        for item in items:
            linked_item = dict(item)
            resource = (item["kind"], item["resource_id"])
            try:
                page: HermesRunLinkPage = pages[resource]
            except (KeyError, TypeError):
                linked_item["run_links"] = None
                warnings.append(
                    {
                        "source": "platform_run_links",
                        "code": "exact_links_unavailable",
                        "kind": item["kind"],
                        "resource_id": item["resource_id"],
                    }
                )
            else:
                if page.has_more:
                    linked_item["run_links"] = None
                    warnings.append(
                        {
                            "source": "platform_run_links",
                            "code": "exact_links_truncated",
                            "kind": item["kind"],
                            "resource_id": item["resource_id"],
                        }
                    )
                else:
                    try:
                        payloads = [
                            _run_link_payload(
                                link,
                                platform_resource_type=item["kind"],
                                platform_resource_id=item["resource_id"],
                            )
                            for link in page.links
                        ]
                    except (
                        HermesCommandValidationError,
                        AttributeError,
                        TypeError,
                        ValueError,
                        OverflowError,
                        RecursionError,
                    ):
                        linked_item["run_links"] = None
                        warnings.append(
                            {
                                "source": "platform_run_links",
                                "code": "exact_link_integrity_failed",
                                "kind": item["kind"],
                                "resource_id": item["resource_id"],
                            }
                        )
                    else:
                        linked_item["run_links"] = payloads
                        link_count += len(payloads)
            linked_items.append(linked_item)
        read_status = "degraded" if warnings else ("available" if link_count else "empty")
        return linked_items, _Collection(
            items=[],
            source={
                "source": "platform_run_links",
                "read_status": read_status,
                "item_count": link_count,
            },
            warnings=warnings,
        )

    def detail(self, *, kind: str, resource_id: str) -> dict[str, Any]:
        result = self._detail_without_links(kind=kind, resource_id=resource_id)
        if result["item"] is None:
            result = dict(result)
            result["warnings"] = _bounded_warnings(result["warnings"], limit=_MAX_DETAIL_WARNINGS)
            return result
        linked_items, link_collection = self._attach_exact_run_links([result["item"]])
        result = dict(result)
        result["item"] = linked_items[0]
        result["warnings"] = _bounded_warnings(
            [*result["warnings"], *link_collection.warnings],
            limit=_MAX_DETAIL_WARNINGS,
        )
        if result["read_status"] == "available" and link_collection.source["read_status"] in {
            "degraded",
            "unavailable",
        }:
            result["read_status"] = "degraded"
        return result

    def _detail_without_links(self, *, kind: str, resource_id: str) -> dict[str, Any]:
        if kind == "experiment":
            return self._experiment_detail(resource_id)
        if kind == "factor_candidate":
            return self._candidate_detail(resource_id)
        if kind in _HQA_KINDS:
            return self._hqa_detail(kind=kind, resource_id=resource_id)
        dirname = KIND_DIRS.get(kind)
        if dirname is None:
            return self._detail_failure(
                kind=kind,
                resource_id=resource_id,
                read_status="missing",
                code="result_not_found",
            )
        run_root = self._api_runs_dir / dirname
        try:
            if self._api_runs_dir.is_symlink() or run_root.is_symlink():
                raise ValueError("result source symlinks are not allowed")
            if (run_root / resource_id).is_symlink():
                raise ValueError("result directory symlinks are not allowed")
            run_dir = resolve_run_dir(run_root, resource_id)
        except FileNotFoundError:
            return self._detail_failure(
                kind=kind,
                resource_id=resource_id,
                read_status="missing",
                code="result_not_found",
            )
        except ValueError:
            return self._detail_failure(
                kind=kind,
                resource_id=resource_id,
                read_status="corrupt",
                code="result_corrupt",
            )
        if not (run_dir / "metadata.json").is_file():
            return self._detail_failure(
                kind=kind,
                resource_id=resource_id,
                read_status="missing",
                code="result_not_found",
            )
        try:
            _reject_symlink_components(run_dir, _RUN_DETAIL_PATHS[kind])
            item = _run_item(kind, run_dir)
            if item["status"].casefold() == "completed" and not _completed_run_has_artifact(
                kind, run_dir
            ):
                return self._detail_failure(
                    kind=kind,
                    resource_id=resource_id,
                    read_status="missing",
                    code="completion_artifact_missing",
                )
            resource = _bounded_run_resource(kind, resource_id, run_dir)
            _ensure_resource_bound(resource)
        except HermesResultResourceTooLarge:
            return _oversized_detail(
                item=item,
                source="platform_runs",
                kind=kind,
                resource_id=resource_id,
            )
        except PermissionError:
            return self._detail_failure(
                kind=kind,
                resource_id=resource_id,
                read_status="unavailable",
                code="result_unavailable",
            )
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            ValidationError,
            AttributeError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            return self._detail_failure(
                kind=kind,
                resource_id=resource_id,
                read_status="corrupt",
                code="result_corrupt",
            )
        except OSError:
            return self._detail_failure(
                kind=kind,
                resource_id=resource_id,
                read_status="unavailable",
                code="result_unavailable",
            )
        return {
            "read_status": item["read_status"],
            "item": item,
            "resource": resource,
            "warnings": []
            if item["read_status"] == "available"
            else [
                {
                    "source": "platform_runs",
                    "code": "run_status_missing",
                    "kind": kind,
                    "resource_id": resource_id,
                }
            ],
        }

    def _candidate_detail(self, resource_id: str) -> dict[str, Any]:
        pool = CandidatePool(self._agent_output_dir)
        try:
            read_item = pool.read_for_read(resource_id)
            if read_item is None:
                return self._detail_failure_for_source(
                    source="platform_candidates",
                    kind="factor_candidate",
                    resource_id=resource_id,
                    read_status="missing",
                    code="result_not_found",
                )
            integrity_state = read_item.integrity_state
            candidate_dir = pool.candidates_dir / resource_id
            metadata: dict[str, Any] | None = None
            source_preview: str | None = None
            reviews: list[str] = []
            manifest_digest = read_item.manifest_digest
            approval_binding = read_item.approval_binding
            if integrity_state == "verified":
                snapshot = pool.get(resource_id)
                if not isinstance(snapshot.metadata, dict):
                    raise TypeError("candidate metadata must be an object")
                metadata = snapshot.metadata
                manifest_digest = snapshot.manifest_digest
                approval_binding = snapshot.approval_binding
                if snapshot.manifest.files:
                    first = snapshot.manifest.files[0].path
                    source_preview = _bounded_preview(snapshot.artifact_bytes.get(first, b""))
                if snapshot.review_record is not None:
                    # Only the exact digest-bound control read by CandidatePool is
                    # authoritative. Legacy reviews.jsonl and global audit logs are
                    # intentionally absent from this safety projection.
                    reviews = [snapshot.review_record.model_dump_json()]
            item = _candidate_item(
                candidate_id=resource_id,
                status=read_item.status,
                integrity_state=integrity_state,
                candidate_dir=candidate_dir,
                created_at=(metadata or {}).get("created_at"),
                goal=read_item.goal,
                artifact_type=read_item.artifact_type,
                universe=read_item.universe,
                approval_binding=approval_binding,
            )
            resource = {
                "candidate_id": resource_id,
                "metadata": metadata,
                "source_preview": source_preview,
                "audit": [],
                "reviews": reviews,
                "integrity_state": integrity_state,
                "manifest_digest": manifest_digest,
                "observed_manifest_digest": read_item.observed_manifest_digest,
                "approval_binding": approval_binding,
                "approval_enabled": approval_binding == "pending",
                "integrity_error_code": read_item.integrity_error_code,
                "status": read_item.status,
            }
            _ensure_resource_bound(resource)
        except HermesResultResourceTooLarge:
            return _oversized_detail(
                item=item,
                source="platform_candidates",
                kind="factor_candidate",
                resource_id=resource_id,
            )
        except PermissionError:
            return self._detail_failure_for_source(
                source="platform_candidates",
                kind="factor_candidate",
                resource_id=resource_id,
                read_status="unavailable",
                code="result_unavailable",
            )
        except (
            CandidateIntegrityError,
            ValidationError,
            AttributeError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            return self._detail_failure_for_source(
                source="platform_candidates",
                kind="factor_candidate",
                resource_id=resource_id,
                read_status="corrupt",
                code="result_corrupt",
            )
        except OSError:
            return self._detail_failure_for_source(
                source="platform_candidates",
                kind="factor_candidate",
                resource_id=resource_id,
                read_status="unavailable",
                code="result_unavailable",
            )
        warning_code: str | None = None
        if integrity_state == "migration_required":
            warning_code = "candidate_migration_required"
        elif integrity_state == "corrupt":
            warning_code = "result_corrupt"
        elif approval_binding == "legacy_unbound":
            warning_code = "candidate_legacy_unbound"
        return {
            "read_status": item["read_status"],
            "item": item,
            "resource": None if integrity_state == "corrupt" else resource,
            "warnings": []
            if warning_code is None
            else [
                {
                    "source": "platform_candidates",
                    "code": warning_code,
                    "kind": "factor_candidate",
                    "resource_id": resource_id,
                }
            ],
        }

    def _hqa_detail(self, *, kind: str, resource_id: str) -> dict[str, Any]:
        try:
            feed = self._artifact_feed()
        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            return self._detail_failure_for_source(
                source="hqa_artifact_feed",
                kind=kind,
                resource_id=resource_id,
                read_status="unavailable",
                code="source_unavailable",
            )
        if feed["read_status"] == "unavailable":
            code = (
                _warning_code(feed["warnings"][0].get("code"))
                if feed["warnings"]
                else "source_unavailable"
            )
            return self._detail_failure_for_source(
                source="hqa_artifact_feed",
                kind=kind,
                resource_id=resource_id,
                read_status="unavailable",
                code=code,
            )
        resource = next(
            (item for item in feed["items"] if item["kind"] == kind and item["id"] == resource_id),
            None,
        )
        if resource is None:
            return self._detail_failure_for_source(
                source="hqa_artifact_feed",
                kind=kind,
                resource_id=resource_id,
                read_status="missing",
                code="result_not_found",
            )
        feed_stale = any(warning.get("code") == "feed_stale" for warning in feed["warnings"])
        try:
            item = _hqa_item(resource, feed_stale=feed_stale)
            _ensure_resource_bound(resource)
        except HermesResultResourceTooLarge:
            return _oversized_detail(
                item=item,
                source="hqa_artifact_feed",
                kind=kind,
                resource_id=resource_id,
            )
        except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
            return self._detail_failure_for_source(
                source="hqa_artifact_feed",
                kind=kind,
                resource_id=resource_id,
                read_status="corrupt",
                code="result_corrupt",
            )
        warnings = [
            {
                "source": "hqa_artifact_feed",
                "code": _warning_code(warning.get("code")),
                "kind": kind,
                "resource_id": resource_id,
            }
            for warning in feed["warnings"]
        ]
        if item["read_status"] != "available" and not warnings:
            warnings.append(
                {
                    "source": "hqa_artifact_feed",
                    "code": "artifact_quality_degraded",
                    "kind": kind,
                    "resource_id": resource_id,
                }
            )
        return {
            "read_status": item["read_status"],
            "item": item,
            "resource": resource,
            "warnings": warnings,
        }

    def _experiment_detail(self, resource_id: str) -> dict[str, Any]:
        experiment_root = self._output_dir / "experiments"
        try:
            if experiment_root.is_symlink():
                raise ValueError("experiment source symlinks are not allowed")
            if (experiment_root / resource_id).is_symlink():
                raise ValueError("experiment directory symlinks are not allowed")
            experiment_dir = resolve_run_dir(experiment_root, resource_id)
        except FileNotFoundError:
            return self._detail_failure_for_source(
                source="platform_experiments",
                kind="experiment",
                resource_id=resource_id,
                read_status="missing",
                code="result_not_found",
            )
        except ValueError:
            return self._detail_failure_for_source(
                source="platform_experiments",
                kind="experiment",
                resource_id=resource_id,
                read_status="corrupt",
                code="result_corrupt",
            )
        if not experiment_dir.is_dir():
            return self._detail_failure_for_source(
                source="platform_experiments",
                kind="experiment",
                resource_id=resource_id,
                read_status="missing",
                code="result_not_found",
            )
        try:
            _reject_symlink_components(experiment_dir, _EXPERIMENT_DETAIL_PATHS)
            item = _experiment_item(experiment_dir)
            resource = _bounded_experiment_resource(resource_id, experiment_dir)
            _ensure_resource_bound(resource)
        except HermesResultResourceTooLarge:
            return _oversized_detail(
                item=item,
                source="platform_experiments",
                kind="experiment",
                resource_id=resource_id,
            )
        except FileNotFoundError:
            return self._detail_failure_for_source(
                source="platform_experiments",
                kind="experiment",
                resource_id=resource_id,
                read_status="missing",
                code="result_not_found",
            )
        except PermissionError:
            return self._detail_failure_for_source(
                source="platform_experiments",
                kind="experiment",
                resource_id=resource_id,
                read_status="unavailable",
                code="result_unavailable",
            )
        except (
            json.JSONDecodeError,
            ValidationError,
            AttributeError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ):
            return self._detail_failure_for_source(
                source="platform_experiments",
                kind="experiment",
                resource_id=resource_id,
                read_status="corrupt",
                code="result_corrupt",
            )
        except OSError:
            return self._detail_failure_for_source(
                source="platform_experiments",
                kind="experiment",
                resource_id=resource_id,
                read_status="unavailable",
                code="result_unavailable",
            )
        return {
            "read_status": item["read_status"],
            "item": item,
            "resource": resource,
            "warnings": []
            if item["read_status"] == "available"
            else [
                {
                    "source": "platform_experiments",
                    "code": "experiment_metadata_missing",
                    "kind": "experiment",
                    "resource_id": resource_id,
                }
            ],
        }

    @staticmethod
    def _detail_failure(
        *,
        kind: str,
        resource_id: str,
        read_status: str,
        code: str,
    ) -> dict[str, Any]:
        return HermesResultsCatalog._detail_failure_for_source(
            source="platform_runs",
            kind=kind,
            resource_id=resource_id,
            read_status=read_status,
            code=code,
        )

    @staticmethod
    def _detail_failure_for_source(
        *,
        source: str,
        kind: str,
        resource_id: str,
        read_status: str,
        code: str,
    ) -> dict[str, Any]:
        return {
            "read_status": read_status,
            "item": None,
            "resource": None,
            "warnings": [
                {
                    "source": source,
                    "code": code,
                    "kind": kind,
                    "resource_id": resource_id,
                }
            ],
        }


def _aggregate_status(collections: list[_Collection], *, has_items: bool) -> str:
    statuses = {collection.source["read_status"] for collection in collections}
    if statuses == {"unavailable"}:
        return "unavailable"
    if statuses & {"degraded", "unavailable"}:
        return "degraded"
    return "available" if has_items else "empty"


def _collection_count_is_exact(collection: _Collection) -> bool:
    if not collection.count_exact or collection.source["read_status"] == "unavailable":
        return False
    incomplete_codes = {
        "invalid_resource_id",
        "source_scan_limit_exceeded",
        "source_read_budget_exceeded",
        "source_unavailable",
        "symlink_resource_rejected",
        "symlink_source_rejected",
        "feed_missing",
        "feed_corrupt",
        "feed_unavailable",
    }
    return not any(warning.get("code") in incomplete_codes for warning in collection.warnings)
