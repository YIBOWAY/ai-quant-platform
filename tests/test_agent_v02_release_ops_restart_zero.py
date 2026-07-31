from __future__ import annotations

import inspect
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType

import pytest

from quant_system.api.routes import paper as paper_routes
from quant_system.ops import restart_stack, zero_effect
from quant_system.ops.common import (
    GitIdentity,
    ReleaseOperationError,
)
from tests import test_agent_v02_zero_effect_hardening as zero_effect_hardening

ROOT = Path(__file__).resolve().parents[1]


def _frontend_install_fixture(repository: Path, frontend: Path) -> None:
    runtime = repository / "data" / "_runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    environment = runtime / "agent-v0.2-frontend.env"
    environment.write_text("QS_FRONTEND_FIXTURE=true\n", encoding="utf-8")
    environment.chmod(0o600)
    node_modules = frontend / "node_modules"
    (node_modules / ".bin").mkdir(parents=True, exist_ok=True)
    (node_modules / "next").mkdir(parents=True, exist_ok=True)
    (node_modules / ".package-lock.json").write_text(
        '{"installed":true}\n',
        encoding="utf-8",
    )
    (node_modules / "next" / "package.json").write_text(
        '{"name":"next","version":"1.0.0"}\n',
        encoding="utf-8",
    )
    next_executable = node_modules / ".bin" / "next"
    next_executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    next_executable.chmod(0o755)


def _repo(path: Path, *, hqa: bool = False) -> Path:
    path.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "codex/agent-v0-2-release"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "release-ops@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Release Ops Test"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "remote", "add", "github", f"https://example.invalid/{path.name}.git"],
        cwd=path,
        check=True,
    )
    if hqa:
        (path / "hqa").mkdir()
        (path / "hqa" / "__init__.py").write_text(
            '"""fixture."""\n',
            encoding="utf-8",
        )
    else:
        (path / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)
    return path


def _install_fake_release_status_cli(
    repository: Path,
    *,
    mutate_on_postflight: Path | str | None = None,
) -> None:
    exclude = repository / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(".venv/\n")
    cli = repository / ".venv" / "bin" / "quant-system"
    cli.parent.mkdir(parents=True)
    payload = {
        "contract": "agent-v0.2-release-cli/v1",
        "decision": {
            "release_authorized": False,
            "public_write_authorized": False,
            "chat_write_ready": False,
            "ready": False,
            "blockers": ["release_missing"],
        },
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    mutation = os.fspath(mutate_on_postflight) if mutate_on_postflight else None
    cli.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"payload = {rendered!r}\n"
        f"mutation = {mutation!r}\n"
        "if sys.argv[1:] != ['hermes', 'release', 'status']:\n"
        "    raise SystemExit(64)\n"
        "counter = Path(__file__).with_name('status-call-count')\n"
        "calls = int(counter.read_text() or '0') + 1 if counter.exists() else 1\n"
        "counter.write_text(str(calls))\n"
        "if calls == 2 and mutation:\n"
        "    target = Path(__file__) if mutation == '__SELF__' else Path(mutation)\n"
        "    target.write_text(target.read_text() + '\\n# postflight drift\\n')\n"
        "print(payload)\n",
        encoding="utf-8",
    )
    cli.chmod(0o755)


def _proof_repositories(tmp_path: Path) -> tuple[Path, Path]:
    platform = _repo(tmp_path / "platform")
    hqa = _repo(tmp_path / "hqa-repo", hqa=True)
    _install_fake_release_status_cli(platform)
    return platform, hqa


def _route_call_count(callback: object) -> tuple[int, BaseException | None]:
    calls = 0
    previous = sys.getprofile()

    def profiler(frame: FrameType, event: str, _arg: object) -> None:
        nonlocal calls
        if event == "call" and frame.f_code is paper_routes.run_paper.__code__:
            calls += 1

    caught: BaseException | None = None
    sys.setprofile(profiler)
    try:
        assert callable(callback)
        callback()
    except BaseException as exc:  # noqa: BLE001 - the test records crash behavior
        caught = exc
    finally:
        sys.setprofile(previous)
    return calls, caught


def test_zero_effect_crash_after_route_leaves_claim_and_retry_never_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    zero_effect_hardening.test_zero_effect_real_sigkill_after_route_never_retries(tmp_path)


