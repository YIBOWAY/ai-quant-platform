"""Canonical dual-engine evidence generator for one registered factor."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from quant_system.config.settings import Settings
from quant_system.d34.engine_comparison import (
    ComparisonPolicy,
    EngineReceipt,
    compare_engine_receipts,
)
from quant_system.d34.market_data_snapshot import create_market_data_snapshot
from quant_system.d34.research_request import (
    LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
    digest_document,
)
from quant_system.factors.library.promoted.agent_candidate_wave2_sceneb_mom20_v3 import (
    AgentCandidateFactor,
)
from quant_system.factors.library.promoted.paper_reversal_momentum_proxy_v2 import (
    PaperReversalMomentumProxyV2,
)
from quant_system.factors.registry import build_factor_registry
from quant_system.options.seller_score import latest_us_market_session

REGISTERED_EVIDENCE_CONTRACT = "hqa.registered_factor_evidence/v1"
_MARKET_TZ = ZoneInfo("America/New_York")
class RegisteredVerificationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RegisteredVerificationBoundary(Protocol):
    provider_name: str

    def fetch_ohlcv(self, symbols, *, start, end, interval): ...

    def run(self, **kwargs): ...

    def replay(self, **kwargs): ...


@dataclass(frozen=True)
class RegisteredFactorEvidence:
    job_id: str
    run_id: str
    root: Path
    manifest: dict[str, Any]


@dataclass(frozen=True)
class RegisteredFactorSpec:
    factor_type: type
    compute_source_digest: str
    qlib_expression: str

    @property
    def expression_digest(self) -> str:
        return digest_document(
            {
                "contract": "hqa.registered_factor_adapter/v1",
                "compute_source_digest": self.compute_source_digest,
                "factor_id": self.factor_type.factor_id,
                "qlib_expression": self.qlib_expression,
            }
        )


_REGISTERED_FACTOR_SPECS = {
    AgentCandidateFactor.factor_id: RegisteredFactorSpec(
        factor_type=AgentCandidateFactor,
        compute_source_digest=(
            "2643e77ed4fbb51f6f70a5373b5b88c70dea8cacfffa3bb97b6bb10c09f14f06"
        ),
        qlib_expression="$close/Ref($close,20)-1",
    ),
    PaperReversalMomentumProxyV2.factor_id: RegisteredFactorSpec(
        factor_type=PaperReversalMomentumProxyV2,
        compute_source_digest=(
            "9defde9e235008975cb0379529ffe152e558b1efb350904793ec81b3f0bcb140"
        ),
        qlib_expression=(
            "-($close/Ref($close,21)-1)+(Ref($close,21)/Ref($close,252)-1)"
        ),
    ),
}


def registered_factor_spec(factor: object) -> RegisteredFactorSpec:
    factor_id = str(getattr(factor, "factor_id", ""))
    spec = _REGISTERED_FACTOR_SPECS.get(factor_id)
    try:
        compute_source = inspect.getsource(type(factor)._compute_values).encode("utf-8")
    except (OSError, TypeError) as exc:
        raise RegisteredVerificationError("registered_factor_not_supported") from exc
    if (
        spec is None
        or type(factor) is not spec.factor_type
        or hashlib.sha256(compute_source).hexdigest() != spec.compute_source_digest
    ):
        raise RegisteredVerificationError("registered_factor_not_supported")
    return spec


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            dict(document),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite")),
    )
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _engine_receipt(
    raw_path: Path,
    *,
    engine: str,
    job_id: str,
    run_id: str,
    factor_id: str | None = None,
    source_digest: str | None = None,
    qlib_expression: str | None = None,
) -> EngineReceipt:
    try:
        document = _read_json(raw_path)
        receipt_digest = str(document.pop("receipt_digest"))
        daily_returns = document.get("daily_returns")
        return_dates = document.get("return_dates")
        terminal_nav = document.get("terminal_nav")
        terminal_weights = document.get("terminal_weights")
        qlib_config = document.get("qlib_config")
        if (
            document.get("contract") != "hqa.d34_engine_receipt/v1"
            or document.get("engine") != engine
            or document.get("job_id") != job_id
            or document.get("run_id") != run_id
            or receipt_digest != digest_document(document)
            or type(daily_returns) is not list
            or not daily_returns
            or any(
                type(value) not in {int, float} or not math.isfinite(float(value))
                for value in daily_returns
            )
            or type(return_dates) is not list
            or len(return_dates) != len(daily_returns)
            or any(type(value) is not str or not value for value in return_dates)
            or type(terminal_nav) not in {int, float}
            or not math.isfinite(float(terminal_nav))
            or type(terminal_weights) is not dict
            or any(
                type(symbol) is not str
                or not symbol
                or type(weight) not in {int, float}
                or not math.isfinite(float(weight))
                for symbol, weight in terminal_weights.items()
            )
            or (
                factor_id is not None
                and (
                    document.get("factor_id") != factor_id
                    or document.get("source_digest") != source_digest
                    or type(qlib_config) is not dict
                    or qlib_config.get("expression") != qlib_expression
                    or document.get("qlib_config_digest") != digest_document(qlib_config)
                )
            )
        ):
            raise ValueError("receipt lineage mismatch")
        return EngineReceipt(
            engine=engine,  # type: ignore[arg-type]
            snapshot_digest=str(document["snapshot_digest"]),
            universe_digest=str(document["universe_digest"]),
            calendar_digest=str(document["calendar_digest"]),
            target_weights_digest=str(document["target_weights_digest"]),
            daily_returns=tuple(float(value) for value in document["daily_returns"]),
            return_dates=tuple(str(value) for value in document["return_dates"]),
            terminal_nav=float(document["terminal_nav"]),
            terminal_weights={
                str(key): float(value)
                for key, value in dict(document["terminal_weights"]).items()
            },
            receipt_digest=receipt_digest,
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RegisteredVerificationError("registered_engine_receipt_invalid") from exc


def _container_path(workspace: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(workspace.resolve())
    except ValueError as exc:
        raise RegisteredVerificationError("registered_evidence_path_invalid") from exc
    return f"/workspace/d34/{relative.as_posix()}"


def _host_path(workspace: Path, raw: object) -> Path:
    value = str(raw or "")
    prefix = "/workspace/d34/"
    if not value.startswith(prefix):
        raise RegisteredVerificationError("registered_evidence_path_invalid")
    path = (workspace / value.removeprefix(prefix)).resolve()
    try:
        path.relative_to(workspace.resolve())
    except ValueError as exc:
        raise RegisteredVerificationError("registered_evidence_path_invalid") from exc
    if not path.is_file() or path.is_symlink():
        raise RegisteredVerificationError("registered_evidence_path_invalid")
    return path


def _default_boundary(settings: Settings, workspace: Path) -> RegisteredVerificationBoundary:
    from quant_system.d34.research_cli import _LazyResearchRuntime
    from quant_system.d34.worker import D34WorkerConfig

    platform_root = Path(__file__).resolve().parents[3]
    hqa_root = Path(
        os.environ.get("QS_D34_HQA_ROOT", "/Users/sunyibo/programs/Hermes-quant-agent")
    )
    cache = workspace / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    config = D34WorkerConfig(
        workspace_root=workspace,
        data_root=Path(settings.data.data_dir),
        platform_root=platform_root,
        hqa_root=hqa_root,
        cache_root=cache,
    )
    return _LazyResearchRuntime(
        settings=settings,
        config=config,
        image_ref=os.environ.get(
            "D34_IMAGE_REF", "hqa-d34-rdagent-qlib:0.1.0"
        ),
    )


def load_registered_factor_evidence(root: Path) -> RegisteredFactorEvidence:
    try:
        manifest = _read_json(root / "manifest.json")
        manifest_digest = str(manifest.pop("manifest_digest"))
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise RegisteredVerificationError("registered_evidence_invalid") from exc
    if (
        manifest.get("contract") != REGISTERED_EVIDENCE_CONTRACT
        or manifest_digest != digest_document(manifest)
        or manifest.get("job_id") != root.name
    ):
        raise RegisteredVerificationError("registered_evidence_invalid")
    for path_field, digest_field in (
        ("source_path", "source_file_digest"),
        ("snapshot_path", "snapshot_file_digest"),
        ("qlib_receipt_path", "qlib_receipt_file_digest"),
        ("qlib_bound_path", "qlib_bound_file_digest"),
        ("platform_receipt_path", "platform_receipt_file_digest"),
        ("platform_bound_path", "platform_bound_file_digest"),
    ):
        path = root / str(manifest.get(path_field) or "")
        if not path.is_file() or path.is_symlink() or _sha(path) != manifest.get(digest_field):
            raise RegisteredVerificationError("registered_evidence_file_invalid")
    return RegisteredFactorEvidence(
        job_id=str(manifest["job_id"]),
        run_id=str(manifest["run_id"]),
        root=root,
        manifest={**manifest, "manifest_digest": manifest_digest},
    )


def generate_registered_factor_evidence(
    settings: Settings,
    *,
    factor_id: str,
    universe: Sequence[str],
    boundary: RegisteredVerificationBoundary | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RegisteredFactorEvidence:
    from quant_system.research.registered_family_evidence import (
        ATTEMPT_INPUT,
        INTENT,
        PRODUCER_IDENTITY,
        commit_registered_trial,
        prepare_registered_trial,
        preserve_registered_failure,
        registered_producer_sources,
    )

    symbols = tuple(str(value).strip().upper() for value in universe)
    if not symbols or len(symbols) > 64 or len(set(symbols)) != len(symbols):
        raise RegisteredVerificationError("registered_factor_universe_invalid")
    registry = build_factor_registry(purpose="paper")
    if factor_id not in registry.factor_ids():
        raise RegisteredVerificationError("registered_factor_not_supported")
    factor = registry.create(factor_id)
    spec = registered_factor_spec(factor)
    source_file = Path(inspect.getsourcefile(type(factor)) or "")
    if not source_file.is_file():
        raise RegisteredVerificationError("registered_factor_source_unavailable")
    source_digest = _sha(source_file)
    factor_identity_digest = digest_document(
        {
            "contract": "hqa.registered_factor_identity/v1",
            "compute_source_digest": spec.compute_source_digest,
            "expression_digest": spec.expression_digest,
            "factor_id": factor_id,
            "source_digest": source_digest,
        }
    )
    market_session = latest_us_market_session(now().astimezone(_MARKET_TZ).date())
    attempt_input = {
            "contract": REGISTERED_EVIDENCE_CONTRACT,
            "factor_id": factor_id,
            "factor_identity_digest": factor_identity_digest,
            "source_digest": source_digest,
            "universe": list(symbols),
            "market_session": market_session.isoformat(),
        }
    identity = digest_document(attempt_input)
    job_id = f"job-registered-{identity[:32]}"
    run_id = f"attempt-registered-{identity[:32]}"
    data_root = Path(settings.data.data_dir)
    workspace = data_root / "_runtime" / "d34"
    jobs_root = workspace / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    final_root = jobs_root / job_id
    if final_root.exists():
        evidence = load_registered_factor_evidence(final_root)
        # Only new producer-owned frozen intents may recover an interrupted
        # ledger append. Loading an older result never retroactively writes it.
        if (final_root / INTENT).is_file():
            try:
                commit_registered_trial(data_root, final_root)
            except ValueError as exc:
                raise RegisteredVerificationError(str(exc)) from exc
        return evidence
    external = boundary or _default_boundary(settings, workspace)
    producer_sources = registered_producer_sources()
    producer_identity = {
        "schema": "registered_producer_identity/v1",
        "source_binding_kind": "disk_files_and_execution_config",
        "loaded_process_attested": False,
        "producer_sources": producer_sources,
        "execution_config": {"initial_cash": 100000.0,
                             "commission_bps": settings.paper_account.commission_bps,
                             "slippage_bps": settings.paper_account.slippage_bps,
                             "min_order_value": 0.0, "whole_share_orders": False,
                             "execution_price": "next_open"},
        "boundary_receipts": [],
        "post_execution_sources_unchanged": False,
    }

    def record_boundary(receipt):
        producer_identity["boundary_receipts"].append({
            "contract": receipt.contract, "job_id": receipt.job_id,
            "image_ref": receipt.image_ref, "image_digest": receipt.image_digest,
            "command": list(receipt.command), "receipt_digest": receipt.receipt_digest,
        })
        _write_json(temporary / PRODUCER_IDENTITY, producer_identity)

    temporary = Path(tempfile.mkdtemp(prefix=f".{job_id}-", dir=jobs_root))
    stage = "snapshot"
    try:
        _write_json(temporary / ATTEMPT_INPUT, attempt_input)
        _write_json(temporary / PRODUCER_IDENTITY, producer_identity)
        snapshot = create_market_data_snapshot(
            provider=external,
            symbols=symbols,
            start=(market_session - timedelta(days=1095)).isoformat(),
            end=market_session.isoformat(),
            output_root=workspace / "snapshots",
            now=now,
        )
        qlib_root = temporary / "qlib-provider"
        stage = "qlib_provider"
        adapter = external.run(
            job_id=job_id,
            command=(
                "qlib-adapt",
                "--snapshot-id",
                snapshot.snapshot_id,
                "--snapshot-digest",
                snapshot.snapshot_digest,
                "--snapshot-parquet",
                _container_path(workspace, snapshot.parquet_path),
                "--output-root",
                _container_path(workspace, qlib_root),
            ),
        )
        record_boundary(adapter)
        bars = pd.read_parquet(snapshot.parquet_path)
        calendar = [
            pd.Timestamp(value).isoformat()
            for value in sorted(pd.to_datetime(bars["timestamp"], utc=True).unique())
        ]
        if not calendar or date.fromisoformat(calendar[-1][:10]) != market_session:
            raise RegisteredVerificationError("registered_snapshot_session_incomplete")
        request = {
            "contract": "hqa.registered_factor_verification_request/v1",
            "job_id": job_id,
            "run_id": run_id,
            "factor_id": factor_id,
            "source_digest": source_digest,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_digest": snapshot.snapshot_digest,
            "provider_uri": adapter.output["provider_uri"],
            "universe": list(symbols),
            "calendar": calendar,
            "qlib_expression": spec.qlib_expression,
            "top_k": 1,
            "initial_cash": 100_000.0,
        }
        request_path = temporary / "request.json"
        _write_json(request_path, request)
        qlib_output = temporary / "qlib-result"
        stage = "qlib_evaluation"
        qlib_result = external.run(
            job_id=job_id,
            command=(
                "registered-verify",
                "--request",
                _container_path(workspace, request_path),
                "--output-root",
                _container_path(workspace, qlib_output),
            ),
        )
        record_boundary(qlib_result)
        qlib_raw = _host_path(workspace, qlib_result.output["qlib_receipt_path"])
        target_weights = _host_path(workspace, qlib_result.output["target_weights_path"])
        qlib_receipt = _engine_receipt(
            qlib_raw,
            engine="qlib",
            job_id=job_id,
            run_id=run_id,
            factor_id=factor_id,
            source_digest=source_digest,
            qlib_expression=spec.qlib_expression,
        )
        stage = "platform_evaluation"
        replay = external.replay(
            qlib_receipt=qlib_receipt,
            job_id=job_id,
            run_id=run_id,
            snapshot_id=snapshot.snapshot_id,
            snapshot_digest=snapshot.snapshot_digest,
            snapshot_parquet=snapshot.parquet_path,
            target_weights_parquet=target_weights,
            output_root=temporary / "platform-replay",
            initial_cash=100_000,
            commission_bps=settings.paper_account.commission_bps,
            slippage_bps=settings.paper_account.slippage_bps,
            min_order_value=0,
            whole_share_orders=False,
        )
        platform_raw = Path(replay.output_dir) / "receipt.json"
        platform_receipt = _engine_receipt(
            platform_raw, engine="platform", job_id=job_id, run_id=run_id
        )
        stage = "dual_engine_comparison"
        comparison = compare_engine_receipts(
            qlib=qlib_receipt,
            platform=platform_receipt,
            policy=ComparisonPolicy.initial(),
        )
        source_copy = temporary / "factor_source.py"
        shutil.copy2(source_file, source_copy)
        snapshot_copy = temporary / "snapshot.parquet"
        shutil.copy2(snapshot.parquet_path, snapshot_copy)

        def bound(engine: str, raw_path: Path, receipt: EngineReceipt, turnover) -> Path:
            raw_relative = raw_path.resolve().relative_to(temporary.resolve())
            path = temporary / f"{engine}_engine_receipt.json"
            body = {
                "contract": "hqa.d34_bound_engine_receipt/v2",
                "job_id": job_id,
                "run_id": run_id,
                "resource_envelope_id": LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
                "engine": engine,
                "raw_receipt_path": raw_relative.as_posix(),
                "raw_receipt_file_digest": _sha(raw_path),
                "engine_receipt": {
                    "engine": receipt.engine,
                    "snapshot_digest": receipt.snapshot_digest,
                    "universe_digest": receipt.universe_digest,
                    "calendar_digest": receipt.calendar_digest,
                    "target_weights_digest": receipt.target_weights_digest,
                    "daily_returns": list(receipt.daily_returns),
                    "return_dates": list(receipt.return_dates),
                    "terminal_nav": receipt.terminal_nav,
                    "terminal_weights": dict(receipt.terminal_weights),
                    "receipt_digest": receipt.receipt_digest,
                },
                "turnover_period": turnover,
            }
            _write_json(path, {**body, "receipt_digest": digest_document(body)})
            return path

        qlib_bound = bound("qlib", qlib_raw, qlib_receipt, None)
        platform_bound = bound(
            "platform", platform_raw, platform_receipt, replay.turnover_period
        )
        manifest = {
            "contract": REGISTERED_EVIDENCE_CONTRACT,
            "job_id": job_id,
            "run_id": run_id,
            "factor_id": factor_id,
            "factor_identity_digest": factor_identity_digest,
            "source_digest": source_digest,
            "compute_source_digest": spec.compute_source_digest,
            "qlib_expression": spec.qlib_expression,
            "qlib_expression_digest": spec.expression_digest,
            "universe": list(symbols),
            "market_session": market_session.isoformat(),
            "source_path": source_copy.relative_to(temporary).as_posix(),
            "source_file_digest": _sha(source_copy),
            "snapshot_path": snapshot_copy.relative_to(temporary).as_posix(),
            "snapshot_file_digest": _sha(snapshot_copy),
            "snapshot_digest": snapshot.snapshot_digest,
            "calendar": calendar,
            "calendar_digest": digest_document(calendar),
            "qlib_receipt_path": qlib_raw.relative_to(temporary).as_posix(),
            "qlib_receipt_file_digest": _sha(qlib_raw),
            "qlib_receipt_digest": qlib_receipt.receipt_digest,
            "qlib_bound_path": qlib_bound.relative_to(temporary).as_posix(),
            "qlib_bound_file_digest": _sha(qlib_bound),
            "platform_receipt_path": platform_raw.relative_to(temporary).as_posix(),
            "platform_receipt_file_digest": _sha(platform_raw),
            "platform_receipt_digest": platform_receipt.receipt_digest,
            "platform_bound_path": platform_bound.relative_to(temporary).as_posix(),
            "platform_bound_file_digest": _sha(platform_bound),
            "comparison_digest": comparison.comparison_digest,
            "comparison": {
                "accepted": comparison.accepted,
                "daily_return_correlation": comparison.daily_return_correlation,
                "terminal_nav_difference_bps": comparison.terminal_nav_difference_bps,
                "max_symbol_weight_difference_bps": (
                    comparison.max_symbol_weight_difference_bps
                ),
            },
            "turnover_period": replay.turnover_period,
            "cost_model": {
                "commission_bps": settings.paper_account.commission_bps,
                "slippage_bps": settings.paper_account.slippage_bps,
            },
        }
        _write_json(
            temporary / "manifest.json",
            {**manifest, "manifest_digest": digest_document(manifest)},
        )
        stage = "family_recording"
        if registered_producer_sources() != producer_sources:
            raise RegisteredVerificationError("registered_producer_sources_changed")
        producer_identity["post_execution_sources_unchanged"] = True
        _write_json(temporary / PRODUCER_IDENTITY, producer_identity)
        prepare_registered_trial(data_root, temporary, final_root)
        temporary.rename(final_root)
        commit_registered_trial(data_root, final_root)
        if not comparison.accepted:
            raise RegisteredVerificationError("registered_factor_dual_engine_rejected")
        return load_registered_factor_evidence(final_root)
    except Exception as exc:
        if temporary.exists():
            preserve_registered_failure(data_root, temporary, job_id=job_id, run_id=run_id,
                                        universe=symbols, stage=stage,
                                        reason=str(getattr(exc, "code", None) or exc))
        raise


__all__ = [
    "REGISTERED_EVIDENCE_CONTRACT",
    "RegisteredFactorEvidence",
    "RegisteredVerificationBoundary",
    "RegisteredVerificationError",
    "generate_registered_factor_evidence",
    "load_registered_factor_evidence",
    "registered_factor_spec",
]
