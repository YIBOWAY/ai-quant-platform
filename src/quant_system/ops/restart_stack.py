"""Compliant launchd stack restart with provider-free authority observations."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

from quant_system.config.settings import Settings
from quant_system.ops.common import (
    ReleaseOperationError,
    canonical_json_bytes,
    ensure_private_directory,
    git_identity,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_immutable,
)
from quant_system.storage.database import get_database, schema_fingerprint

BACKEND_LABEL = "com.aiquant.backend"
FRONTEND_LABEL = "com.aiquant.frontend"
CONNECTOR_LABEL = "com.aiquant.agent-v02-connector"
SETTINGS_URL = "http://127.0.0.1:8765/api/settings"
GATEWAY_URL = "http://127.0.0.1:8765/api/hermes/gateway"
FRONTEND_ORIGIN = "http://127.0.0.1:3001"
CONNECTOR_LOG = Path("data/_runtime/logs/agent-v02-connector.launchd.out.log")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def parse_launchctl_pid(document: str) -> int:
    match = re.search(r"(?m)^\s*pid = ([1-9][0-9]*)\s*$", document)
    if match is None:
        raise ReleaseOperationError("launchd job has no running pid")
    return int(match.group(1))


def validate_settings_observation(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        raise ReleaseOperationError("/api/settings response is not an object")
    public = document.get("safety")
    settings = document.get("settings")
    nested = settings.get("safety") if isinstance(settings, dict) else None
    if not isinstance(public, dict) or not isinstance(nested, dict):
        raise ReleaseOperationError("/api/settings safety projection is absent")
    required = {
        "kill_switch": True,
        "live_trading_enabled": False,
    }
    for name, expected in required.items():
        if public.get(name) is not expected or nested.get(name) is not expected:
            raise ReleaseOperationError(f"/api/settings safety mismatch: {name}")
    if public.get("bind_address") != "127.0.0.1":
        raise ReleaseOperationError("backend bind address is not loopback")
    return {
        "kill_switch": True,
        "live_trading_enabled": False,
        "bind_address": "127.0.0.1",
        "dry_run": public.get("dry_run"),
        "paper_trading": public.get("paper_trading"),
    }


def validate_release_observation(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        raise ReleaseOperationError("release status response is not an object")
    if document.get("contract") != "agent-v0.2-release-cli/v1":
        raise ReleaseOperationError("release status contract is invalid")
    decision = document.get("decision")
    if not isinstance(decision, dict):
        raise ReleaseOperationError("release status decision is absent")
    closed_fields = (
        "release_authorized",
        "public_write_authorized",
        "chat_write_ready",
    )
    for field in closed_fields:
        if decision.get(field) is not False:
            raise ReleaseOperationError(f"release authority is not closed: {field}")
    return {
        "release_authorized": False,
        "public_write_authorized": False,
        "chat_write_ready": False,
        "ready": decision.get("ready"),
        "blockers": decision.get("blockers"),
        "release_stamp_id": decision.get("release_stamp_id"),
        "public_cutover_id": decision.get("public_cutover_id"),
        "event_cursor": decision.get("event_cursor"),
    }


def validate_gateway_observation(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        raise ReleaseOperationError("/api/hermes/gateway response is not an object")
    if document.get("chat_write_ready") is not False:
        raise ReleaseOperationError("/api/hermes/gateway chat write is not closed")
    return {
        "chat_write_ready": False,
        "read_status": document.get("read_status"),
        "connected": document.get("connected"),
        "session_api_available": document.get("session_api_available"),
        "blockers": document.get("blockers"),
    }


def validate_launcher_source(source: str) -> None:
    if ("|" + "|" + " true") in source:
        raise ReleaseOperationError("launcher contains a forbidden masking construct")
    if ("/api/" + "health") in source:
        raise ReleaseOperationError("launcher contains a forbidden readiness route")


def _json_get(
    url: str,
    *,
    timeout: float = 3,
) -> dict[str, object]:
    headers = {
        "Accept": "application/json",
        "Origin": FRONTEND_ORIGIN,
        "Sec-Fetch-Site": "same-origin",
    }
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_RejectRedirects())
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ReleaseOperationError(f"provider-free observation failed: {url}")
            if response.geturl() != url:
                raise ReleaseOperationError("provider-free observation redirected")
            content_type = response.headers.get_content_type()
            if content_type != "application/json":
                raise ReleaseOperationError("provider-free observation is not JSON content")
            raw = response.read(8 * 1024 * 1024 + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise ReleaseOperationError(f"provider-free observation unavailable: {url}") from exc
    if len(raw) > 8 * 1024 * 1024:
        raise ReleaseOperationError("provider-free observation is oversized")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("provider-free observation is not JSON") from exc
    if not isinstance(document, dict):
        raise ReleaseOperationError("provider-free observation is not an object")
    return document


def _launchctl_document(launchctl: str, domain: str, label: str) -> str:
    completed = subprocess.run(
        [launchctl, "print", f"{domain}/{label}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ReleaseOperationError(f"launchd job is unavailable: {label}")
    return completed.stdout


def _process_facts(
    *,
    launchctl: str,
    domain: str,
    label: str,
    repository_root: Path,
    preflight: dict[str, object],
    require_runtime_match: bool = True,
) -> dict[str, object]:
    launchd = _launchctl_document(launchctl, domain, label)
    pid = parse_launchctl_pid(launchd)
    scripts = {
        BACKEND_LABEL: "run_quant_backend.sh",
        FRONTEND_LABEL: "run_quant_frontend.sh",
        CONNECTOR_LABEL: "run_agent_v02_connector.sh",
    }
    script = scripts.get(label)
    if script is None:
        raise ReleaseOperationError("unknown launchd label")
    expected_script = repository_root / "scripts" / script
    if str(expected_script) not in launchd:
        raise ReleaseOperationError(f"launchd source path mismatch: {label}")
    launcher_sha256 = sha256_file(expected_script)
    if launcher_sha256 != preflight.get("source_sha256"):
        raise ReleaseOperationError(f"launchd source changed after preflight: {label}")
    command = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    executable = subprocess.run(
        ["ps", "-p", str(pid), "-o", "comm="],
        check=False,
        capture_output=True,
        text=True,
    )
    executable_images = subprocess.run(
        ["lsof", "-nP", "-a", "-p", str(pid), "-d", "txt", "-Fn"],
        check=False,
        capture_output=True,
        text=True,
    )
    cwd_result = subprocess.run(
        ["lsof", "-nP", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        check=False,
        capture_output=True,
        text=True,
    )
    if any(
        result.returncode != 0
        for result in (command, executable, executable_images, cwd_result)
    ):
        raise ReleaseOperationError(f"process identity observation failed: {label}")
    image_paths = [
        line[1:]
        for line in executable_images.stdout.splitlines()
        if line.startswith("n") and len(line) > 1
    ]
    if not image_paths:
        raise ReleaseOperationError(f"process executable image is absent: {label}")
    runtime = preflight.get("runtime")
    if not isinstance(runtime, dict):
        raise ReleaseOperationError(f"preflight runtime identity is absent: {label}")
    runtime_executable_name = "node" if label == FRONTEND_LABEL else "python"
    runtime_executable = runtime.get(runtime_executable_name)
    if not isinstance(runtime_executable, str):
        raise ReleaseOperationError(f"preflight executable identity is absent: {label}")
    runtime_matches = (
        Path(image_paths[0]).resolve() == Path(runtime_executable).resolve()
    )
    if require_runtime_match and not runtime_matches:
        raise ReleaseOperationError(f"running executable differs from preflight: {label}")
    cwd_paths = [
        line[1:]
        for line in cwd_result.stdout.splitlines()
        if line.startswith("n") and len(line) > 1
    ]
    expected_cwd = (
        repository_root / "src" / "frontend"
        if label == FRONTEND_LABEL
        else repository_root
    )
    if len(cwd_paths) != 1 or Path(cwd_paths[0]).resolve() != expected_cwd.resolve():
        raise ReleaseOperationError(f"process working directory mismatch: {label}")

    facts: dict[str, object] = {
        "label": label,
        "pid": pid,
        "process_executable": executable.stdout.strip(),
        "process_command": command.stdout.strip(),
        "actual_executable_image": image_paths[0],
        "actual_executable_image_sha256": sha256_file(Path(image_paths[0])),
        "mapped_text_image_count": len(image_paths),
        "working_directory": cwd_paths[0],
        "launchd_document_sha256": sha256_bytes(launchd.encode("utf-8")),
        "launcher_path": str(expected_script),
        "launcher_sha256": launcher_sha256,
        "preflight_source_sha256": preflight["source_sha256"],
        "runtime_matches_preflight": runtime_matches,
    }
    if label in {BACKEND_LABEL, FRONTEND_LABEL}:
        listeners = subprocess.run(
            [
                "lsof",
                "-nP",
                "-a",
                "-p",
                str(pid),
                "-iTCP",
                "-sTCP:LISTEN",
                "-Fn",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if listeners.returncode != 0:
            raise ReleaseOperationError(f"listener observation failed: {label}")
        listener_names = [
            line[1:]
            for line in listeners.stdout.splitlines()
            if line.startswith("n") and len(line) > 1
        ]
        expected_port = 8765 if label == BACKEND_LABEL else 3001
        expected_listener = f"127.0.0.1:{expected_port}"
        if not listener_names or set(listener_names) != {expected_listener}:
            raise ReleaseOperationError(f"process listener is not exact loopback: {label}")
        facts.update(
            {
                "listener_sha256": sha256_bytes(listeners.stdout.encode("utf-8")),
                "listeners": sorted(set(listener_names)),
                "loopback_port": expected_port,
            }
        )
    if label == FRONTEND_LABEL:
        installed_root = (repository_root / "src" / "frontend" / "node_modules").resolve()
        mapped_installed = [
            path
            for path in image_paths
            if Path(path).resolve().is_relative_to(installed_root)
        ]
        if not mapped_installed:
            raise ReleaseOperationError("frontend has no mapped release node_modules image")
        build_id = repository_root / "src" / "frontend" / ".next" / "BUILD_ID"
        if build_id.is_symlink() or not build_id.is_file():
            raise ReleaseOperationError("frontend build identity is absent")
        facts["mapped_release_node_modules_images"] = mapped_installed
        facts["next_build_id_sha256"] = sha256_file(build_id)
    return facts


def _wait_tcp(port: int, *, deadline: float) -> None:
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.2)
    raise ReleaseOperationError(f"loopback port {port} did not become ready") from last_error


def _wait_settings(*, deadline: float) -> dict[str, object]:
    last_error: ReleaseOperationError | None = None
    while time.monotonic() < deadline:
        try:
            return _json_get(SETTINGS_URL)
        except ReleaseOperationError as exc:
            last_error = exc
            time.sleep(0.2)
    raise ReleaseOperationError("provider-free /api/settings did not become ready") from last_error


def _release_status(repository_root: Path) -> dict[str, object]:
    cli = repository_root / ".venv" / "bin" / "quant-system"
    if not cli.is_file() or not os.access(cli, os.X_OK):
        raise ReleaseOperationError("installed quant-system CLI is unavailable")
    argv = [str(cli), "hermes", "release", "status"]
    completed = subprocess.run(
        argv,
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ReleaseOperationError("provider-free release status command failed")
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("release status output is not JSON") from exc
    return {
        "facts": validate_release_observation(document),
        "command": {
            "argv": argv,
            "exit_code": completed.returncode,
            "stdout_sha256": sha256_bytes(completed.stdout),
            "stdout_bytes": len(completed.stdout),
            "stderr_sha256": sha256_bytes(completed.stderr),
            "stderr_bytes": len(completed.stderr),
        },
    }


def _validate_connector_cycle(document: object) -> dict[str, object]:
    if not isinstance(document, dict):
        raise ReleaseOperationError("connector cycle is not a JSON object")
    if document.get("mode") != "reconcile_only":
        raise ReleaseOperationError("connector is not in reconcile-only mode")
    zero_fields = (
        "claimed_count",
        "delivered_count",
        "dispatch_unknown_count",
        "hermes_mutation_count",
        "outcome_unknown_count",
        "provider_call_count",
        "recovered_count",
        "rejected_count",
        "requeued_count",
        "terminal_count",
    )
    observed: dict[str, int] = {}
    for field in zero_fields:
        value = document.get(field)
        if type(value) is not int or value != 0:
            raise ReleaseOperationError(f"connector cycle has a nonzero effect: {field}")
        observed[field] = value
    if document.get("last_command_id") is not None:
        raise ReleaseOperationError("connector cycle observed a command")
    if document.get("last_dispatch_outcome") is not None:
        raise ReleaseOperationError("connector cycle observed a dispatch outcome")
    return {
        "mode": "reconcile_only",
        "effect_counters": observed,
        "last_command_id": None,
        "last_dispatch_outcome": None,
        "capability_read_status": document.get("capability_read_status"),
        "connector_liveness": document.get("connector_liveness"),
        "session_provisioning": document.get("session_provisioning"),
    }


def _connector_log_snapshot(path: Path) -> dict[str, object]:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ReleaseOperationError("connector log is absent") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ReleaseOperationError("connector log is not a regular file")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ReleaseOperationError("connector log is not owner-only")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        current = os.fstat(descriptor)
        if current.st_dev != info.st_dev or current.st_ino != info.st_ino:
            raise ReleaseOperationError("connector log identity changed during observation")
        if current.st_size == 0:
            raise ReleaseOperationError("connector log is empty")
        os.lseek(descriptor, -1, os.SEEK_END)
        if os.read(descriptor, 1) != b"\n":
            raise ReleaseOperationError("connector log has an incomplete current record")
        read_size = min(current.st_size, 1024 * 1024)
        os.lseek(descriptor, current.st_size - read_size, os.SEEK_SET)
        tail = os.read(descriptor, read_size)
    finally:
        os.close(descriptor)
    complete_lines = [line for line in tail.splitlines() if line.strip()]
    if not complete_lines:
        raise ReleaseOperationError("connector log has no complete record")
    try:
        latest = json.loads(complete_lines[-1])
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("latest connector cycle is not JSON") from exc
    return {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
        "offset": info.st_size,
        "latest_cycle": _validate_connector_cycle(latest),
        "latest_cycle_sha256": sha256_bytes(complete_lines[-1] + b"\n"),
    }


def _wait_fresh_connector_cycle(
    path: Path,
    *,
    snapshot: dict[str, object],
    deadline: float,
) -> dict[str, object]:
    offset = snapshot.get("offset")
    device = snapshot.get("device")
    inode = snapshot.get("inode")
    if type(offset) is not int or type(device) is not int or type(inode) is not int:
        raise ReleaseOperationError("connector log snapshot is malformed")
    while time.monotonic() < deadline:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            current = os.fstat(descriptor)
            if current.st_dev != device or current.st_ino != inode:
                raise ReleaseOperationError("connector log rotated during restart")
            if current.st_size < offset:
                raise ReleaseOperationError("connector log was truncated during restart")
            available = current.st_size - offset
            if available > 1024 * 1024:
                raise ReleaseOperationError("fresh connector evidence is oversized")
            os.lseek(descriptor, offset, os.SEEK_SET)
            appended = os.read(descriptor, available)
        finally:
            os.close(descriptor)
        for line in appended.splitlines(keepends=True):
            if not line.endswith(b"\n") or not line.strip():
                continue
            try:
                document = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReleaseOperationError("fresh connector cycle is not JSON") from exc
            return {
                "start_offset": offset,
                "end_offset": offset + len(line),
                "record_sha256": sha256_bytes(line),
                "cycle": _validate_connector_cycle(document),
            }
        time.sleep(0.2)
    raise ReleaseOperationError("no fresh connector cycle arrived after restart")


def _command_queue_facts(settings: Settings) -> dict[str, object]:
    database = get_database(settings)
    if database is None:
        raise ReleaseOperationError("command queue database is unavailable")
    try:
        with database.connect() as conn, conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            rows = conn.execute(
                """
                SELECT state, count(*)
                FROM quant_system.hermes_commands
                GROUP BY state
                ORDER BY state
                """
            ).fetchall()
            pending_outbox = conn.execute(
                """
                SELECT count(*)
                FROM quant_system.hermes_outbox
                WHERE topic = 'hermes.command.queued'
                  AND consumed_at IS NULL
                """
            ).fetchone()
    except Exception as exc:
        raise ReleaseOperationError("command queue read-only observation failed") from exc
    state_counts = {str(row[0]): int(row[1]) for row in rows}
    active_count = sum(state_counts.get(state, 0) for state in ("queued", "leased"))
    outbox_count = int(pending_outbox[0]) if pending_outbox is not None else -1
    if active_count != 0 or outbox_count != 0:
        raise ReleaseOperationError("connector command queue is not empty")
    return {
        "state_counts": state_counts,
        "queued_or_leased_count": active_count,
        "pending_queued_outbox_count": outbox_count,
        "transaction_read_only": True,
    }


def _preflight_check(repository_root: Path, script: str) -> dict[str, object]:
    path = repository_root / "scripts" / script
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise ReleaseOperationError(f"restart launcher is unsafe: {script}")
    source = path.read_text(encoding="utf-8")
    validate_launcher_source(source)
    completed = subprocess.run(
        [str(path), "--check"],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    payload = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise ReleaseOperationError(f"restart preflight failed: {script}")
    try:
        stdout = completed.stdout.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as exc:
        raise ReleaseOperationError(f"restart preflight is not UTF-8: {script}") from exc
    patterns = {
        "run_quant_backend.sh": (
            re.compile(
                r"^backend_ready=true release_root=(\S+) python=(\S+) module=(\S+)$"
            ),
            ("release_root", "python", "module"),
            'exec "$PYTHON" -m quant_system.cli serve --host 127.0.0.1 --port 8765',
        ),
        "run_quant_frontend.sh": (
            re.compile(
                r"^frontend_ready=true release_root=(\S+) node=(\S+) next=(\S+)$"
            ),
            ("release_root", "node", "next"),
            'exec "$NODE_BIN" "$NEXT_BIN" start -H 127.0.0.1 -p 3001',
        ),
        "run_agent_v02_connector.sh": (
            re.compile(r"^connector_ready=true release_root=(\S+) python=(\S+)$"),
            ("release_root", "python"),
            'exec "$PYTHON" -m quant_system.cli hermes connector-worker',
        ),
    }
    definition = patterns.get(script)
    if definition is None:
        raise ReleaseOperationError(f"unknown restart preflight: {script}")
    pattern, fields, required_exec = definition
    match = pattern.fullmatch(stdout)
    if match is None:
        raise ReleaseOperationError(f"restart preflight identity is malformed: {script}")
    runtime = dict(zip(fields, match.groups(), strict=True))
    if Path(runtime["release_root"]).resolve() != repository_root.resolve():
        raise ReleaseOperationError(f"restart preflight release root mismatch: {script}")
    if required_exec not in source:
        raise ReleaseOperationError(f"restart launcher exec contract mismatch: {script}")
    executable_name = "node" if script == "run_quant_frontend.sh" else "python"
    executable = Path(runtime[executable_name])
    resolved_executable = (
        executable.resolve() if executable.is_symlink() else executable.absolute()
    )
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ReleaseOperationError(f"restart preflight executable is absent: {script}")
    runtime[f"{executable_name}_resolved"] = str(resolved_executable)
    if script == "run_quant_backend.sh":
        expected_python = repository_root / ".venv" / "bin" / "python"
        if executable.absolute() != expected_python.absolute():
            raise ReleaseOperationError("backend is not bound to the release .venv")
        expected_module = repository_root / "src" / "quant_system" / "__init__.py"
        if Path(runtime["module"]).resolve() != expected_module.resolve():
            raise ReleaseOperationError("backend module does not resolve to release source")
        runtime["module_sha256"] = sha256_file(expected_module)
    if script == "run_quant_frontend.sh":
        expected_next = (
            repository_root / "src" / "frontend" / "node_modules" / ".bin" / "next"
        )
        if Path(runtime["next"]).absolute() != expected_next.absolute():
            raise ReleaseOperationError("frontend is not bound to release node_modules")
    return {
        "argv": [str(path), "--check"],
        "exit_code": completed.returncode,
        "source_sha256": sha256_bytes(source.encode("utf-8")),
        "stdout_stderr_sha256": sha256_bytes(payload),
        "stdout_stderr_bytes": len(payload),
        "runtime": runtime,
    }


def restart_stack(
    *,
    repository_root: Path,
    output_dir: Path,
    timeout_seconds: float = 30,
) -> dict[str, object]:
    repository_root = repository_root.resolve()
    output_dir = ensure_private_directory(output_dir)
    receipt_path = output_dir / "restart-receipt.json"
    if receipt_path.exists():
        raise ReleaseOperationError("restart receipt already exists")
    identity = git_identity(repository_root, require_clean=True)
    launchctl = shutil.which("launchctl")
    if launchctl is None:
        raise ReleaseOperationError("launchctl is unavailable")
    domain = f"gui/{os.getuid()}"
    settings = Settings()
    checks = {
        "backend": _preflight_check(repository_root, "run_quant_backend.sh"),
        "frontend": _preflight_check(repository_root, "run_quant_frontend.sh"),
        "connector": _preflight_check(
            repository_root,
            "run_agent_v02_connector.sh",
        ),
    }
    connector_log_path = repository_root / CONNECTOR_LOG
    connector_log_snapshot = _connector_log_snapshot(connector_log_path)
    pre_settings_raw = _json_get(SETTINGS_URL)
    pre_gateway_raw = _json_get(GATEWAY_URL)
    pre = {
        "backend": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=BACKEND_LABEL,
            repository_root=repository_root,
            preflight=checks["backend"],
            require_runtime_match=False,
        ),
        "frontend": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=FRONTEND_LABEL,
            repository_root=repository_root,
            preflight=checks["frontend"],
            require_runtime_match=False,
        ),
        "connector": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=CONNECTOR_LABEL,
            repository_root=repository_root,
            preflight=checks["connector"],
        ),
        "settings": validate_settings_observation(pre_settings_raw),
        "gateway": validate_gateway_observation(pre_gateway_raw),
        "release": _release_status(repository_root),
        "schema_fingerprint": schema_fingerprint(get_database(settings)),
        "command_queue": _command_queue_facts(settings),
        "connector_log": connector_log_snapshot,
    }
    if pre["schema_fingerprint"] in {"<db-disabled>", "<unavailable>"}:
        raise ReleaseOperationError("pre-restart schema fingerprint is unavailable")
    for label in (BACKEND_LABEL, FRONTEND_LABEL):
        completed = subprocess.run(
            [launchctl, "kickstart", "-k", f"{domain}/{label}"],
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise ReleaseOperationError(f"launchd kickstart failed: {label}")

    deadline = time.monotonic() + timeout_seconds
    _wait_tcp(8765, deadline=deadline)
    _wait_tcp(3001, deadline=deadline)
    post_settings_raw = _wait_settings(deadline=deadline)
    post_gateway_raw = _json_get(GATEWAY_URL)
    fresh_connector_cycle = _wait_fresh_connector_cycle(
        connector_log_path,
        snapshot=connector_log_snapshot,
        deadline=deadline,
    )
    post = {
        "backend": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=BACKEND_LABEL,
            repository_root=repository_root,
            preflight=checks["backend"],
        ),
        "frontend": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=FRONTEND_LABEL,
            repository_root=repository_root,
            preflight=checks["frontend"],
        ),
        "connector": _process_facts(
            launchctl=launchctl,
            domain=domain,
            label=CONNECTOR_LABEL,
            repository_root=repository_root,
            preflight=checks["connector"],
        ),
        "settings": validate_settings_observation(post_settings_raw),
        "gateway": validate_gateway_observation(post_gateway_raw),
        "release": _release_status(repository_root),
        "schema_fingerprint": schema_fingerprint(get_database(Settings())),
        "command_queue": _command_queue_facts(Settings()),
        "fresh_connector_cycle": fresh_connector_cycle,
    }
    if post["schema_fingerprint"] != pre["schema_fingerprint"]:
        raise ReleaseOperationError("schema fingerprint changed across restart")
    for service in ("backend", "frontend"):
        if pre[service]["pid"] == post[service]["pid"]:  # type: ignore[index]
            raise ReleaseOperationError(f"{service} pid did not change")
    if pre["connector"]["pid"] != post["connector"]["pid"]:  # type: ignore[index]
        raise ReleaseOperationError("connector was unexpectedly restarted")
    if (
        pre["frontend"]["next_build_id_sha256"]  # type: ignore[index]
        != post["frontend"]["next_build_id_sha256"]  # type: ignore[index]
    ):
        raise ReleaseOperationError("frontend build identity changed across restart")
    post_identity = git_identity(repository_root, require_clean=True)
    if post_identity != identity:
        raise ReleaseOperationError("repository identity changed across restart")
    if pre["settings"] != post["settings"]:
        raise ReleaseOperationError("safety settings changed across restart")
    receipt: dict[str, object] = {
        "schema_version": "agent-v0.2.2-launchd-restart.v1",
        "status": "passed",
        "completed_at": utc_now(),
        "repository": asdict(identity),
        "post_restart_repository": asdict(post_identity),
        "provider_free_readiness_paths": [
            "/api/settings",
            "/api/hermes/gateway",
            "quant-system hermes release status",
        ],
        "forbidden_readiness_path_used": False,
        "preflight_checks": checks,
        "pre_restart": pre,
        "post_restart": post,
        "processes_replaced": True,
        "connector_was_not_restarted": True,
        "connector_fresh_reconcile_only_cycle_observed": True,
        "command_queue_empty_before_and_after": True,
        "source_identity_unchanged": True,
        "safety_identity_unchanged": True,
        "release_authorized": False,
    }
    write_immutable(receipt_path, canonical_json_bytes(receipt))
    return receipt