def test_zero_effect_concurrent_same_id_routes_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    zero_effect_hardening.test_zero_effect_concurrent_processes_execute_real_route_exactly_once(
        tmp_path
    )


@pytest.mark.parametrize("drift_kind", ("platform", "hqa", "platform_runtime"))
def test_zero_effect_postflight_rejects_repository_or_runtime_drift_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift_kind: str,
) -> None:
    del monkeypatch
    zero_effect_hardening.assert_zero_effect_postflight_drift_fails(
        tmp_path,
        drift_kind,
    )


def test_frontend_build_authority_binds_current_commit_tree_and_full_next_tree(
    tmp_path: Path,
) -> None:
    tree_facts = getattr(restart_stack, "frontend_build_tree_facts", None)
    validator = getattr(restart_stack, "validate_frontend_build_authority", None)
    assert callable(tree_facts), "restart lacks full .next tree authority"
    assert callable(validator), "restart lacks current-HEAD build authority validation"

    next_root = tmp_path / ".next"
    (next_root / "server").mkdir(parents=True)
    (next_root / "BUILD_ID").write_text("same-build-id\n", encoding="utf-8")
    (next_root / "server" / "page.js").write_text("old bytes\n", encoding="utf-8")
    old_facts = tree_facts(next_root)
    (next_root / "server" / "page.js").write_text("new bytes\n", encoding="utf-8")
    new_facts = tree_facts(next_root)
    assert old_facts["build_id_sha256"] == new_facts["build_id_sha256"]
    assert old_facts["tree_sha256"] != new_facts["tree_sha256"]

    identity = GitIdentity(
        path="/release/platform",
        branch="codex/agent-v0-2-release",
        commit="c" * 40,
        tree="d" * 40,
        origin_url="https://example.invalid/platform.git",
        status_sha256="e" * 64,
        clean=True,
    )
    authority = {
        "repository": {
            "commit": identity.commit,
            "tree": identity.tree,
        },
        "next": new_facts,
        "build_inputs": {
            "pre_build": {"authority_sha256": "f" * 64},
            "post_build": {"authority_sha256": "f" * 64},
            "post_activation": {"authority_sha256": "f" * 64},
            "unchanged": True,
        },
        "atomic_activation": {
            "active_before": old_facts,
            "active_after": new_facts,
            "rollback": {
                "path": "/release/rollback/.next",
                "facts": old_facts,
                "available_until_restart_outcome": True,
            },
        },
    }
    accepted = validator(authority, identity)
    assert accepted["repository"]["commit"] == identity.commit
    stale = json.loads(json.dumps(authority))
    stale["repository"]["commit"] = "a" * 40
    with pytest.raises(ReleaseOperationError, match="current repository"):
        validator(stale, identity)


def test_frontend_failed_build_preserves_active_next_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repo(tmp_path / "platform")
    (repository / ".gitignore").write_text("data/\n", encoding="utf-8")
    frontend = repository / "src" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / ".gitignore").write_text(".next/\nnode_modules/\n", encoding="utf-8")
    (frontend / "package.json").write_text(
        '{"scripts":{"build":"fake"}}\n',
        encoding="utf-8",
    )
    (frontend / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "frontend fixture"], cwd=repository, check=True)
    active_next = frontend / ".next"
    (active_next / "server").mkdir(parents=True)
    (active_next / "BUILD_ID").write_text("active-build\n", encoding="utf-8")
    active_page = active_next / "server" / "page.js"
    active_page.write_text("active bytes\n", encoding="utf-8")
    (frontend / "node_modules").mkdir()
    _frontend_install_fixture(repository, frontend)
    before = restart_stack.frontend_build_tree_facts(active_next)
    fake_npm = tmp_path / "npm"
    fake_npm.write_text(
        "#!/bin/sh\nrm -rf .next\nexit 19\n",
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)
    monkeypatch.setattr(restart_stack.shutil, "which", lambda name: str(fake_npm))

    with pytest.raises(ReleaseOperationError, match="frontend build failed"):
        restart_stack._build_current_frontend(
            repository,
            restart_stack.git_identity(repository, require_clean=True),
        )

    assert active_page.read_text(encoding="utf-8") == "active bytes\n"
    assert restart_stack.frontend_build_tree_facts(active_next) == before


