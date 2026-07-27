"""Repository-real §9.1 blocked/replay proof.

The proof calls the production ``run_paper`` route with its repository-defined
replay kill switch enabled.  The route must return its stable HTTP 409 before
allocating a run identity or reaching any provider, broker, pipeline, or
persistence boundary.  A private immutable journal owns the fixed operation
identity so same-byte replay only reconciles the original receipt.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
import stat
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from types import FrameType
from typing import Any

from fastapi import HTTPException

from quant_system.api.routes import paper as paper_routes
from quant_system.api.schemas.paper import PaperRunRequest
from quant_system.config.settings import Settings
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.execution.account import PaperAccount
from quant_system.execution.paper_broker import PaperBroker
from quant_system.ops.common import (
    ReleaseOperationError,
    canonical_json_bytes,
    ensure_private_directory,
    git_identity,
    read_private_regular,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_immutable,
)

SCHEMA_VERSION = "agent-v0.2.2-repository-zero-effect-proof.v2"
AUTHORITY_KIND = "immutable_same_identity_zero_effect_journal"
OPERATION_ID = "agent-v02-zero-effect-paper-replay-001"
DISPOSABLE_ACCOUNT = "agent-v02-zero-effect-disposable-account"
EXPECTED_BLOCK_CODE = "replay_kill_switch_enabled"
EXPECTED_RELEASE_CONTRACT = "agent-v0.2-release-cli/v1"
FIXED_TIME = "2026-01-01T00:00:00+00:00"


def _paper_run_request() -> PaperRunRequest:
    return PaperRunRequest(
        symbols=["SPY", "QQQ"],
        start="2026-01-02",
        end="2026-01-03",
        provider="sample",
        enable_kill_switch=True,
        initial_cash=100_000.0,
        lookback=20,
        top_n=2,
        max_fill_ratio_per_tick=1.0,
    )


def default_request_bytes() -> bytes:
    """Return the one canonical request allowed in this proof namespace."""

    return canonical_json_bytes(
        {
            "operation_id": OPERATION_ID,
            "operation_kind": "paper.replay.blocked_zero_effect",
            "paper_run_request": _paper_run_request().model_dump(mode="json"),
        }
    )


def _runtime_digest(root: Path, module_paths: tuple[Path, ...]) -> str:
    identity = git_identity(root, require_clean=True)
    modules = [
        {
            "path": str(module_path.resolve()),
            "sha256": sha256_file(module_path),
        }
        for module_path in module_paths
    ]
    return sha256_bytes(
        canonical_json_bytes(
            {
                "commit": identity.commit,
                "modules": modules,
                "tree": identity.tree,
            }
        )
    )


def _settings_safety_observation(settings: Settings) -> dict[str, object]:
    facts = {
        "global_switch_authority": "Settings.safety.kill_switch",
        "global_kill_switch": settings.safety.kill_switch,
        "live_trading_authority": "Settings.safety.live_trading_enabled",
        "live_trading_enabled": settings.safety.live_trading_enabled,
    }
    if facts["global_kill_switch"] is not True:
        raise ReleaseOperationError("observed Settings global kill switch is not closed")
    if facts["live_trading_enabled"] is not False:
        raise ReleaseOperationError("observed Settings live trading flag is not closed")
    return facts


def _release_status_cli(platform_root: Path) -> Path:
    cli = platform_root.resolve() / ".venv" / "bin" / "quant-system"
    if cli.is_symlink() or not cli.is_file() or not os.access(cli, os.X_OK):
        raise ReleaseOperationError("installed quant-system release-status CLI is unavailable")
    return cli


def _validate_release_status(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        raise ReleaseOperationError("release status artifact is not a JSON object")
    if document.get("contract") != EXPECTED_RELEASE_CONTRACT:
        raise ReleaseOperationError("release status artifact contract is invalid")
    decision = document.get("decision")
    if not isinstance(decision, dict):
        raise ReleaseOperationError("release status artifact has no decision")
    required_closed = (
        "release_authorized",
        "public_write_authorized",
        "chat_write_ready",
    )
    for field in required_closed:
        if decision.get(field) is not False:
            raise ReleaseOperationError(f"release status is not closed: {field}")
    if decision.get("ready") is not False:
        raise ReleaseOperationError("release status ready flag is not closed")
    return {
        "release_authorized": decision["release_authorized"],
        "public_write_authorized": decision["public_write_authorized"],
        "chat_write_ready": decision["chat_write_ready"],
        "ready": decision["ready"],
    }


def _fresh_release_status_observation(
    *,
    platform_root: Path,
    state_dir: Path,
) -> dict[str, object]:
    """Run the provider-free owner CLI and persist its exact JSON output."""

    cli = _release_status_cli(platform_root)
    argv = [str(cli), "hermes", "release", "status"]
    completed = subprocess.run(
        argv,
        cwd=platform_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ReleaseOperationError("provider-free release status command failed")
    if completed.stderr:
        raise ReleaseOperationError("provider-free release status wrote stderr")
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("release status artifact is not valid JSON") from exc
    facts = _validate_release_status(document)
    artifact_dir = ensure_private_directory(state_dir / "release-status")
    artifact_path = artifact_dir / f"status-{uuid.uuid4().hex}.json"
    write_immutable(artifact_path, completed.stdout)
    mode = stat.S_IMODE(artifact_path.stat().st_mode)
    if mode != 0o600:
        raise ReleaseOperationError("release status artifact is not owner-only")
    return {
        "facts": facts,
        "artifact": {
            "path": str(artifact_path),
            "mode": "0600",
            "sha256": sha256_file(artifact_path),
            "bytes": artifact_path.stat().st_size,
        },
        "command": {
            "argv": argv,
            "exit_code": completed.returncode,
            "cli_sha256": sha256_file(cli),
            "stdout_sha256": sha256_bytes(completed.stdout),
            "stdout_bytes": len(completed.stdout),
            "stderr_sha256": sha256_bytes(completed.stderr),
            "stderr_bytes": len(completed.stderr),
            "provider_free_surface": "quant-system hermes release status",
        },
    }


def _deterministic_account() -> PaperAccount:
    return PaperAccount(
        account_id=DISPOSABLE_ACCOUNT,
        initial_cash=100_000.0,
        cash=100_000.0,
        sleeve_cash={"manual": 100_000.0},
        kill_switch=True,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


def _load_or_create_account(runtime_root: Path) -> tuple[Path, PaperAccount]:
    account_path = runtime_root / "paper-account.json"
    expected = canonical_json_bytes(_deterministic_account().model_dump(mode="json"))
    if account_path.exists():
        if read_private_regular(account_path) != expected:
            raise ReleaseOperationError("disposable PaperAccount bytes changed")
    else:
        write_immutable(account_path, expected)
    try:
        account = PaperAccount.model_validate_json(read_private_regular(account_path))
    except Exception as exc:
        raise ReleaseOperationError("disposable PaperAccount is invalid") from exc
    return account_path, account


def _account_observation(account: PaperAccount) -> dict[str, object]:
    model = account.model_dump(mode="json")
    ledger = [entry.model_dump(mode="json") for entry in account.ledger]
    positions = {
        symbol: position.model_dump(mode="json")
        for symbol, position in sorted(account.positions.items())
    }
    return {
        "model_sha256": sha256_bytes(canonical_json_bytes(model)),
        "ledger_sha256": sha256_bytes(canonical_json_bytes(ledger)),
        "positions_sha256": sha256_bytes(canonical_json_bytes(positions)),
        "cash": account.cash,
        "pending_order_count": len(account.pending_orders),
        "fill_ledger_count": sum(
            entry.kind in {"fill", "rebalance_fill", "sleeve_execution_fill"}
            for entry in account.ledger
        ),
        "position_count": len(account.positions),
        "paper_account_local_switch_authority": "PaperAccount.kill_switch",
        "paper_account_local_kill_switch": account.kill_switch,
    }


def _tree_observation(root: Path) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        info = path.lstat()
        relative = path.relative_to(root).as_posix()
        if stat.S_ISLNK(info.st_mode):
            raise ReleaseOperationError(f"symlink in disposable runtime tree: {relative}")
        if stat.S_ISDIR(info.st_mode):
            entries.append(
                {
                    "path": relative,
                    "type": "directory",
                    "mode": f"{stat.S_IMODE(info.st_mode):04o}",
                }
            )
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ReleaseOperationError(
                f"non-regular entry in disposable runtime tree: {relative}"
            )
        entries.append(
            {
                "path": relative,
                "type": "file",
                "mode": f"{stat.S_IMODE(info.st_mode):04o}",
                "bytes": info.st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "root": str(root),
        "entries": entries,
        "sha256": sha256_bytes(canonical_json_bytes(entries)),
    }


def _route_dependency_surface() -> dict[str, object]:
    parameters = tuple(inspect.signature(paper_routes.run_paper).parameters)
    expected = ("request", "api_runs_dir", "settings")
    if parameters != expected:
        raise ReleaseOperationError("run_paper route dependency surface changed")
    route_names = {
        str(name).lower()
        for name in (
            *parameters,
            *paper_routes.run_paper.__code__.co_names,
        )
    }

    def matching_count(*needles: str) -> int:
        return sum(any(needle in name for needle in needles) for name in route_names)

    return {
        "parameters": list(parameters),
        "requested_provider": _paper_run_request().provider,
        "simulation_only": _paper_run_request().provider == "sample",
        "futu_trade_context_binding_count": matching_count("futu", "trade_context"),
        "live_broker_adapter_binding_count": matching_count("live_broker"),
        "account_unlock_binding_count": matching_count("unlock"),
        "fallback_dispatch_binding_count": matching_count("fallback", "dispatch"),
    }


def _execute_repository_block(
    *,
    request: PaperRunRequest,
    settings: Settings,
    api_runs_dir: Path,
    account_before: PaperAccount,
    tree_before: dict[str, object],
) -> dict[str, object]:
    """Call the real route with passive spies and two downstream guard rails."""

    call_targets = {
        paper_routes.run_paper.__code__: "route_invocations",
        paper_routes.make_run_id.__code__: "run_id_allocations",
        build_ohlcv_provider.__code__: "provider_builds",
        SampleOHLCVProvider.fetch_ohlcv.__code__: "sample_provider_fetches",
        FutuMarketDataProvider.__init__.__code__: "futu_provider_constructions",
        FutuMarketDataProvider._create_context.__code__: "futu_context_creations",
        PaperBroker.__init__.__code__: "paper_broker_constructions",
        PaperBroker.submit_order.__code__: "paper_broker_submissions",
        PaperBroker.process_market_data.__code__: "paper_broker_market_data_calls",
        PaperAccount.apply_fill.__code__: "paper_account_fill_applications",
    }
    observed_calls = {name: 0 for name in call_targets.values()}
    observed_calls["run_paper_trading_calls"] = 0
    observed_calls["persist_run_calls"] = 0
    observed_calls["account_unlock_calls"] = 0
    observed_calls["fallback_dispatch_calls"] = 0
    observed_calls["live_broker_adapter_calls"] = 0
    original_run_paper_trading = paper_routes.run_paper_trading
    original_persist_run = paper_routes.persist_run
    previous_profile = sys.getprofile()

    def profile(frame: FrameType, event: str, argument: object) -> None:
        if event == "call":
            name = call_targets.get(frame.f_code)
            if name is not None:
                observed_calls[name] += 1
            module_name = str(frame.f_globals.get("__name__", ""))
            qualified_name = frame.f_code.co_qualname.lower()
            if module_name.startswith("quant_system."):
                if "unlock" in qualified_name:
                    observed_calls["account_unlock_calls"] += 1
                if "fallback" in qualified_name or "dispatch" in qualified_name:
                    observed_calls["fallback_dispatch_calls"] += 1
                if "livebroker" in qualified_name or "live_broker" in qualified_name:
                    observed_calls["live_broker_adapter_calls"] += 1
        if previous_profile is not None:
            previous_profile(frame, event, argument)

    def run_paper_trading_tripwire(*_args: object, **_kwargs: object) -> None:
        observed_calls["run_paper_trading_calls"] += 1
        raise ReleaseOperationError("blocked route reached run_paper_trading")

    def persist_run_tripwire(*_args: object, **_kwargs: object) -> None:
        observed_calls["persist_run_calls"] += 1
        raise ReleaseOperationError("blocked route reached persist_run")

    paper_routes.run_paper_trading = run_paper_trading_tripwire
    paper_routes.persist_run = persist_run_tripwire
    try:
        sys.setprofile(profile)
        try:
            paper_routes.run_paper(request, api_runs_dir, settings)
        except HTTPException as exc:
            detail = exc.detail
            if (
                exc.status_code != 409
                or not isinstance(detail, dict)
                or detail.get("code") != EXPECTED_BLOCK_CODE
            ):
                raise ReleaseOperationError(
                    "run_paper returned the wrong repository-defined block"
                ) from exc
            blocked = {
                "status_code": exc.status_code,
                "detail": detail,
                "exception_class": (
                    f"{exc.__class__.__module__}.{exc.__class__.__qualname__}"
                ),
            }
        else:
            raise ReleaseOperationError("paper replay was not blocked")
    finally:
        sys.setprofile(previous_profile)
        paper_routes.run_paper_trading = original_run_paper_trading
        paper_routes.persist_run = original_persist_run

    globals_restored = (
        paper_routes.run_paper_trading is original_run_paper_trading
        and paper_routes.persist_run is original_persist_run
    )
    if not globals_restored:
        raise ReleaseOperationError("run_paper downstream globals were not restored")

    _, account_after = _load_or_create_account(api_runs_dir.parent)
    before = _account_observation(account_before)
    after = _account_observation(account_after)
    tree_after = _tree_observation(api_runs_dir.parent)
    dependency_surface = _route_dependency_surface()
    position_changes = int(before["positions_sha256"] != after["positions_sha256"])
    effect_counters = {
        "orders": abs(
            int(after["pending_order_count"]) - int(before["pending_order_count"])
        ),
        "fills": abs(int(after["fill_ledger_count"]) - int(before["fill_ledger_count"])),
        "cash_changes": int(before["cash"] != after["cash"]),
        "position_changes": position_changes,
        "broker_calls": (
            observed_calls["paper_broker_constructions"]
            + observed_calls["paper_broker_submissions"]
            + observed_calls["paper_broker_market_data_calls"]
        ),
        "trade_context_creations": observed_calls["futu_context_creations"],
        "account_unlocks": observed_calls["account_unlock_calls"],
        "external_dispatches": (
            observed_calls["provider_builds"]
            + observed_calls["sample_provider_fetches"]
            + observed_calls["futu_provider_constructions"]
            + observed_calls["run_paper_trading_calls"]
            + observed_calls["persist_run_calls"]
            + observed_calls["fallback_dispatch_calls"]
            + observed_calls["live_broker_adapter_calls"]
        ),
    }
    boundary_counters = {
        "run_id_allocations": observed_calls["run_id_allocations"],
        "provider_calls": (
            observed_calls["provider_builds"]
            + observed_calls["sample_provider_fetches"]
            + observed_calls["futu_provider_constructions"]
        ),
        "run_paper_trading_calls": observed_calls["run_paper_trading_calls"],
        "persist_run_calls": observed_calls["persist_run_calls"],
    }
    dependency_binding_counts = (
        int(dependency_surface["futu_trade_context_binding_count"]),
        int(dependency_surface["live_broker_adapter_binding_count"]),
        int(dependency_surface["account_unlock_binding_count"]),
        int(dependency_surface["fallback_dispatch_binding_count"]),
    )
    if observed_calls["route_invocations"] != 1:
        raise ReleaseOperationError("run_paper route invocation count is not exactly one")
    if (
        any(effect_counters.values())
        or any(boundary_counters.values())
        or any(dependency_binding_counts)
        or dependency_surface["simulation_only"] is not True
        or observed_calls["paper_account_fill_applications"] != 0
        or before != after
        or tree_before != tree_after
    ):
        raise ReleaseOperationError("blocked paper replay produced or reached an effect")
    return {
        "repository_blocked_result": blocked,
        "route_invocations": observed_calls["route_invocations"],
        "passive_call_observations": observed_calls,
        "boundary_counters": boundary_counters,
        "effect_counters": effect_counters,
        "account_before": before,
        "account_after": after,
        "tree_before": tree_before,
        "tree_after": tree_after,
        "downstream_globals_restored": globals_restored,
        "dependency_surface": dependency_surface,
    }


def _authoritative_receipt(
    *,
    request_digest: str,
    platform_identity: dict[str, Any],
    hqa_identity: dict[str, Any],
    platform_runtime_digest: str,
    hqa_runtime_digest: str,
    settings_preflight: dict[str, object],
    settings_postflight: dict[str, object],
    release_preflight: dict[str, object],
    release_postflight: dict[str, object],
    execution: dict[str, object],
) -> dict[str, object]:
    route_module = Path(paper_routes.__file__).resolve()
    body: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "authority_kind": AUTHORITY_KIND,
        "operation_id": OPERATION_ID,
        "request_sha256": request_digest,
        "adapter": "quant_system.api.routes.paper.run_paper",
        "simulation_provider": execution["dependency_surface"]["requested_provider"],
        "disposable_account_ref": DISPOSABLE_ACCOUNT,
        "platform_repository": platform_identity,
        "hqa_repository": hqa_identity,
        "platform_runtime_digest": platform_runtime_digest,
        "hqa_runtime_digest": hqa_runtime_digest,
        "safety_preflight": {
            **settings_preflight,
            "paper_account_local_switch_authority": "PaperAccount.kill_switch",
            "paper_account_local_kill_switch": execution["account_before"][
                "paper_account_local_kill_switch"
            ],
            "replay_switch_authority": "PaperRunRequest.enable_kill_switch",
            "replay_enable_kill_switch": _paper_run_request().enable_kill_switch,
            **release_preflight["facts"],
        },
        "safety_postflight": {
            **settings_postflight,
            "paper_account_local_switch_authority": "PaperAccount.kill_switch",
            "paper_account_local_kill_switch": execution["account_after"][
                "paper_account_local_kill_switch"
            ],
            "replay_switch_authority": "PaperRunRequest.enable_kill_switch",
            "replay_enable_kill_switch": _paper_run_request().enable_kill_switch,
            **release_postflight["facts"],
        },
        "release_status_artifacts": {
            "preflight": release_preflight,
            "postflight": release_postflight,
        },
        "expected_outcome": {
            "status_code": 409,
            "code": EXPECTED_BLOCK_CODE,
            "stage": "before_run_id_provider_broker_pipeline_persist",
        },
        "outcome": "blocked_before_effect",
        "repository_blocking_primitive": {
            "module": "quant_system.api.routes.paper",
            "operation": "run_paper",
            "module_path": str(route_module),
            "module_sha256": sha256_file(route_module),
        },
        "execution_observation": execution,
        "effect_counters": execution["effect_counters"],
        "account_before_sha256": execution["account_before"]["model_sha256"],
        "account_after_sha256": execution["account_after"]["model_sha256"],
        "ledger_before_sha256": execution["account_before"]["ledger_sha256"],
        "ledger_after_sha256": execution["account_after"]["ledger_sha256"],
        "tree_before_sha256": execution["tree_before"]["sha256"],
        "tree_after_sha256": execution["tree_after"]["sha256"],
        "authoritative_command_count": execution["route_invocations"],
    }
    body["authoritative_receipt_sha256"] = sha256_bytes(canonical_json_bytes(body))
    return body


def _verify_receipt_digest(receipt: dict[str, object]) -> None:
    claimed = receipt.get("authoritative_receipt_sha256")
    body = dict(receipt)
    body.pop("authoritative_receipt_sha256", None)
    if claimed != sha256_bytes(canonical_json_bytes(body)):
        raise ReleaseOperationError("authoritative receipt digest mismatch")


def _replay_receipt_observation(
    receipt_path: Path,
) -> tuple[dict[str, object], int]:
    """Read the immutable receipt while passively counting route invocations."""

    route_invocations = 0
    previous_profile = sys.getprofile()

    def profile(frame: FrameType, event: str, argument: object) -> None:
        nonlocal route_invocations
        if event == "call" and frame.f_code is paper_routes.run_paper.__code__:
            route_invocations += 1
        if previous_profile is not None:
            previous_profile(frame, event, argument)

    sys.setprofile(profile)
    try:
        try:
            receipt = json.loads(read_private_regular(receipt_path))
        except json.JSONDecodeError as exc:
            raise ReleaseOperationError("immutable receipt is not valid JSON") from exc
    finally:
        sys.setprofile(previous_profile)
    if not isinstance(receipt, dict):
        raise ReleaseOperationError("immutable receipt is not a JSON object")
    return receipt, route_invocations


def _verify_release_artifacts(receipt: dict[str, object]) -> None:
    observations = receipt.get("release_status_artifacts")
    if not isinstance(observations, dict):
        raise ReleaseOperationError("receipt lacks release status artifacts")
    for phase in ("preflight", "postflight"):
        observation = observations.get(phase)
        if not isinstance(observation, dict):
            raise ReleaseOperationError("receipt release status observation is invalid")
        artifact = observation.get("artifact")
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            raise ReleaseOperationError("receipt release status artifact is invalid")
        path = Path(artifact["path"])
        payload = read_private_regular(path)
        if sha256_bytes(payload) != artifact.get("sha256"):
            raise ReleaseOperationError("receipt release status artifact digest mismatch")
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ReleaseOperationError("receipt release status artifact is invalid") from exc
        if _validate_release_status(document) != observation.get("facts"):
            raise ReleaseOperationError("receipt release status facts disagree")


def _validate_existing_receipt(
    *,
    receipt: dict[str, object],
    request_digest: str,
    platform_identity: dict[str, object],
    hqa_identity: dict[str, object],
    platform_runtime_digest: str,
    hqa_runtime_digest: str,
    current_settings: dict[str, object],
    current_release_facts: dict[str, object],
    runtime_root: Path,
) -> None:
    _verify_receipt_digest(receipt)
    _verify_release_artifacts(receipt)
    if receipt.get("operation_id") != OPERATION_ID:
        raise ReleaseOperationError("immutable receipt operation identity mismatch")
    if receipt.get("request_sha256") != request_digest:
        raise ReleaseOperationError("immutable receipt request digest mismatch")
    if receipt.get("platform_repository") != platform_identity:
        raise ReleaseOperationError("immutable receipt platform identity mismatch")
    if receipt.get("hqa_repository") != hqa_identity:
        raise ReleaseOperationError("immutable receipt HQA identity mismatch")
    if receipt.get("platform_runtime_digest") != platform_runtime_digest:
        raise ReleaseOperationError("immutable receipt platform runtime mismatch")
    if receipt.get("hqa_runtime_digest") != hqa_runtime_digest:
        raise ReleaseOperationError("immutable receipt HQA runtime mismatch")
    safety_preflight = receipt.get("safety_preflight")
    safety_postflight = receipt.get("safety_postflight")
    if not isinstance(safety_preflight, dict) or not isinstance(safety_postflight, dict):
        raise ReleaseOperationError("immutable receipt safety facts are invalid")
    for field, value in current_settings.items():
        if safety_preflight.get(field) != value or safety_postflight.get(field) != value:
            raise ReleaseOperationError("immutable receipt Settings safety facts drifted")
    for field, value in current_release_facts.items():
        if safety_preflight.get(field) != value or safety_postflight.get(field) != value:
            raise ReleaseOperationError("immutable receipt release facts drifted")
    _, account = _load_or_create_account(runtime_root)
    account_observation = _account_observation(account)
    tree_observation = _tree_observation(runtime_root)
    execution = receipt.get("execution_observation")
    if not isinstance(execution, dict):
        raise ReleaseOperationError("immutable receipt execution observation is invalid")
    if execution.get("account_after") != account_observation:
        raise ReleaseOperationError("disposable PaperAccount changed after receipt")
    if execution.get("tree_after") != tree_observation:
        raise ReleaseOperationError("disposable runtime tree changed after receipt")


def run_zero_effect_proof(
    *,
    platform_root: Path,
    hqa_root: Path,
    state_dir: Path,
    request_bytes: bytes | None = None,
) -> dict[str, object]:
    """Submit once and reconcile same-byte replay without a second route call."""

    platform_root = platform_root.resolve()
    hqa_root = hqa_root.resolve()
    state_dir = ensure_private_directory(state_dir)
    journal_dir = ensure_private_directory(state_dir / "journal")
    runtime_root = ensure_private_directory(state_dir / "disposable-runtime")
    api_runs_dir = ensure_private_directory(runtime_root / "runs")
    request_path = journal_dir / "request.json"
    receipt_path = journal_dir / "authoritative-receipt.json"

    raw_request = request_bytes if request_bytes is not None else default_request_bytes()
    if request_path.exists() and read_private_regular(request_path) != raw_request:
        raise ReleaseOperationError("same operation identity has different request bytes")
    if receipt_path.exists() and not request_path.exists():
        raise ReleaseOperationError("partial immutable zero-effect journal")
    try:
        decoded = json.loads(raw_request)
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("request bytes are not valid JSON") from exc
    if not isinstance(decoded, dict) or decoded.get("operation_id") != OPERATION_ID:
        raise ReleaseOperationError("request operation_id is not the fixed proof identity")
    if canonical_json_bytes(decoded) != raw_request:
        raise ReleaseOperationError("request bytes are not canonical and exact")
    if raw_request != default_request_bytes():
        raise ReleaseOperationError("different request bytes from the fixed proof")
    try:
        route_request = PaperRunRequest.model_validate(decoded["paper_run_request"])
    except Exception as exc:
        raise ReleaseOperationError("paper replay request payload is invalid") from exc
    if route_request != _paper_run_request():
        raise ReleaseOperationError("paper replay request model is not exact")

    platform = git_identity(platform_root, require_clean=True)
    hqa = git_identity(hqa_root, require_clean=True)
    hqa_module = hqa_root / "hqa" / "__init__.py"
    if hqa_module.is_symlink() or not hqa_module.is_file():
        raise ReleaseOperationError("HQA runtime module is absent")
    platform_runtime_digest = _runtime_digest(
        platform_root,
        (
            Path(__file__).resolve(),
            Path(paper_routes.__file__).resolve(),
            _release_status_cli(platform_root),
        ),
    )
    hqa_runtime_digest = _runtime_digest(hqa_root, (hqa_module,))
    _, account = _load_or_create_account(runtime_root)
    account_before = _account_observation(account)
    if account_before["paper_account_local_kill_switch"] is not True:
        raise ReleaseOperationError("disposable PaperAccount kill switch is not closed")
    tree_before = _tree_observation(runtime_root)

    if request_path.exists() and not receipt_path.exists():
        raise ReleaseOperationError("partial immutable zero-effect journal")
    first_was_replay = receipt_path.exists()

    active_settings = Settings()
    settings_preflight = _settings_safety_observation(active_settings)
    release_preflight = _fresh_release_status_observation(
        platform_root=platform_root,
        state_dir=state_dir,
    )
    if first_was_replay:
        receipt, route_invocations_this_call = _replay_receipt_observation(receipt_path)
    else:
        execution = _execute_repository_block(
            request=route_request,
            settings=active_settings,
            api_runs_dir=api_runs_dir,
            account_before=account,
            tree_before=tree_before,
        )
        route_invocations_this_call = int(execution["route_invocations"])
        settings_postflight = _settings_safety_observation(Settings())
        release_postflight = _fresh_release_status_observation(
            platform_root=platform_root,
            state_dir=state_dir,
        )
        receipt = _authoritative_receipt(
            request_digest=sha256_bytes(raw_request),
            platform_identity=asdict(platform),
            hqa_identity=asdict(hqa),
            platform_runtime_digest=platform_runtime_digest,
            hqa_runtime_digest=hqa_runtime_digest,
            settings_preflight=settings_preflight,
            settings_postflight=settings_postflight,
            release_preflight=release_preflight,
            release_postflight=release_postflight,
            execution=execution,
        )
        write_immutable(request_path, raw_request)
        try:
            write_immutable(receipt_path, canonical_json_bytes(receipt))
        except BaseException:
            request_path.unlink(missing_ok=True)
            raise
    if first_was_replay:
        settings_postflight = _settings_safety_observation(Settings())
        release_postflight = _fresh_release_status_observation(
            platform_root=platform_root,
            state_dir=state_dir,
        )
    _validate_existing_receipt(
        receipt=receipt,
        request_digest=sha256_bytes(raw_request),
        platform_identity=asdict(platform),
        hqa_identity=asdict(hqa),
        platform_runtime_digest=platform_runtime_digest,
        hqa_runtime_digest=hqa_runtime_digest,
        current_settings=settings_postflight,
        current_release_facts=release_postflight["facts"],
        runtime_root=runtime_root,
    )
    replay, replay_route_invocations = _replay_receipt_observation(receipt_path)
    if replay != receipt:
        raise ReleaseOperationError("same-id replay did not return the same receipt")

    effect_counters = receipt["effect_counters"]
    assert isinstance(effect_counters, dict)
    repository_block = receipt["execution_observation"]["repository_blocked_result"]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "completed_at": utc_now(),
        "operation_id": OPERATION_ID,
        "request_sha256": sha256_bytes(raw_request),
        "request_base64": base64.b64encode(raw_request).decode("ascii"),
        "first_submission": {
            "idempotent_replay": first_was_replay,
            "route_invocations_this_call": route_invocations_this_call,
            "receipt": receipt,
        },
        "exact_same_bytes_replay": {
            "idempotent_replay": (
                replay == receipt and replay_route_invocations == 0
            ),
            "route_invocations": replay_route_invocations,
            "receipt": replay,
        },
        "same_authoritative_receipt": receipt == replay,
        "all_effect_counters_zero": all(value == 0 for value in effect_counters.values()),
        "repository_block_executed": (
            repository_block["status_code"] == 409
            and repository_block["detail"]["code"] == EXPECTED_BLOCK_CODE
        ),
        "safety_unchanged": (
            receipt["safety_preflight"] == receipt["safety_postflight"]
            and settings_preflight == settings_postflight
            and release_preflight["facts"] == release_postflight["facts"]
        ),
        "fresh_release_status_observations_this_call": {
            "preflight": release_preflight,
            "postflight": release_postflight,
        },
        "state_paths": {
            "request": str(request_path),
            "authoritative_receipt": str(receipt_path),
            "disposable_runtime": str(runtime_root),
        },
    }
