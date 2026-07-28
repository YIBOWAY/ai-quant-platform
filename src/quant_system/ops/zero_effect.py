"""Repository-real §9.1 blocked/replay proof.

The proof calls the production ``run_paper`` route with its repository-defined
replay kill switch enabled.  The route must return its stable HTTP 409 before
allocating a run identity or reaching any provider, broker, pipeline, or
persistence boundary.  A private immutable journal owns the fixed operation
identity so same-byte replay only reconciles the original receipt.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.util
import errno
import fcntl
import inspect
import json
import math
import os
import select
import signal
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
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

SCHEMA_VERSION = "agent-v0.2.2-repository-zero-effect-proof.v6"
AUTHORITY_KIND = "immutable_same_identity_zero_effect_journal"
CLAIM_SCHEMA_VERSION = "agent-v0.2.2-zero-effect-claim.v3"
SEAL_SCHEMA_VERSION = "agent-v0.2.2-zero-effect-seal.v1"
OPERATION_ID = "agent-v02-zero-effect-paper-replay-001"
DISPOSABLE_ACCOUNT = "agent-v02-zero-effect-disposable-account"
EXPECTED_BLOCK_CODE = "replay_kill_switch_enabled"
EXPECTED_RELEASE_CONTRACT = "agent-v0.2-release-cli/v1"
FIXED_TIME = "2026-01-01T00:00:00+00:00"
GLOBAL_SWITCH_AUTHORITY = "Settings.safety.kill_switch"
PAPER_ACCOUNT_SWITCH_AUTHORITY = "PaperAccount.kill_switch"
REPLAY_REQUEST_SWITCH_AUTHORITY = "PaperRunRequest.enable_kill_switch"
ROUTE_SANDBOX_PROFILE = (
    "(version 1) (allow default) (deny network*) (deny process-exec) (deny process-fork)"
)
ROUTE_CHILD_RESULT_LIMIT = 8 * 1024 * 1024
DEFAULT_ROUTE_CHILD_TIMEOUT_SECONDS = 30.0
MIN_ROUTE_CHILD_TIMEOUT_SECONDS = 0.1
MAX_ROUTE_CHILD_TIMEOUT_SECONDS = 300.0
ROUTE_CHILD_KILL_REAP_GRACE_SECONDS = 2.0
ROUTE_CHILD_WAIT_POLL_SECONDS = 0.01
ROUTE_FORBIDDEN_AUDIT_EVENTS = frozenset(
    {
        "_posixsubprocess.fork_exec",
        "os.exec",
        "os.fork",
        "os.forkpty",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawn",
        "os.system",
        "pty.spawn",
        "socket.__new__",
        "socket.bind",
        "socket.connect",
        "socket.getaddrinfo",
        "socket.gethostbyaddr",
        "socket.gethostbyname",
        "socket.gethostbyname_ex",
        "subprocess.Popen",
    }
)
ROUTE_SAFE_ENVIRONMENT = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "NO_COLOR": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONNOUSERSITE": "1",
    "QS_DATABASE_AUTO_MIGRATE": "false",
    "QS_DATABASE_ENABLED": "false",
    "QS_DEFAULT_DATA_PROVIDER": "sample",
    "QS_DRY_RUN": "true",
    "QS_FUTU_ENABLED": "false",
    "QS_KILL_SWITCH": "true",
    "QS_LIVE_TRADING_ENABLED": "false",
    "QS_OPTIONS_RADAR_ENABLED": "false",
    "QS_PAPER_TRADING": "true",
}


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


def _scoped_switch_observations(
    *,
    global_process_value: object,
    paper_account_value: object,
    replay_request_value: object,
) -> list[dict[str, object]]:
    values = (
        global_process_value,
        paper_account_value,
        replay_request_value,
    )
    if any(type(value) is not bool for value in values):
        raise ReleaseOperationError("switch observation value is not boolean")
    return [
        {
            "switch_scope": "global_process",
            "authority_reference": GLOBAL_SWITCH_AUTHORITY,
            "value": global_process_value,
        },
        {
            "switch_scope": "paper_account",
            "authority_reference": PAPER_ACCOUNT_SWITCH_AUTHORITY,
            "value": paper_account_value,
        },
        {
            "switch_scope": "replay_request",
            "authority_reference": REPLAY_REQUEST_SWITCH_AUTHORITY,
            "value": replay_request_value,
        },
    ]


def state_namespace_identity(state_dir: Path) -> dict[str, str]:
    """Return the canonical state namespace used in the idempotency identity."""

    canonical = Path(os.path.abspath(os.fspath(state_dir)))
    namespace_sha256 = sha256_bytes(str(canonical).encode("utf-8"))
    return {
        "canonical_path": str(canonical),
        "namespace_sha256": namespace_sha256,
    }


def _idempotency_identity(state_namespace: dict[str, str]) -> dict[str, str]:
    canonical_path = state_namespace.get("canonical_path")
    namespace_sha256 = state_namespace.get("namespace_sha256")
    if (
        not isinstance(canonical_path, str)
        or not isinstance(namespace_sha256, str)
        or namespace_sha256 != sha256_bytes(canonical_path.encode("utf-8"))
    ):
        raise ReleaseOperationError("state namespace identity is invalid")
    identity_body = {
        "operation_id": OPERATION_ID,
        "state_namespace_sha256": namespace_sha256,
    }
    return {
        **identity_body,
        "identity_sha256": sha256_bytes(canonical_json_bytes(identity_body)),
    }


def _validate_route_child_timeout_seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ReleaseOperationError("route child timeout must be a finite number")
    timeout = float(value)
    if not MIN_ROUTE_CHILD_TIMEOUT_SECONDS <= timeout <= MAX_ROUTE_CHILD_TIMEOUT_SECONDS:
        raise ReleaseOperationError("route child timeout is outside the bounded operational range")
    return timeout


def default_request_bytes(
    state_namespace: dict[str, str],
    *,
    route_child_timeout_seconds: float = DEFAULT_ROUTE_CHILD_TIMEOUT_SECONDS,
) -> bytes:
    """Return the one canonical request allowed in this proof namespace."""

    idempotency = _idempotency_identity(state_namespace)
    timeout = _validate_route_child_timeout_seconds(route_child_timeout_seconds)
    return canonical_json_bytes(
        {
            "idempotency_identity": idempotency,
            "operation_id": OPERATION_ID,
            "operation_kind": "paper.replay.blocked_zero_effect",
            "paper_run_request": _paper_run_request().model_dump(mode="json"),
            "route_child_deadline": {
                "clock": "time.monotonic",
                "kill_reap_grace_seconds": ROUTE_CHILD_KILL_REAP_GRACE_SECONDS,
                "timeout_seconds": timeout,
            },
            "state_namespace": state_namespace,
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
        "global_switch_authority": GLOBAL_SWITCH_AUTHORITY,
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
    info = cli.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ReleaseOperationError("installed quant-system CLI is not owner-controlled")
    try:
        payload = cli.read_bytes()
        first_line = payload.splitlines()[0].decode("utf-8", "strict")
    except (IndexError, OSError, UnicodeDecodeError) as exc:
        raise ReleaseOperationError("installed quant-system CLI launcher is invalid") from exc
    allowed_launchers = {
        f"#!{platform_root.resolve() / '.venv' / 'bin' / name}" for name in ("python", "python3")
    }
    if first_line not in allowed_launchers:
        raise ReleaseOperationError(
            "installed quant-system CLI does not bind the requested platform root"
        )
    generated_body = (
        b"# -*- coding: utf-8 -*-\n"
        b"import sys\n"
        b"from quant_system.cli import app\n"
        b'if __name__ == "__main__":\n'
        b'    if sys.argv[0].endswith("-script.pyw"):\n'
        b"        sys.argv[0] = sys.argv[0][:-11]\n"
        b'    elif sys.argv[0].endswith(".exe"):\n'
        b"        sys.argv[0] = sys.argv[0][:-4]\n"
        b"    sys.exit(app())\n"
    )
    if payload != first_line.encode("utf-8") + b"\n" + generated_body:
        raise ReleaseOperationError("installed quant-system CLI wrapper bytes are not canonical")
    return cli


def validate_platform_execution_authority(
    platform_root: Path,
) -> dict[str, object]:
    """Bind the imported route, callable, and installed CLI to one checkout."""

    root = platform_root.resolve()
    expected_paths = {
        "zero_effect_module": root / "src" / "quant_system" / "ops" / "zero_effect.py",
        "paper_route_module": root / "src" / "quant_system" / "api" / "routes" / "paper.py",
        "paper_schema_module": root / "src" / "quant_system" / "api" / "schemas" / "paper.py",
        "settings_module": root / "src" / "quant_system" / "config" / "settings.py",
        "account_module": root / "src" / "quant_system" / "execution" / "account.py",
    }
    actual_paths = {
        "zero_effect_module": Path(__file__).resolve(),
        "paper_route_module": Path(paper_routes.__file__).resolve(),
        "paper_schema_module": Path(inspect.getsourcefile(PaperRunRequest) or "").resolve(),
        "settings_module": Path(inspect.getsourcefile(Settings) or "").resolve(),
        "account_module": Path(inspect.getsourcefile(PaperAccount) or "").resolve(),
    }
    for name, expected in expected_paths.items():
        if not expected.is_file() or expected.is_symlink():
            raise ReleaseOperationError(f"expected Platform execution module is absent: {name}")
        if actual_paths[name] != expected:
            raise ReleaseOperationError(
                f"imported Platform execution module is outside requested root: {name}"
            )

    callable_source = inspect.getsourcefile(paper_routes.run_paper)
    if callable_source is None:
        raise ReleaseOperationError("run_paper callable has no source authority")
    callable_path = Path(callable_source).resolve()
    code_path = Path(paper_routes.run_paper.__code__.co_filename).resolve()
    if (
        callable_path != expected_paths["paper_route_module"]
        or code_path != expected_paths["paper_route_module"]
        or paper_routes.run_paper.__module__ != "quant_system.api.routes.paper"
        or paper_routes.run_paper.__qualname__ != "run_paper"
    ):
        raise ReleaseOperationError("run_paper callable is not the requested checkout callable")
    matching_routes = [
        route
        for route in paper_routes.router.routes
        if getattr(route, "path", None) == "/paper/run"
        and getattr(route, "methods", set()) == {"POST"}
    ]
    if (
        len(matching_routes) != 1
        or getattr(matching_routes[0], "endpoint", None) is not paper_routes.run_paper
    ):
        raise ReleaseOperationError("run_paper callable is not the registered POST route")

    cli = _release_status_cli(root)
    module_facts = {
        name: {
            "path": str(path),
            "sha256": sha256_file(path),
        }
        for name, path in sorted(actual_paths.items())
    }
    return {
        "platform_root": str(root),
        "modules": module_facts,
        "callable": {
            "module": paper_routes.run_paper.__module__,
            "qualname": paper_routes.run_paper.__qualname__,
            "path": str(callable_path),
            "first_line": paper_routes.run_paper.__code__.co_firstlineno,
            "bytecode_sha256": sha256_bytes(paper_routes.run_paper.__code__.co_code),
            "registered_post_route": "/paper/run",
        },
        "release_status_cli": {
            "path": str(cli),
            "sha256": sha256_file(cli),
        },
    }


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
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": str(platform_root.resolve() / "src"),
            "PYTHONSAFEPATH": "1",
        }
    )
    environment.pop("PYTHONHOME", None)
    completed = subprocess.run(
        argv,
        cwd=platform_root,
        env=environment,
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
            "module_binding": {
                "pythonpath": environment["PYTHONPATH"],
                "python_no_user_site": True,
                "python_safe_path": True,
            },
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
        "paper_account_local_switch_authority": PAPER_ACCOUNT_SWITCH_AUTHORITY,
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
            raise ReleaseOperationError(f"non-regular entry in disposable runtime tree: {relative}")
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


def _route_environment(
    state_dir: Path,
) -> tuple[dict[str, str], dict[str, object]]:
    """Create the exact credential-free environment inherited by the route child."""

    root = ensure_private_directory(state_dir / "route-environment")
    path_values = {
        "HOME": ensure_private_directory(root / "home"),
        "TMPDIR": ensure_private_directory(root / "tmp"),
        "TMP": ensure_private_directory(root / "tmp"),
        "TEMP": ensure_private_directory(root / "tmp"),
        "XDG_CACHE_HOME": ensure_private_directory(root / "xdg-cache"),
        "PYTHONPYCACHEPREFIX": ensure_private_directory(root / "pycache"),
    }
    environment = {
        **ROUTE_SAFE_ENVIRONMENT,
        **{name: str(path) for name, path in path_values.items()},
        "PATH": "/usr/bin:/bin",
    }
    credential_markers = (
        "API_KEY",
        "AUTH",
        "BROKER",
        "CREDENTIAL",
        "DATABASE_URL",
        "FUTU_HOST",
        "FUTU_PORT",
        "OPENAI",
        "PASSWORD",
        "PROVIDER_URL",
        "PROXY",
        "SECRET",
        "TOKEN",
        "UNLOCK",
    )
    removed_credential_like_names = sorted(
        name
        for name in os.environ
        if any(marker in name.upper() for marker in credential_markers) and name not in environment
    )
    present_credential_like_names = sorted(
        name for name in environment if any(marker in name.upper() for marker in credential_markers)
    )
    if present_credential_like_names:
        raise ReleaseOperationError("route environment retained credential-like names")
    return environment, {
        "environment_variable_names": sorted(environment),
        "environment_sha256": sha256_bytes(canonical_json_bytes(environment)),
        "private_paths": {name: str(path) for name, path in path_values.items()},
        "credential_like_names_removed": removed_credential_like_names,
        "credential_like_names_present": present_credential_like_names,
        "provider_and_trading_credentials_inherited": False,
        "working_directory": str(root),
    }


def _apply_route_os_sandbox() -> dict[str, object]:
    """Irreversibly deny network, exec, and fork in the route child."""

    library_path = ctypes.util.find_library("sandbox")
    if not library_path:
        raise ReleaseOperationError("macOS route sandbox library is unavailable")
    try:
        library = ctypes.CDLL(library_path)
    except OSError as exc:
        raise ReleaseOperationError("macOS route sandbox library could not load") from exc
    library.sandbox_init.argtypes = [
        ctypes.c_char_p,
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_char_p),
    ]
    library.sandbox_init.restype = ctypes.c_int
    library.sandbox_free_error.argtypes = [ctypes.c_char_p]
    error = ctypes.c_char_p()
    result = library.sandbox_init(
        ROUTE_SANDBOX_PROFILE.encode("utf-8"),
        0,
        ctypes.byref(error),
    )
    if result != 0:
        if error.value:
            library.sandbox_free_error(error)
        raise ReleaseOperationError("macOS route sandbox initialization failed")
    return {
        "kind": "macos_sandbox_init",
        "library": library_path,
        "profile_sha256": sha256_bytes(ROUTE_SANDBOX_PROFILE.encode("utf-8")),
        "network": "denied",
        "process_exec": "denied",
        "process_fork": "denied",
    }


def _os_sandbox_self_test() -> dict[str, object]:
    """Prove the installed OS policy rejects socket and process effects."""

    import socket

    network_errno: int | None = None
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        network_errno = probe.connect_ex(("127.0.0.1", 9))
    finally:
        probe.close()
    if network_errno != errno.EPERM:
        raise ReleaseOperationError("OS route sandbox did not deny network")

    process_errno: int | None = None
    try:
        subprocess.run(
            ["/usr/bin/true"],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        process_errno = exc.errno
    if process_errno != errno.EPERM:
        raise ReleaseOperationError("OS route sandbox did not deny child processes")
    return {
        "network_connect_errno": network_errno,
        "network_connect_denied": True,
        "subprocess_errno": process_errno,
        "subprocess_denied": True,
    }


def _install_route_audit_guard() -> dict[str, object]:
    """Install a process-global guard that also applies to child route threads."""

    def audit(event: str, _arguments: tuple[object, ...]) -> None:
        if event in ROUTE_FORBIDDEN_AUDIT_EVENTS:
            raise ReleaseOperationError(f"route audit denied boundary: {event}")

    sys.addaudithook(audit)
    return {
        "kind": "python_audit_hook",
        "forbidden_events": sorted(ROUTE_FORBIDDEN_AUDIT_EVENTS),
        "thread_scope": "process_global_including_route_threads",
    }


def _audit_guard_self_test() -> dict[str, object]:
    """Exercise a C socket from a thread and Python subprocess under the hook."""

    import _socket
    import threading

    thread_errors: list[BaseException] = []

    def create_c_socket() -> None:
        try:
            _socket.socket()
        except BaseException as exc:  # noqa: BLE001 - the guard outcome is the proof
            thread_errors.append(exc)

    thread = threading.Thread(target=create_c_socket, name="zero-effect-audit-probe")
    thread.start()
    thread.join(timeout=5)
    if thread.is_alive():
        raise ReleaseOperationError("route audit thread probe did not terminate")
    if (
        len(thread_errors) != 1
        or not isinstance(thread_errors[0], ReleaseOperationError)
        or "socket.__new__" not in str(thread_errors[0])
    ):
        raise ReleaseOperationError("route audit hook did not deny threaded C socket")

    process_error: BaseException | None = None
    try:
        subprocess.run(
            ["/usr/bin/true"],
            check=False,
            capture_output=True,
        )
    except BaseException as exc:  # noqa: BLE001 - the guard outcome is the proof
        process_error = exc
    if not isinstance(process_error, ReleaseOperationError) or "subprocess.Popen" not in str(
        process_error
    ):
        raise ReleaseOperationError("route audit hook did not deny subprocess")
    return {
        "threaded_c_socket_denied": True,
        "subprocess_denied": True,
    }


def _write_pipe_payload(descriptor: int, payload: bytes) -> None:
    header = len(payload).to_bytes(8, "big")
    for value in (header, payload):
        view = memoryview(value)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ReleaseOperationError("route child pipe write failed")
            view = view[written:]


class _RouteChildDeadlineExceeded(ReleaseOperationError):
    """The exact route child exceeded its monotonic parent deadline."""


def _read_pipe_exact(
    descriptor: int,
    size: int,
    *,
    deadline: float,
    phase: str,
) -> bytes:
    value = bytearray()
    while len(value) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _RouteChildDeadlineExceeded(f"route child timed out before {phase}")
        try:
            readable, _, _ = select.select([descriptor], [], [], remaining)
        except InterruptedError:
            continue
        if not readable:
            raise _RouteChildDeadlineExceeded(f"route child timed out before {phase}")
        block = os.read(descriptor, size - len(value))
        if not block:
            raise ReleaseOperationError("route child exited before durable handoff")
        value.extend(block)
    return bytes(value)


def _acknowledge_route_child(process_id: int, descriptor: int) -> None:
    """Release the child only after its complete route observation was received."""

    del process_id
    if os.write(descriptor, b"1") != 1:
        raise ReleaseOperationError("route child acknowledgement failed")


def _validate_route_child_exit_status(status: int) -> None:
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        if os.WIFSIGNALED(status):
            signal_number = os.WTERMSIG(status)
            raise ReleaseOperationError(
                f"route child terminated by signal before durable handoff: {signal_number}"
            )
        raise ReleaseOperationError("route child failed before durable handoff")


def _wait_route_child(process_id: int, *, deadline: float) -> None:
    while True:
        try:
            waited, status = os.waitpid(process_id, os.WNOHANG)
        except InterruptedError:
            continue
        if waited == process_id:
            _validate_route_child_exit_status(status)
            return
        if waited != 0:
            raise ReleaseOperationError("route child wait returned the wrong process")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _RouteChildDeadlineExceeded("route child timed out after acknowledgement")
        time.sleep(min(ROUTE_CHILD_WAIT_POLL_SECONDS, remaining))


def _terminate_and_reap_route_child(process_id: int) -> None:
    """Kill and reap exactly one child without introducing another unbounded wait."""

    with suppress(ProcessLookupError):
        os.kill(process_id, signal.SIGKILL)
    cleanup_deadline = time.monotonic() + ROUTE_CHILD_KILL_REAP_GRACE_SECONDS
    while True:
        try:
            waited, _status = os.waitpid(process_id, os.WNOHANG)
        except InterruptedError:
            continue
        except ChildProcessError:
            return
        if waited == process_id:
            return
        if waited != 0:
            raise ReleaseOperationError("route child cleanup waited for the wrong process")
        remaining = cleanup_deadline - time.monotonic()
        if remaining <= 0:
            raise ReleaseOperationError("route child could not be reaped after SIGKILL")
        time.sleep(min(ROUTE_CHILD_WAIT_POLL_SECONDS, remaining))


def _route_child_main(
    *,
    write_descriptor: int,
    ack_descriptor: int,
    environment: dict[str, str],
    environment_authority: dict[str, object],
    execution_authority: dict[str, object],
    platform_root: Path,
    request: PaperRunRequest,
    api_runs_dir: Path,
    tree_before: dict[str, object],
) -> None:
    """Execute the real route after irreversible OS and audit confinement."""

    try:
        os.environ.clear()
        os.environ.update(environment)
        os.chdir(environment_authority["working_directory"])
        sys.setprofile(None)
        child_execution_authority = validate_platform_execution_authority(platform_root)
        if child_execution_authority != execution_authority:
            raise ReleaseOperationError("route child execution authority changed")
        sandbox_authority = _apply_route_os_sandbox()
        os_self_test = _os_sandbox_self_test()
        audit_authority = _install_route_audit_guard()
        audit_self_test = _audit_guard_self_test()
        if dict(os.environ) != environment:
            raise ReleaseOperationError("route child environment changed before execution")
        active_settings = Settings()
        safety = _settings_safety_observation(active_settings)
        if (
            active_settings.data.default_data_provider != "sample"
            or active_settings.futu.enabled is not False
            or active_settings.database.enabled is not False
        ):
            raise ReleaseOperationError("route child retained a provider or database path")
        _, account = _load_or_create_account(api_runs_dir.parent)
        execution = _execute_repository_block(
            request=request,
            settings=active_settings,
            api_runs_dir=api_runs_dir,
            account_before=account,
            tree_before=tree_before,
        )
        execution["route_guard"] = {
            "os_sandbox": sandbox_authority,
            "os_self_test": os_self_test,
            "python_audit": audit_authority,
            "audit_self_test": audit_self_test,
            "environment": environment_authority,
            "execution_authority": child_execution_authority,
            "settings": {
                **safety,
                "default_data_provider": active_settings.data.default_data_provider,
                "futu_enabled": active_settings.futu.enabled,
                "database_enabled": active_settings.database.enabled,
            },
        }
        payload = canonical_json_bytes({"status": "passed", "execution": execution})
    except BaseException as exc:  # noqa: BLE001 - child must report and fail closed
        payload = canonical_json_bytes(
            {
                "status": "failed_closed",
                "exception_class": exc.__class__.__name__,
                "error": (
                    str(exc)
                    if isinstance(exc, ReleaseOperationError)
                    else "unexpected_route_child_error"
                ),
            }
        )
    try:
        if len(payload) > ROUTE_CHILD_RESULT_LIMIT:
            raise ReleaseOperationError("route child result exceeds the bounded limit")
        _write_pipe_payload(write_descriptor, payload)
        if os.read(ack_descriptor, 1) != b"1":
            os._exit(75)
        os._exit(0)
    except BaseException:
        os._exit(76)


def _execute_repository_block_in_child(
    *,
    platform_root: Path,
    state_dir: Path,
    request: PaperRunRequest,
    api_runs_dir: Path,
    tree_before: dict[str, object],
    execution_authority: dict[str, object],
    route_child_timeout_seconds: float,
) -> dict[str, object]:
    """Fork one OS-confined route child and require an acknowledged handoff."""

    timeout = _validate_route_child_timeout_seconds(route_child_timeout_seconds)
    environment, environment_authority = _route_environment(state_dir)
    result_read, result_write = os.pipe()
    ack_read, ack_write = os.pipe()
    deadline = time.monotonic() + timeout
    process_id = os.fork()
    if process_id == 0:
        os.close(result_read)
        os.close(ack_write)
        _route_child_main(
            write_descriptor=result_write,
            ack_descriptor=ack_read,
            environment=environment,
            environment_authority=environment_authority,
            execution_authority=execution_authority,
            platform_root=platform_root,
            request=request,
            api_runs_dir=api_runs_dir,
            tree_before=tree_before,
        )
        os._exit(77)

    os.close(result_write)
    os.close(ack_read)
    execution: dict[str, object] | None = None
    caught: BaseException | None = None
    try:
        header = _read_pipe_exact(
            result_read,
            8,
            deadline=deadline,
            phase="result header",
        )
        payload_size = int.from_bytes(header, "big")
        if payload_size <= 0 or payload_size > ROUTE_CHILD_RESULT_LIMIT:
            raise ReleaseOperationError("route child result length is invalid")
        payload = _read_pipe_exact(
            result_read,
            payload_size,
            deadline=deadline,
            phase="result payload",
        )
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ReleaseOperationError("route child result is not valid JSON") from exc
        if not isinstance(document, dict) or document.get("status") != "passed":
            detail = (
                document.get("error")
                if isinstance(document, dict) and isinstance(document.get("error"), str)
                else "route child failed closed"
            )
            raise ReleaseOperationError(detail)
        execution = document.get("execution")
        if not isinstance(execution, dict):
            raise ReleaseOperationError("route child result lacks execution observation")
        _acknowledge_route_child(process_id, ack_write)
    except BaseException as exc:  # noqa: BLE001 - reap the exact child before raising
        caught = exc
    finally:
        os.close(result_read)
        os.close(ack_write)
    if caught is not None:
        try:
            _terminate_and_reap_route_child(process_id)
        except BaseException as cleanup_error:
            raise ReleaseOperationError(
                "route child failed and exact child cleanup was incomplete"
            ) from cleanup_error
        raise caught
    try:
        _wait_route_child(process_id, deadline=deadline)
    except _RouteChildDeadlineExceeded:
        try:
            _terminate_and_reap_route_child(process_id)
        except BaseException as cleanup_error:
            raise ReleaseOperationError(
                "route child deadline expired and exact child cleanup was incomplete"
            ) from cleanup_error
        raise
    if execution is None:
        raise ReleaseOperationError("route child produced no execution observation")
    execution["route_child_transport"] = {
        "clock": "time.monotonic",
        "configured_timeout_seconds": timeout,
        "exact_child_reaped": True,
        "header_payload_and_post_ack_wait_share_deadline": True,
        "kill_reap_grace_seconds": ROUTE_CHILD_KILL_REAP_GRACE_SECONDS,
        "result_limit_bytes": ROUTE_CHILD_RESULT_LIMIT,
    }
    return execution


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
        paper_routes.run_paper_trading.__code__: "run_paper_trading_calls",
        paper_routes.persist_run.__code__: "persist_run_calls",
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
    protected_boundaries = {
        "run_id_allocations",
        "provider_builds",
        "sample_provider_fetches",
        "futu_provider_constructions",
        "futu_context_creations",
        "paper_broker_constructions",
        "paper_broker_submissions",
        "paper_broker_market_data_calls",
        "paper_account_fill_applications",
        "run_paper_trading_calls",
        "persist_run_calls",
    }

    def profile(frame: FrameType, event: str, argument: object) -> None:
        if event == "call":
            name = call_targets.get(frame.f_code)
            if name is not None:
                observed_calls[name] += 1
                if name in protected_boundaries:
                    raise ReleaseOperationError(f"blocked route crossed protected boundary: {name}")
            module_name = str(frame.f_globals.get("__name__", ""))
            qualified_name = frame.f_code.co_qualname.lower()
            if module_name.startswith("quant_system."):
                if "unlock" in qualified_name:
                    observed_calls["account_unlock_calls"] += 1
                    raise ReleaseOperationError(
                        "blocked route crossed protected boundary: account_unlock"
                    )
                if "fallback" in qualified_name or "dispatch" in qualified_name:
                    observed_calls["fallback_dispatch_calls"] += 1
                    raise ReleaseOperationError(
                        "blocked route crossed protected boundary: fallback_dispatch"
                    )
                if "livebroker" in qualified_name or "live_broker" in qualified_name:
                    observed_calls["live_broker_adapter_calls"] += 1
                    raise ReleaseOperationError(
                        "blocked route crossed protected boundary: live_broker"
                    )
        if previous_profile is not None:
            previous_profile(frame, event, argument)

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
                "exception_class": (f"{exc.__class__.__module__}.{exc.__class__.__qualname__}"),
            }
        else:
            raise ReleaseOperationError("paper replay was not blocked")
    finally:
        sys.setprofile(previous_profile)

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
        "orders": abs(int(after["pending_order_count"]) - int(before["pending_order_count"])),
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
    state_namespace: dict[str, str],
    idempotency_identity: dict[str, str],
    platform_identity: dict[str, Any],
    hqa_identity: dict[str, Any],
    platform_runtime_digest: str,
    hqa_runtime_digest: str,
    execution_authority: dict[str, object],
    postflight_runtime_identity: dict[str, object],
    settings_preflight: dict[str, object],
    settings_postflight: dict[str, object],
    release_preflight: dict[str, object],
    release_postflight: dict[str, object],
    execution: dict[str, object],
) -> dict[str, object]:
    route_module = Path(paper_routes.__file__).resolve()
    replay_request = _paper_run_request()
    preflight_switches = _scoped_switch_observations(
        global_process_value=settings_preflight["global_kill_switch"],
        paper_account_value=execution["account_before"]["paper_account_local_kill_switch"],
        replay_request_value=replay_request.enable_kill_switch,
    )
    postflight_switches = _scoped_switch_observations(
        global_process_value=settings_postflight["global_kill_switch"],
        paper_account_value=execution["account_after"]["paper_account_local_kill_switch"],
        replay_request_value=replay_request.enable_kill_switch,
    )
    body: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "authority_kind": AUTHORITY_KIND,
        "operation_id": OPERATION_ID,
        "idempotency_identity": idempotency_identity,
        "request_sha256": request_digest,
        "state_namespace": state_namespace,
        "adapter": "quant_system.api.routes.paper.run_paper",
        "simulation_provider": execution["dependency_surface"]["requested_provider"],
        "disposable_account_ref": DISPOSABLE_ACCOUNT,
        "platform_repository": platform_identity,
        "hqa_repository": hqa_identity,
        "platform_runtime_digest": platform_runtime_digest,
        "hqa_runtime_digest": hqa_runtime_digest,
        "platform_execution_authority": execution_authority,
        "postflight_runtime_identity": postflight_runtime_identity,
        "safety_preflight": {
            **settings_preflight,
            "paper_account_local_switch_authority": PAPER_ACCOUNT_SWITCH_AUTHORITY,
            "paper_account_local_kill_switch": execution["account_before"][
                "paper_account_local_kill_switch"
            ],
            "replay_switch_authority": REPLAY_REQUEST_SWITCH_AUTHORITY,
            "replay_enable_kill_switch": replay_request.enable_kill_switch,
            "switch_observations": preflight_switches,
            **release_preflight["facts"],
        },
        "safety_postflight": {
            **settings_postflight,
            "paper_account_local_switch_authority": PAPER_ACCOUNT_SWITCH_AUTHORITY,
            "paper_account_local_kill_switch": execution["account_after"][
                "paper_account_local_kill_switch"
            ],
            "replay_switch_authority": REPLAY_REQUEST_SWITCH_AUTHORITY,
            "replay_enable_kill_switch": replay_request.enable_kill_switch,
            "switch_observations": postflight_switches,
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
    state_namespace: dict[str, str],
    idempotency_identity: dict[str, str],
    platform_identity: dict[str, object],
    hqa_identity: dict[str, object],
    platform_runtime_digest: str,
    hqa_runtime_digest: str,
    execution_authority: dict[str, object],
    postflight_runtime_identity: dict[str, object],
    current_settings: dict[str, object],
    current_release_facts: dict[str, object],
    runtime_root: Path,
) -> None:
    _verify_receipt_digest(receipt)
    _verify_release_artifacts(receipt)
    if receipt.get("operation_id") != OPERATION_ID:
        raise ReleaseOperationError("immutable receipt operation identity mismatch")
    if receipt.get("state_namespace") != state_namespace:
        raise ReleaseOperationError("immutable receipt state namespace mismatch")
    if receipt.get("idempotency_identity") != idempotency_identity:
        raise ReleaseOperationError("immutable receipt idempotency identity mismatch")
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
    if receipt.get("platform_execution_authority") != execution_authority:
        raise ReleaseOperationError("immutable receipt execution authority mismatch")
    if receipt.get("postflight_runtime_identity") != postflight_runtime_identity:
        raise ReleaseOperationError("immutable receipt postflight runtime identity mismatch")
    safety_preflight = receipt.get("safety_preflight")
    safety_postflight = receipt.get("safety_postflight")
    if not isinstance(safety_preflight, dict) or not isinstance(safety_postflight, dict):
        raise ReleaseOperationError("immutable receipt safety facts are invalid")
    expected_switches = {
        "preflight": _scoped_switch_observations(
            global_process_value=safety_preflight.get("global_kill_switch"),
            paper_account_value=safety_preflight.get("paper_account_local_kill_switch"),
            replay_request_value=safety_preflight.get("replay_enable_kill_switch"),
        ),
        "postflight": _scoped_switch_observations(
            global_process_value=safety_postflight.get("global_kill_switch"),
            paper_account_value=safety_postflight.get("paper_account_local_kill_switch"),
            replay_request_value=safety_postflight.get("replay_enable_kill_switch"),
        ),
    }
    if (
        safety_preflight.get("switch_observations") != expected_switches["preflight"]
        or safety_postflight.get("switch_observations") != expected_switches["postflight"]
    ):
        raise ReleaseOperationError("immutable receipt switch scope authority is invalid")
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


def _verify_postflight_runtime_identity(
    *,
    platform_root: Path,
    hqa_root: Path,
    platform_preflight: object,
    hqa_preflight: object,
    platform_modules: tuple[Path, ...],
    hqa_modules: tuple[Path, ...],
    platform_runtime_digest: str,
    hqa_runtime_digest: str,
) -> dict[str, object]:
    try:
        platform_postflight = git_identity(platform_root, require_clean=True)
    except ReleaseOperationError as exc:
        raise ReleaseOperationError("postflight Platform repository identity is not clean") from exc
    try:
        hqa_postflight = git_identity(hqa_root, require_clean=True)
    except ReleaseOperationError as exc:
        raise ReleaseOperationError("postflight HQA repository identity is not clean") from exc
    if platform_postflight != platform_preflight:
        raise ReleaseOperationError("postflight Platform repository identity changed")
    if hqa_postflight != hqa_preflight:
        raise ReleaseOperationError("postflight HQA repository identity changed")
    platform_postflight_digest = _runtime_digest(platform_root, platform_modules)
    hqa_postflight_digest = _runtime_digest(hqa_root, hqa_modules)
    if platform_postflight_digest != platform_runtime_digest:
        raise ReleaseOperationError("postflight Platform runtime digest changed")
    if hqa_postflight_digest != hqa_runtime_digest:
        raise ReleaseOperationError("postflight HQA runtime digest changed")
    return {
        "platform_repository": asdict(platform_postflight),
        "hqa_repository": asdict(hqa_postflight),
        "platform_runtime_digest": platform_postflight_digest,
        "hqa_runtime_digest": hqa_postflight_digest,
    }


def _authoritative_seal_document(
    *,
    request_path: Path,
    claim_path: Path,
    receipt_path: Path,
    state_namespace: dict[str, str],
    idempotency_identity: dict[str, str],
    post_receipt_runtime_identity: dict[str, object],
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": SEAL_SCHEMA_VERSION,
        "authority_kind": "two_phase_zero_effect_receipt_seal",
        "operation_id": OPERATION_ID,
        "state_namespace": state_namespace,
        "idempotency_identity": idempotency_identity,
        "request_sha256": sha256_file(request_path),
        "claim_sha256": sha256_file(claim_path),
        "authoritative_receipt_sha256": sha256_file(receipt_path),
        "post_receipt_runtime_identity": post_receipt_runtime_identity,
        "state": "authoritative",
        "sealed_at": utc_now(),
    }
    body["seal_sha256"] = sha256_bytes(canonical_json_bytes(body))
    return body


def _validate_authoritative_seal(
    *,
    seal_path: Path,
    request_path: Path,
    claim_path: Path,
    receipt_path: Path,
    state_namespace: dict[str, str],
    idempotency_identity: dict[str, str],
) -> dict[str, object]:
    try:
        seal = json.loads(read_private_regular(seal_path))
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("authoritative seal is not valid JSON") from exc
    if not isinstance(seal, dict):
        raise ReleaseOperationError("authoritative seal is not an object")
    claimed_digest = seal.get("seal_sha256")
    body = dict(seal)
    body.pop("seal_sha256", None)
    if claimed_digest != sha256_bytes(canonical_json_bytes(body)):
        raise ReleaseOperationError("authoritative seal digest mismatch")
    expected = {
        "schema_version": SEAL_SCHEMA_VERSION,
        "authority_kind": "two_phase_zero_effect_receipt_seal",
        "operation_id": OPERATION_ID,
        "state_namespace": state_namespace,
        "idempotency_identity": idempotency_identity,
        "request_sha256": sha256_file(request_path),
        "claim_sha256": sha256_file(claim_path),
        "authoritative_receipt_sha256": sha256_file(receipt_path),
        "state": "authoritative",
    }
    for key, value in expected.items():
        if seal.get(key) != value:
            raise ReleaseOperationError(f"authoritative seal mismatch: {key}")
    if not isinstance(seal.get("sealed_at"), str):
        raise ReleaseOperationError("authoritative seal timestamp is absent")
    if not isinstance(seal.get("post_receipt_runtime_identity"), dict):
        raise ReleaseOperationError("authoritative seal runtime identity is absent")
    return seal


def _write_two_phase_authoritative_seal(
    *,
    journal_dir: Path,
    request_path: Path,
    claim_path: Path,
    receipt_path: Path,
    seal_path: Path,
    receipt: dict[str, object],
    state_namespace: dict[str, str],
    idempotency_identity: dict[str, str],
    verify_runtime_identity: Callable[[], dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    """Write receipt, recheck authority, then write and recheck its seal."""

    write_immutable(receipt_path, canonical_json_bytes(receipt))
    _fsync_directory(journal_dir)
    post_receipt_runtime_identity = verify_runtime_identity()
    seal = _authoritative_seal_document(
        request_path=request_path,
        claim_path=claim_path,
        receipt_path=receipt_path,
        state_namespace=state_namespace,
        idempotency_identity=idempotency_identity,
        post_receipt_runtime_identity=post_receipt_runtime_identity,
    )
    write_immutable(seal_path, canonical_json_bytes(seal))
    _fsync_directory(journal_dir)
    post_seal_runtime_identity = verify_runtime_identity()
    if post_seal_runtime_identity != post_receipt_runtime_identity:
        raise ReleaseOperationError("runtime identity changed while sealing receipt")
    validated = _validate_authoritative_seal(
        seal_path=seal_path,
        request_path=request_path,
        claim_path=claim_path,
        receipt_path=receipt_path,
        state_namespace=state_namespace,
        idempotency_identity=idempotency_identity,
    )
    if validated != seal:
        raise ReleaseOperationError("authoritative seal changed after write")
    return seal, post_seal_runtime_identity


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _exclusive_operation_lock(journal_dir: Path) -> Iterator[Path]:
    """Serialize one operation identity without weakening crash recovery."""

    lock_path = journal_dir / "operation.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ReleaseOperationError("zero-effect operation lock is unsafe") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ReleaseOperationError("zero-effect operation lock is not owner-only")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield lock_path
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _claim_document(
    *,
    request_digest: str,
    route_child_timeout_seconds: float,
    state_namespace: dict[str, str],
    idempotency_identity: dict[str, str],
    platform_identity: dict[str, object],
    hqa_identity: dict[str, object],
    platform_runtime_digest: str,
    hqa_runtime_digest: str,
) -> dict[str, object]:
    return {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "authority_kind": AUTHORITY_KIND,
        "operation_id": OPERATION_ID,
        "idempotency_identity": idempotency_identity,
        "request_sha256": request_digest,
        "route_child_timeout_seconds": route_child_timeout_seconds,
        "state_namespace": state_namespace,
        "platform_repository": platform_identity,
        "hqa_repository": hqa_identity,
        "platform_runtime_digest": platform_runtime_digest,
        "hqa_runtime_digest": hqa_runtime_digest,
        "state": "in_progress",
        "recovery": "fail_closed_without_route_retry",
        "claimed_at": utc_now(),
    }


def _validate_claim(
    claim_path: Path,
    *,
    request_digest: str,
    route_child_timeout_seconds: float,
    state_namespace: dict[str, str],
    idempotency_identity: dict[str, str],
    platform_identity: dict[str, object],
    hqa_identity: dict[str, object],
    platform_runtime_digest: str,
    hqa_runtime_digest: str,
) -> dict[str, object]:
    try:
        claim = json.loads(read_private_regular(claim_path))
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("in-progress claim is not valid JSON") from exc
    if not isinstance(claim, dict):
        raise ReleaseOperationError("in-progress claim is not an object")
    expected = {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "authority_kind": AUTHORITY_KIND,
        "operation_id": OPERATION_ID,
        "idempotency_identity": idempotency_identity,
        "request_sha256": request_digest,
        "route_child_timeout_seconds": route_child_timeout_seconds,
        "state_namespace": state_namespace,
        "platform_repository": platform_identity,
        "hqa_repository": hqa_identity,
        "platform_runtime_digest": platform_runtime_digest,
        "hqa_runtime_digest": hqa_runtime_digest,
        "state": "in_progress",
        "recovery": "fail_closed_without_route_retry",
    }
    for key, value in expected.items():
        if claim.get(key) != value:
            raise ReleaseOperationError(f"in-progress claim mismatch: {key}")
    if not isinstance(claim.get("claimed_at"), str):
        raise ReleaseOperationError("in-progress claim timestamp is absent")
    return claim


def _run_zero_effect_proof_locked(
    *,
    platform_root: Path,
    hqa_root: Path,
    state_dir: Path,
    route_child_timeout_seconds: float,
    request_bytes: bytes | None = None,
) -> dict[str, object]:
    """Submit once and reconcile same-byte replay without a second route call."""

    platform_root = platform_root.resolve()
    hqa_root = hqa_root.resolve()
    route_child_timeout_seconds = _validate_route_child_timeout_seconds(route_child_timeout_seconds)
    state_dir = ensure_private_directory(state_dir)
    state_namespace = state_namespace_identity(state_dir)
    idempotency_identity = _idempotency_identity(state_namespace)
    journal_dir = ensure_private_directory(state_dir / "journal")
    runtime_root = ensure_private_directory(state_dir / "disposable-runtime")
    api_runs_dir = ensure_private_directory(runtime_root / "runs")
    request_path = journal_dir / "request.json"
    claim_path = journal_dir / "in-progress-claim.json"
    receipt_path = journal_dir / "authoritative-receipt.json"
    seal_path = journal_dir / "authoritative-seal.json"

    expected_request = default_request_bytes(
        state_namespace,
        route_child_timeout_seconds=route_child_timeout_seconds,
    )
    raw_request = request_bytes if request_bytes is not None else expected_request
    if request_path.exists() and read_private_regular(request_path) != raw_request:
        raise ReleaseOperationError("same operation identity has different request bytes")
    journal_presence = {
        "request": request_path.exists(),
        "claim": claim_path.exists(),
        "receipt": receipt_path.exists(),
        "seal": seal_path.exists(),
    }
    if journal_presence["receipt"] != journal_presence["seal"]:
        raise ReleaseOperationError("partial two-phase zero-effect journal")
    if journal_presence["seal"] and not all(journal_presence.values()):
        raise ReleaseOperationError("partial immutable zero-effect journal")
    if journal_presence["claim"] and not journal_presence["request"]:
        raise ReleaseOperationError("partial immutable zero-effect journal")
    if journal_presence["request"] and not journal_presence["claim"]:
        raise ReleaseOperationError("partial immutable zero-effect journal")
    try:
        decoded = json.loads(raw_request)
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("request bytes are not valid JSON") from exc
    if not isinstance(decoded, dict) or decoded.get("operation_id") != OPERATION_ID:
        raise ReleaseOperationError("request operation_id is not the fixed proof identity")
    if canonical_json_bytes(decoded) != raw_request:
        raise ReleaseOperationError("request bytes are not canonical and exact")
    if raw_request != expected_request:
        raise ReleaseOperationError("different request bytes from the fixed proof")
    if decoded.get("state_namespace") != state_namespace:
        raise ReleaseOperationError("request state namespace is not exact")
    if decoded.get("idempotency_identity") != idempotency_identity:
        raise ReleaseOperationError("request idempotency identity is not exact")
    try:
        route_request = PaperRunRequest.model_validate(decoded["paper_run_request"])
    except Exception as exc:
        raise ReleaseOperationError("paper replay request payload is invalid") from exc
    if route_request != _paper_run_request():
        raise ReleaseOperationError("paper replay request model is not exact")

    execution_authority = validate_platform_execution_authority(platform_root)
    platform = git_identity(platform_root, require_clean=True)
    hqa = git_identity(hqa_root, require_clean=True)
    hqa_module = hqa_root / "hqa" / "__init__.py"
    if hqa_module.is_symlink() or not hqa_module.is_file():
        raise ReleaseOperationError("HQA runtime module is absent")
    authority_modules = execution_authority["modules"]
    assert isinstance(authority_modules, dict)
    platform_modules = tuple(
        Path(record["path"])
        for record in authority_modules.values()
        if isinstance(record, dict) and isinstance(record.get("path"), str)
    ) + (_release_status_cli(platform_root),)
    hqa_modules = (hqa_module,)
    platform_runtime_digest = _runtime_digest(platform_root, platform_modules)
    hqa_runtime_digest = _runtime_digest(hqa_root, hqa_modules)
    _, account = _load_or_create_account(runtime_root)
    account_before = _account_observation(account)
    if account_before["paper_account_local_kill_switch"] is not True:
        raise ReleaseOperationError("disposable PaperAccount kill switch is not closed")
    tree_before = _tree_observation(runtime_root)

    request_digest = sha256_bytes(raw_request)
    platform_identity = asdict(platform)
    hqa_identity = asdict(hqa)
    if claim_path.exists():
        _validate_claim(
            claim_path,
            request_digest=request_digest,
            route_child_timeout_seconds=route_child_timeout_seconds,
            state_namespace=state_namespace,
            idempotency_identity=idempotency_identity,
            platform_identity=platform_identity,
            hqa_identity=hqa_identity,
            platform_runtime_digest=platform_runtime_digest,
            hqa_runtime_digest=hqa_runtime_digest,
        )
        if not seal_path.exists():
            raise ReleaseOperationError(
                "in-progress claim has no authoritative seal; refusing route retry"
            )
    first_was_replay = seal_path.exists()

    active_settings = Settings()
    settings_preflight = _settings_safety_observation(active_settings)
    release_preflight = _fresh_release_status_observation(
        platform_root=platform_root,
        state_dir=state_dir,
    )
    if first_was_replay:
        receipt, route_invocations_this_call = _replay_receipt_observation(receipt_path)
        authoritative_seal = _validate_authoritative_seal(
            seal_path=seal_path,
            request_path=request_path,
            claim_path=claim_path,
            receipt_path=receipt_path,
            state_namespace=state_namespace,
            idempotency_identity=idempotency_identity,
        )
    else:
        write_immutable(request_path, raw_request)
        write_immutable(
            claim_path,
            canonical_json_bytes(
                _claim_document(
                    request_digest=request_digest,
                    route_child_timeout_seconds=route_child_timeout_seconds,
                    state_namespace=state_namespace,
                    idempotency_identity=idempotency_identity,
                    platform_identity=platform_identity,
                    hqa_identity=hqa_identity,
                    platform_runtime_digest=platform_runtime_digest,
                    hqa_runtime_digest=hqa_runtime_digest,
                )
            ),
        )
        _fsync_directory(journal_dir)
        execution = _execute_repository_block_in_child(
            platform_root=platform_root,
            state_dir=state_dir,
            request=route_request,
            api_runs_dir=api_runs_dir,
            tree_before=tree_before,
            execution_authority=execution_authority,
            route_child_timeout_seconds=route_child_timeout_seconds,
        )
        route_invocations_this_call = int(execution["route_invocations"])
        settings_postflight = _settings_safety_observation(Settings())
        release_postflight = _fresh_release_status_observation(
            platform_root=platform_root,
            state_dir=state_dir,
        )
        postflight_runtime_identity = _verify_postflight_runtime_identity(
            platform_root=platform_root,
            hqa_root=hqa_root,
            platform_preflight=platform,
            hqa_preflight=hqa,
            platform_modules=platform_modules,
            hqa_modules=hqa_modules,
            platform_runtime_digest=platform_runtime_digest,
            hqa_runtime_digest=hqa_runtime_digest,
        )
        receipt = _authoritative_receipt(
            request_digest=request_digest,
            state_namespace=state_namespace,
            idempotency_identity=idempotency_identity,
            platform_identity=platform_identity,
            hqa_identity=hqa_identity,
            platform_runtime_digest=platform_runtime_digest,
            hqa_runtime_digest=hqa_runtime_digest,
            execution_authority=execution_authority,
            postflight_runtime_identity=postflight_runtime_identity,
            settings_preflight=settings_preflight,
            settings_postflight=settings_postflight,
            release_preflight=release_preflight,
            release_postflight=release_postflight,
            execution=execution,
        )

        def verify_runtime_identity() -> dict[str, object]:
            return _verify_postflight_runtime_identity(
                platform_root=platform_root,
                hqa_root=hqa_root,
                platform_preflight=platform,
                hqa_preflight=hqa,
                platform_modules=platform_modules,
                hqa_modules=hqa_modules,
                platform_runtime_digest=platform_runtime_digest,
                hqa_runtime_digest=hqa_runtime_digest,
            )

        authoritative_seal, sealed_runtime_identity = _write_two_phase_authoritative_seal(
            journal_dir=journal_dir,
            request_path=request_path,
            claim_path=claim_path,
            receipt_path=receipt_path,
            seal_path=seal_path,
            receipt=receipt,
            state_namespace=state_namespace,
            idempotency_identity=idempotency_identity,
            verify_runtime_identity=verify_runtime_identity,
        )
        if sealed_runtime_identity != postflight_runtime_identity:
            raise ReleaseOperationError("sealed runtime identity differs from postflight")
    if first_was_replay:
        settings_postflight = _settings_safety_observation(Settings())
        release_postflight = _fresh_release_status_observation(
            platform_root=platform_root,
            state_dir=state_dir,
        )
        postflight_runtime_identity = _verify_postflight_runtime_identity(
            platform_root=platform_root,
            hqa_root=hqa_root,
            platform_preflight=platform,
            hqa_preflight=hqa,
            platform_modules=platform_modules,
            hqa_modules=hqa_modules,
            platform_runtime_digest=platform_runtime_digest,
            hqa_runtime_digest=hqa_runtime_digest,
        )
        if authoritative_seal.get("post_receipt_runtime_identity") != postflight_runtime_identity:
            raise ReleaseOperationError("sealed runtime identity drifted on replay")
    _validate_existing_receipt(
        receipt=receipt,
        request_digest=request_digest,
        state_namespace=state_namespace,
        idempotency_identity=idempotency_identity,
        platform_identity=platform_identity,
        hqa_identity=hqa_identity,
        platform_runtime_digest=platform_runtime_digest,
        hqa_runtime_digest=hqa_runtime_digest,
        execution_authority=execution_authority,
        postflight_runtime_identity=postflight_runtime_identity,
        current_settings=settings_postflight,
        current_release_facts=release_postflight["facts"],
        runtime_root=runtime_root,
    )
    replay_seal = _validate_authoritative_seal(
        seal_path=seal_path,
        request_path=request_path,
        claim_path=claim_path,
        receipt_path=receipt_path,
        state_namespace=state_namespace,
        idempotency_identity=idempotency_identity,
    )
    if replay_seal != authoritative_seal:
        raise ReleaseOperationError("same-id replay did not return the same seal")
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
        "state_namespace": state_namespace,
        "idempotency_identity": idempotency_identity,
        "request_sha256": request_digest,
        "request_base64": base64.b64encode(raw_request).decode("ascii"),
        "route_child_deadline": decoded["route_child_deadline"],
        "first_submission": {
            "idempotent_replay": first_was_replay,
            "route_invocations_this_call": route_invocations_this_call,
            "receipt": receipt,
            "seal": authoritative_seal,
        },
        "exact_same_bytes_replay": {
            "idempotent_replay": (replay == receipt and replay_route_invocations == 0),
            "route_invocations": replay_route_invocations,
            "receipt": replay,
            "seal": replay_seal,
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
            "in_progress_claim": str(claim_path),
            "authoritative_receipt": str(receipt_path),
            "authoritative_seal": str(seal_path),
            "disposable_runtime": str(runtime_root),
        },
    }


def run_zero_effect_proof(
    *,
    platform_root: Path,
    hqa_root: Path,
    state_dir: Path,
    route_child_timeout_seconds: float = DEFAULT_ROUTE_CHILD_TIMEOUT_SECONDS,
    request_bytes: bytes | None = None,
) -> dict[str, object]:
    """Serialize submit/replay and persist a claim before the repository route."""

    route_child_timeout_seconds = _validate_route_child_timeout_seconds(route_child_timeout_seconds)
    private_state = ensure_private_directory(state_dir)
    journal_dir = ensure_private_directory(private_state / "journal")
    with _exclusive_operation_lock(journal_dir):
        return _run_zero_effect_proof_locked(
            platform_root=platform_root,
            hqa_root=hqa_root,
            state_dir=private_state,
            route_child_timeout_seconds=route_child_timeout_seconds,
            request_bytes=request_bytes,
        )