def test_frontend_build_environment_strips_backend_secrets_and_proxies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "must-not-reach-node"
    for name in (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NPM_TOKEN",
        "OPENAI_API_KEY",
        "QS_DATABASE_URL",
        "QS_FUTU_HOST",
        "UV_INDEX_URL",
    ):
        monkeypatch.setenv(name, sentinel)
    frontend_base = "http://127.0.0.1:8765"
    monkeypatch.setenv("NEXT_PUBLIC_QUANT_API_BASE_URL", frontend_base)
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    npm = tmp_path / "bin" / "npm"
    npm.parent.mkdir()
    npm.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    npm.chmod(0o755)
    node = npm.parent / "node"
    node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    node.chmod(0o755)
    monkeypatch.setattr(
        restart_stack.shutil,
        "which",
        lambda name: str(node) if name == "node" else None,
    )

    environment, authority = restart_stack._frontend_build_environment(
        npm=npm,
        workspace=workspace,
    )

    for name in (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NPM_TOKEN",
        "OPENAI_API_KEY",
        "QS_DATABASE_URL",
        "QS_FUTU_HOST",
        "UV_INDEX_URL",
    ):
        assert name not in environment
        assert name not in authority["environment_names"]
    assert environment["NEXT_TELEMETRY_DISABLED"] == "1"
    assert environment["TURBO_TELEMETRY_DISABLED"] == "1"
    assert environment["NPM_CONFIG_OFFLINE"] == "true"
    assert environment["NEXT_PUBLIC_QUANT_API_BASE_URL"] == frontend_base
    for name in ("HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME"):
        assert Path(environment[name]).is_relative_to(workspace)
    rendered = json.dumps(authority, sort_keys=True)
    assert sentinel not in rendered
    assert frontend_base not in rendered
    monkeypatch.setenv(
        "NEXT_PUBLIC_QUANT_API_BASE_URL",
        "http://embedded-secret@127.0.0.1:8765",
    )
    with pytest.raises(ReleaseOperationError, match="loopback origin"):
        restart_stack._frontend_build_environment(
            npm=npm,
            workspace=workspace,
        )


def test_frontend_build_input_drift_preserves_active_next_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repo(tmp_path / "platform")
    (repository / ".gitignore").write_text("data/\n", encoding="utf-8")
    frontend = repository / "src" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / ".gitignore").write_text(".next/\nnode_modules/\n", encoding="utf-8")
    (frontend / "package.json").write_text(
        '{"scripts":{"build":"fake"}}\n',
        encoding="utf-8",
    )
    (frontend / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "frontend fixture"], cwd=repository, check=True)
    active_next = frontend / ".next"
    (active_next / "server").mkdir(parents=True)
    (active_next / "BUILD_ID").write_text("active-build\n", encoding="utf-8")
    (active_next / "server" / "page.js").write_text("old bytes\n", encoding="utf-8")
    (frontend / "node_modules").mkdir()
    _frontend_install_fixture(repository, frontend)
    before = restart_stack.frontend_build_tree_facts(active_next)
    environment = repository / "data" / "_runtime" / "agent-v0.2-frontend.env"
    fake_npm = tmp_path / "npm"
    fake_npm.write_text(
        "#!/bin/sh\n"
        "mkdir -p .next/server\n"
        "printf 'candidate-build\\n' > .next/BUILD_ID\n"
        "printf 'new bytes\\n' > .next/server/page.js\n"
        f"printf 'changed=true\\n' > {shlex.quote(str(environment))}\n",
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)
    monkeypatch.setattr(restart_stack.shutil, "which", lambda name: str(fake_npm))

    with pytest.raises(
        ReleaseOperationError,
        match="environment, dependency, or install changed",
    ):
        restart_stack._build_current_frontend(
            repository,
            restart_stack.git_identity(repository, require_clean=True),
        )

    assert restart_stack.frontend_build_tree_facts(active_next) == before


def test_frontend_success_build_rebinds_and_atomically_activates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repo(tmp_path / "platform")
    (repository / ".gitignore").write_text("data/\n", encoding="utf-8")
    frontend = repository / "src" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / ".gitignore").write_text(".next/\nnode_modules/\n", encoding="utf-8")
    (frontend / "package.json").write_text(
        '{"scripts":{"build":"fake"}}\n',
        encoding="utf-8",
    )
    (frontend / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "frontend fixture"], cwd=repository, check=True)
    active_next = frontend / ".next"
    (active_next / "server").mkdir(parents=True)
    (active_next / "BUILD_ID").write_text("active-build\n", encoding="utf-8")
    (active_next / "server" / "page.js").write_text("old bytes\n", encoding="utf-8")
    (frontend / "node_modules").mkdir()
    _frontend_install_fixture(repository, frontend)
    sentinel = "must-not-reach-node"
    monkeypatch.setenv("QS_DATABASE_URL", sentinel)
    monkeypatch.setenv("HTTPS_PROXY", sentinel)
    monkeypatch.setenv("NPM_TOKEN", sentinel)
    fake_npm = tmp_path / "npm"
    fake_npm.write_text(
        "#!/bin/sh\n"
        'if [ "${QS_DATABASE_URL+x}" = x ]; then exit 91; fi\n'
        'if [ "${HTTPS_PROXY+x}" = x ]; then exit 92; fi\n'
        'if [ "${NPM_TOKEN+x}" = x ]; then exit 93; fi\n'
        'candidate_root="$(cd ../.. && pwd)"\n'
        '[ "$HOME" = "$candidate_root/build-environment/home" ] || exit 94\n'
        '[ "$TMPDIR" = "$candidate_root/build-environment/tmp" ] || exit 95\n'
        '[ "$NPM_CONFIG_CACHE" = '
        '"$candidate_root/build-environment/npm-cache" ] || exit 96\n'
        '[ "$NPM_CONFIG_OFFLINE" = true ] || exit 97\n'
        '[ "$NEXT_TELEMETRY_DISABLED" = 1 ] || exit 98\n'
        "mkdir -p .next/server .next/cache/webpack\n"
        "printf 'candidate-build\\n' > .next/BUILD_ID\n"
        "printf 'new bytes\\n' > .next/server/page.js\n"
        "printf '\\377%s' \"$PWD\" > .next/cache/webpack/0.pack\n"
        'printf \'{"appDir":"%s"}\\n\' "$PWD" > .next/required-server-files.json\n',
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)
    monkeypatch.setattr(restart_stack.shutil, "which", lambda name: str(fake_npm))

    authority, command = restart_stack._build_current_frontend(
        repository,
        restart_stack.git_identity(repository, require_clean=True),
    )

    assert command["exit_code"] == 0
    assert (active_next / "server" / "page.js").read_text() == "new bytes\n"
    required = (active_next / "required-server-files.json").read_text()
    assert str(frontend) in required
    assert "candidate-" not in required
    assert authority["atomic_activation"]["primitive"] in {
        "renamex_np(RENAME_SWAP)",
        "renameat2(RENAME_EXCHANGE)",
    }
    assert authority["excluded_build_cache"]["present_after_build"] is True
    assert authority["excluded_build_cache"]["file_count"] == 1
    assert not (active_next / "cache").exists()
    assert authority["next"] == restart_stack.frontend_build_tree_facts(active_next)
    rollback = authority["atomic_activation"]["rollback"]
    assert Path(rollback["path"]).is_dir()
    assert restart_stack._same_build_content(
        rollback["facts"],
        authority["atomic_activation"]["active_before"],
    )
    rendered = json.dumps(command, sort_keys=True)
    assert sentinel not in rendered
    assert "QS_DATABASE_URL" not in command["environment"]["environment_names"]
    assert "HTTPS_PROXY" not in command["environment"]["environment_names"]
    assert "NPM_TOKEN" not in command["environment"]["environment_names"]


def test_restart_failure_after_activation_restores_active_build_without_kickstart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repo(tmp_path / "platform")
    (repository / ".gitignore").write_text("data/\n", encoding="utf-8")
    frontend = repository / "src" / "frontend"
    frontend.mkdir(parents=True)
    (frontend / ".gitignore").write_text(".next/\nnode_modules/\n", encoding="utf-8")
    (frontend / "package.json").write_text(
        '{"scripts":{"build":"fake"}}\n',
        encoding="utf-8",
    )
    (frontend / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "frontend fixture"], cwd=repository, check=True)
    active_next = frontend / ".next"
    (active_next / "server").mkdir(parents=True)
    (active_next / "BUILD_ID").write_text("active-build\n", encoding="utf-8")
    (active_next / "server" / "page.js").write_text("old bytes\n", encoding="utf-8")
    (frontend / "node_modules").mkdir()
    _frontend_install_fixture(repository, frontend)
    before = restart_stack.frontend_build_tree_facts(active_next)
    fake_npm = tmp_path / "npm"
    fake_npm.write_text(
        "#!/bin/sh\n"
        "mkdir -p .next/server\n"
        "printf 'candidate-build\\n' > .next/BUILD_ID\n"
        "printf 'new bytes\\n' > .next/server/page.js\n",
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)

    def which(name: str) -> str | None:
        if name in {"node", "npm"}:
            return str(fake_npm)
        return None

    monkeypatch.setattr(restart_stack.shutil, "which", which)
    output_dir = tmp_path / "restart-output"
    with pytest.raises(
        ReleaseOperationError,
        match="launchctl is unavailable; frontend build restored",
    ):
        restart_stack.restart_stack(
            repository_root=repository,
            output_dir=output_dir,
            timeout_seconds=0.01,
        )

    assert restart_stack.frontend_build_tree_facts(active_next) == before
    assert not (output_dir / "restart-receipt.json").exists()
    recovery = json.loads(
        (output_dir / "restart-failure-recovery.json").read_text(encoding="utf-8")
    )
    provisional = json.loads(
        (output_dir / "restart-failure-recovery.provisional.json").read_text(encoding="utf-8")
    )
    assert provisional["status"] == "provisional"
    assert provisional["intended_status"] == "restored"
    assert recovery["status"] == "restored"
    assert recovery["publication_seal"]["status"] == "sealed"
    assert recovery["success_receipt_exists"] is False
    assert recovery["rollback_recovery"]["active_restored"] == before
    assert recovery["frontend_process_recovery"]["status"] == "not_required"


def _connector_cycle(sequence: int) -> bytes:
    return (
        json.dumps(
            {
                "mode": "reconcile_only",
                "claimed_count": 0,
                "delivered_count": 0,
                "dispatch_unknown_count": 0,
                "hermes_mutation_count": 0,
                "outcome_unknown_count": 0,
                "provider_call_count": 0,
                "recovered_count": 0,
                "rejected_count": 0,
                "requeued_count": 0,
                "terminal_count": 0,
                "last_command_id": None,
                "last_dispatch_outcome": None,
                "sequence": sequence,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()


def test_connector_follow_boundary_rejects_pre_kickstart_append(
    tmp_path: Path,
) -> None:
    capture = getattr(restart_stack, "_capture_connector_follow_boundary", None)
    assert callable(capture), "restart lacks a post-PID connector follow boundary"
    connector_log = tmp_path / "connector.log"
    connector_log.write_bytes(_connector_cycle(1))
    connector_log.chmod(0o600)
    pre = restart_stack._connector_log_snapshot(connector_log)
    with connector_log.open("ab") as handle:
        handle.write(_connector_cycle(2))
    process_facts = {
        "pre": {
            "backend": {"pid": 10},
            "frontend": {"pid": 20},
            "connector": {"pid": 30},
        },
        "post": {
            "backend": {"pid": 11},
            "frontend": {"pid": 21},
            "connector": {"pid": 30},
        },
    }
    boundary = capture(
        connector_log,
        pre_restart_snapshot=pre,
        process_facts=process_facts,
    )
    assert int(boundary["offset"]) > int(pre["offset"])
    with pytest.raises(ReleaseOperationError, match="no fresh connector cycle"):
        restart_stack._wait_fresh_connector_cycle(
            connector_log,
            snapshot=boundary,
            deadline=time.monotonic() + 0.01,
        )
    with connector_log.open("ab") as handle:
        handle.write(_connector_cycle(3))
    observed = restart_stack._wait_fresh_connector_cycle(
        connector_log,
        snapshot=boundary,
        deadline=time.monotonic() + 1,
    )
    assert observed["cycle"]["mode"] == "reconcile_only"
    restart_source = inspect.getsource(restart_stack._complete_activated_restart)
    kickstart_position = restart_source.index("for label in (BACKEND_LABEL, FRONTEND_LABEL)")
    backend_ready_position = restart_source.index("_wait_tcp(8765")
    frontend_ready_position = restart_source.index("_wait_tcp(3001")
    settings_ready_position = restart_source.index("_wait_settings(")
    gateway_ready_position = restart_source.index("post_gateway_raw = _json_get(GATEWAY_URL)")
    post_process_position = restart_source.index("post_processes =")
    boundary_position = restart_source.index(
        "connector_follow_boundary = _capture_connector_follow_boundary"
    )
    follow_position = restart_source.index("snapshot=connector_follow_boundary")
    assert (
        kickstart_position
        < backend_ready_position
        < frontend_ready_position
        < settings_ready_position
        < gateway_ready_position
        < post_process_position
        < boundary_position
        < follow_position
    )


def test_runtime_authority_binds_env_locks_dependencies_and_installs_without_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = getattr(restart_stack, "_runtime_authority_snapshot", None)
    assert callable(snapshot), "restart lacks environment/install authority"
    repository = tmp_path / "release"
    frontend = repository / "src" / "frontend"
    runtime = repository / "data" / "_runtime"
    node_modules = frontend / "node_modules"
    for directory in (
        runtime,
        node_modules / ".bin",
        node_modules / "next",
        repository / ".venv" / "bin",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    for name in ("backend", "frontend", "connector"):
        env_path = runtime / f"{name}.env"
        env_path.write_text("SECRET_VALUE=do-not-emit\n", encoding="utf-8")
        env_path.chmod(0o600)
        monkeypatch.setenv(f"QS_AGENT_V02_{name.upper()}_ENV_FILE", str(env_path))
    for relative, body in (
        ("uv.lock", "uv lock\n"),
        ("pyproject.toml", "project\n"),
        ("src/frontend/package-lock.json", '{"lockfileVersion":3}\n'),
        ("src/frontend/package.json", '{"name":"fixture"}\n'),
        ("src/frontend/node_modules/.package-lock.json", '{"installed":true}\n'),
        ("src/frontend/node_modules/next/package.json", '{"version":"1.2.3"}\n'),
        (".venv/bin/quant-system", "#!/bin/sh\nexit 0\n"),
    ):
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        if relative.endswith("quant-system"):
            target.chmod(0o755)
    next_bin = node_modules / ".bin" / "next"
    next_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    next_bin.chmod(0o755)
    checks = {
        "backend": {"runtime": {"python": sys.executable}},
        "frontend": {"runtime": {"node": sys.executable, "next": str(next_bin)}},
        "connector": {"runtime": {"python": sys.executable}},
    }

    before = snapshot(repository, checks)
    rendered = json.dumps(before, sort_keys=True)
    assert "do-not-emit" not in rendered
    assert before["environments"]["backend"]["mode"] == "0600"
    assert before["locks"]["python"]["path"].endswith("/uv.lock")
    assert before["installs"]["frontend_node_modules_lock"]["sha256"]
    (runtime / "frontend.env").write_text(
        "SECRET_VALUE=changed-but-still-not-emitted\n",
        encoding="utf-8",
    )
    (runtime / "frontend.env").chmod(0o600)
    after = snapshot(repository, checks)
    assert after != before


def test_release_restart_launchers_and_wrappers_have_no_mask_or_health_probe() -> None:
    for relative in (
        "scripts/run_quant_backend.sh",
        "scripts/run_quant_frontend.sh",
        "scripts/restart_agent_v02_stack.sh",
        "scripts/verify_agent_v02_zero_effect.sh",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "||" + " true" not in source
        assert "/api/" + "health" not in source
    assert restart_stack.SETTINGS_URL.endswith("/api/settings")
    assert restart_stack.GATEWAY_URL.endswith("/api/hermes/gateway")
    assert (
        restart_stack.parse_launchctl_last_exit_code("state = running\n\tlast exit code = 0\n") == 0
    )
    with pytest.raises(ReleaseOperationError, match="last exit code"):
        restart_stack.parse_launchctl_last_exit_code("state = running\n")
    for label in (restart_stack.BACKEND_LABEL, restart_stack.FRONTEND_LABEL):
        assert (
            restart_stack.observed_launchctl_last_exit_code(
                "state = running\n",
                label=label,
            )
            is None
        )
    with pytest.raises(ReleaseOperationError, match="last exit code"):
        restart_stack.observed_launchctl_last_exit_code(
            "state = running\n",
            label=restart_stack.CONNECTOR_LABEL,
        )
    with pytest.raises(ReleaseOperationError, match="nonzero"):
        restart_stack.observed_launchctl_last_exit_code(
            "state = running\n\tlast exit code = 70\n",
            label=restart_stack.CONNECTOR_LABEL,
        )
    assert (
        restart_stack.observed_launchctl_last_exit_code(
            "state = running\n\tlast exit code = 0\n",
            label=restart_stack.CONNECTOR_LABEL,
        )
        == 0
    )
    closed = {
        "contract": "agent-v0.2-release-cli/v1",
        "decision": {
            "release_authorized": False,
            "public_write_authorized": False,
            "chat_write_ready": False,
            "ready": False,
        },
    }
    assert restart_stack.validate_release_observation(closed)["ready"] is False
    closed["decision"]["ready"] = True
    with pytest.raises(ReleaseOperationError, match="ready flag"):
        restart_stack.validate_release_observation(closed)
    zero_source = inspect.getsource(zero_effect._execute_repository_block)
    assert "paper_routes.run_paper_trading =" not in zero_source
    assert "paper_routes.persist_run =" not in zero_source
    assert "sys.setprofile(profile)" in zero_source


def test_connector_accepts_never_exited_only_for_proven_active_generation() -> None:
    valid = (
        "state = active\n"
        "\tpid = 11367\n"
        "\truns = 1\n"
        "\tlast exit code = (never exited)\n"
    )

    assert (
        restart_stack.observed_launchctl_last_exit_code(
            valid,
            label=restart_stack.CONNECTOR_LABEL,
        )
        is None
    )

    invalid_documents = (
        valid.replace("state = active", "state = waiting"),
        valid.replace("\tpid = 11367\n", ""),
        valid.replace("\truns = 1\n", "\truns = 0\n"),
        valid + "\tlast exit code = 0\n",
    )
    for document in invalid_documents:
        with pytest.raises(ReleaseOperationError):
            restart_stack.observed_launchctl_last_exit_code(
                document,
                label=restart_stack.CONNECTOR_LABEL,
            )


def test_connector_generation_preserves_never_exited_identity() -> None:
    facts = {
        "label": restart_stack.CONNECTOR_LABEL,
        "pid": 11367,
        "process_started_at": "Wed Jul 29 08:10:00 2026",
        "process_command": "/release/run-agent connector-worker --mode reconcile_only",
        "actual_executable_image": "/release/.venv/bin/python",
        "actual_executable_image_sha256": "a" * 64,
        "launcher_sha256": "b" * 64,
        "launchd_runs": 1,
        "launchd_state": "active",
        "last_exit_code": None,
        "last_exit_status": "never_exited",
        "connector_mode": "reconcile_only",
    }

    authority = restart_stack._connector_generation_authority(facts)

    assert authority["last_exit_code"] is None
    assert authority["last_exit_status"] == "never_exited"
    assert authority["launchd_state"] == "active"
    recorded_without_code = dict(facts, last_exit_status="recorded")
    with pytest.raises(ReleaseOperationError, match="exit"):
        restart_stack._connector_generation_authority(recorded_without_code)
    recorded_zero = dict(
        facts,
        last_exit_code=0,
        last_exit_status="recorded",
    )
    assert (
        restart_stack._connector_generation_authority(recorded_zero)["last_exit_code"]
        == 0
    )
    recorded_nonzero = dict(recorded_zero, last_exit_code=70)
    with pytest.raises(ReleaseOperationError, match="nonzero"):
        restart_stack._connector_generation_authority(recorded_nonzero)


def test_zero_effect_changed_same_id_request_fails_closed_without_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    zero_effect_hardening.test_zero_effect_changed_same_identity_request_fails_before_observation(
        tmp_path
    )
