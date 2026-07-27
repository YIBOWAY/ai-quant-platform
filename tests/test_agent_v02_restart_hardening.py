from __future__ import annotations

import copy
import json
import subprocess
import time
from pathlib import Path

import pytest

from quant_system.ops import restart_stack
from quant_system.ops.common import GitIdentity, ReleaseOperationError


def _build_facts(*, tree: str, root: str = "/release/src/frontend/.next") -> dict[str, object]:
    return {
        "root": root,
        "tree_sha256": tree * 64,
        "entry_count": 3,
        "file_count": 2,
        "total_bytes": 17,
        "build_id_sha256": "b" * 64,
    }


def _identity() -> GitIdentity:
    return GitIdentity(
        path="/release/platform",
        branch="codex/agent-v0-2-release",
        commit="c" * 40,
        tree="d" * 40,
        origin_url="https://example.invalid/platform.git",
        status_sha256="e" * 64,
        clean=True,
    )


def _connector_cycle(*, include_liveness: bool = True) -> dict[str, object]:
    cycle: dict[str, object] = {
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
    }
    if include_liveness:
        cycle["connector_liveness"] = {"status": "not_acquired"}
    return cycle


def _connector_process(*, pid: int = 301, runs: int = 7) -> dict[str, object]:
    return {
        "label": restart_stack.CONNECTOR_LABEL,
        "pid": pid,
        "process_started_at": "Mon Jul 27 16:50:06 2026",
        "process_command": (
            "/release/python -m quant_system.cli hermes connector-worker --mode reconcile_only"
        ),
        "actual_executable_image": "/release/python",
        "actual_executable_image_sha256": "a" * 64,
        "launcher_sha256": "b" * 64,
        "launchd_runs": runs,
        "last_exit_code": 0,
        "connector_mode": "reconcile_only",
    }


def _service_process(
    label: str,
    *,
    pid: int,
    next_build: dict[str, object] | None = None,
) -> dict[str, object]:
    process: dict[str, object] = {
        "label": label,
        "pid": pid,
        "process_executable": "python" if label != restart_stack.FRONTEND_LABEL else "node",
        "process_started_at": f"Mon Jul 27 16:50:{pid % 60:02d} 2026",
        "process_command": f"/release/{label}",
        "actual_executable_image": f"/release/{label}-runtime",
        "actual_executable_image_sha256": "a" * 64,
        "working_directory": (
            "/release/platform/src/frontend"
            if label == restart_stack.FRONTEND_LABEL
            else "/release/platform"
        ),
        "launcher_path": f"/release/platform/scripts/{label}.sh",
        "launcher_sha256": "b" * 64,
        "preflight_source_sha256": "b" * 64,
        "runtime_matches_preflight": True,
        "listeners": (
            ["127.0.0.1:3001"] if label == restart_stack.FRONTEND_LABEL else ["127.0.0.1:8765"]
        ),
        "loopback_port": 3001 if label == restart_stack.FRONTEND_LABEL else 8765,
    }
    if label == restart_stack.FRONTEND_LABEL:
        process["mapped_release_node_modules_images"] = [
            "/release/platform/src/frontend/node_modules/next/runtime.node"
        ]
        process["next_build"] = next_build
    return process


def _full_connector_process(*, pid: int = 301, runs: int = 7) -> dict[str, object]:
    process = _connector_process(pid=pid, runs=runs)
    process.update(
        {
            "process_executable": "python",
            "working_directory": "/release/platform",
            "launcher_path": ("/release/platform/scripts/run_agent_v02_connector.sh"),
            "preflight_source_sha256": "b" * 64,
            "runtime_matches_preflight": True,
        }
    )
    return process


def _settings_document() -> dict[str, object]:
    safety = {
        "kill_switch": True,
        "live_trading_enabled": False,
        "dry_run": True,
        "paper_trading": True,
        "bind_address": "127.0.0.1",
    }
    return {
        "safety": dict(safety),
        "settings": {"safety": dict(safety)},
    }


def _gateway_document() -> dict[str, object]:
    return {
        "chat_write_ready": False,
        "read_status": "available",
        "connected": True,
        "session_api_available": True,
        "blockers": [],
    }


def _seal_authority(authority: dict[str, object]) -> dict[str, object]:
    authority["authority_sha256"] = restart_stack.sha256_bytes(
        restart_stack.canonical_json_bytes(authority)
    )
    return authority


def test_restart_settings_require_exact_safe_values_in_both_layers() -> None:
    expected = {
        "kill_switch": True,
        "live_trading_enabled": False,
        "dry_run": True,
        "paper_trading": True,
        "bind_address": "127.0.0.1",
    }
    accepted = restart_stack.validate_settings_observation(_settings_document())
    assert accepted == expected

    wrong_values = {
        "kill_switch": False,
        "live_trading_enabled": True,
        "dry_run": False,
        "paper_trading": False,
        "bind_address": "0.0.0.0",
    }
    for layer in ("public", "nested"):
        for field, wrong_value in wrong_values.items():
            missing = _settings_document()
            missing_safety = (
                missing["safety"] if layer == "public" else missing["settings"]["safety"]  # type: ignore[index]
            )
            assert isinstance(missing_safety, dict)
            del missing_safety[field]
            with pytest.raises(ReleaseOperationError, match=field):
                restart_stack.validate_settings_observation(missing)

            wrong = _settings_document()
            wrong_safety = (
                wrong["safety"] if layer == "public" else wrong["settings"]["safety"]  # type: ignore[index]
            )
            assert isinstance(wrong_safety, dict)
            wrong_safety[field] = wrong_value
            with pytest.raises(ReleaseOperationError, match=field):
                restart_stack.validate_settings_observation(wrong)


def test_pre_activation_authority_rejects_candidate_bytes_bound_to_old_process() -> None:
    old_build = _build_facts(tree="1")
    candidate_build = _build_facts(tree="2")
    authority = _seal_authority(
        {
            "repository": {
                field: getattr(_identity(), field) for field in _identity().__dataclass_fields__
            },
            "captured_monotonic_ns": 10,
            "processes": {
                "frontend": {
                    "pid": 100,
                    "next_build": old_build,
                }
            },
        }
    )
    activation = {
        "active_before": old_build,
        "active_after": candidate_build,
    }

    accepted = restart_stack._validate_pre_activation_restart_authority(
        authority,
        identity=_identity(),
        activation=activation,
    )
    assert accepted["processes"]["frontend"]["next_build"] == old_build

    corrupt_digest = copy.deepcopy(authority)
    corrupt_digest["captured_monotonic_ns"] = 11
    with pytest.raises(ReleaseOperationError, match="digest"):
        restart_stack._validate_pre_activation_restart_authority(
            corrupt_digest,
            identity=_identity(),
            activation=activation,
        )

    falsely_bound = copy.deepcopy(authority)
    falsely_bound["processes"]["frontend"]["next_build"] = candidate_build
    del falsely_bound["authority_sha256"]
    _seal_authority(falsely_bound)
    with pytest.raises(
        ReleaseOperationError,
        match="pre-activation frontend build",
    ):
        restart_stack._validate_pre_activation_restart_authority(
            falsely_bound,
            identity=_identity(),
            activation=activation,
        )


def test_connector_generation_and_liveness_are_mandatory_for_restart() -> None:
    generation = restart_stack._connector_generation_authority(_connector_process())
    assert generation["pid"] == 301
    assert generation["launchd_runs"] == 7
    assert generation["mode"] == "reconcile_only"

    missing_runs = _connector_process()
    del missing_runs["launchd_runs"]
    with pytest.raises(ReleaseOperationError, match="generation"):
        restart_stack._connector_generation_authority(missing_runs)

    with pytest.raises(ReleaseOperationError, match="liveness"):
        restart_stack._validate_connector_cycle(
            _connector_cycle(include_liveness=False),
            require_liveness=True,
        )
    observed = restart_stack._validate_connector_cycle(
        _connector_cycle(),
        require_liveness=True,
    )
    assert observed["connector_liveness"] == {"status": "not_acquired"}


def test_connector_heartbeat_rejects_stale_or_different_generation() -> None:
    generation = restart_stack._connector_generation_authority(_connector_process())
    boundary = {
        "offset": 100,
        "captured_monotonic_ns": 1_000,
        "connector_generation": generation,
    }
    observation = {
        "start_offset": 100,
        "end_offset": 240,
        "observed_monotonic_ns": 1_001,
        "record_sha256": "f" * 64,
        "cycle": restart_stack._validate_connector_cycle(
            _connector_cycle(),
            require_liveness=True,
        ),
        "connector_generation": generation,
    }
    accepted = restart_stack._validate_connector_heartbeat_observation(
        boundary,
        observation,
    )
    assert accepted["fresh_after_boundary"] is True

    stale = copy.deepcopy(observation)
    stale["observed_monotonic_ns"] = 999
    with pytest.raises(ReleaseOperationError, match="stale"):
        restart_stack._validate_connector_heartbeat_observation(boundary, stale)

    replaced = copy.deepcopy(observation)
    replaced["connector_generation"] = restart_stack._connector_generation_authority(
        _connector_process(pid=302, runs=8)
    )
    with pytest.raises(ReleaseOperationError, match="generation"):
        restart_stack._validate_connector_heartbeat_observation(
            boundary,
            replaced,
        )


def test_connector_snapshot_does_not_replay_a_cycle_seen_during_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector_log = tmp_path / "connector.log"
    connector_log.write_text(
        json.dumps(
            {
                **_connector_cycle(),
                "capability_read_status": "before-snapshot",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    connector_log.chmod(0o600)
    raced_line = (
        json.dumps(
            {
                **_connector_cycle(),
                "capability_read_status": "seen-during-open",
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()
    original_open = restart_stack.os.open
    appended = False

    def append_before_snapshot_open(
        path: object,
        flags: int,
        *args: object,
    ) -> int:
        nonlocal appended
        if (
            not appended
            and Path(path) == connector_log
            and flags & restart_stack.os.O_ACCMODE == restart_stack.os.O_RDONLY
        ):
            appended = True
            writer = original_open(
                path,
                restart_stack.os.O_WRONLY | restart_stack.os.O_APPEND,
            )
            try:
                restart_stack.os.write(writer, raced_line)
            finally:
                restart_stack.os.close(writer)
        return original_open(path, flags, *args)

    monkeypatch.setattr(restart_stack.os, "open", append_before_snapshot_open)
    snapshot = restart_stack._connector_log_snapshot(
        connector_log,
        require_liveness=True,
    )
    assert snapshot["latest_cycle"]["capability_read_status"] == "seen-during-open"
    generation = restart_stack._connector_generation_authority(_connector_process())
    snapshot["connector_generation"] = generation
    snapshot["captured_monotonic_ns"] = time.monotonic_ns()

    with pytest.raises(ReleaseOperationError, match="no fresh connector cycle"):
        restart_stack._wait_fresh_connector_cycle(
            connector_log,
            snapshot=snapshot,
            deadline=time.monotonic() + 0.01,
            connector_generation=generation,
            require_liveness=True,
        )


def test_recovery_attempts_both_services_even_when_backend_kickstart_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_run(
        argv: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        label = argv[-1]
        calls.append(label)
        return subprocess.CompletedProcess(
            argv,
            17 if label.endswith(restart_stack.BACKEND_LABEL) else 0,
            stdout=b"",
            stderr=b"",
        )

    monkeypatch.setattr(restart_stack.subprocess, "run", fake_run)
    recovery = restart_stack._reconcile_services_after_rollback(
        repository_root=Path("/release/platform"),
        restart_state={
            "service_reconciliation_required": True,
            "launchctl": "/usr/bin/launchctl",
            "domain": "gui/501",
            "checks": {
                "backend": {},
                "frontend": {},
                "connector": {},
            },
            "pre_activation_authority": {
                "processes": {
                    "backend": {"pid": 11},
                    "frontend": {"pid": 12},
                    "connector": _connector_process(),
                },
            },
        },
        restored_build=_build_facts(tree="1"),
        timeout_seconds=0.01,
        identity=_identity(),
    )

    assert calls == [
        "gui/501/com.aiquant.backend",
        "gui/501/com.aiquant.frontend",
    ]
    assert recovery["status"] == "recovery_incomplete"
    assert recovery["both_services_kickstart_attempted"] is True
    assert "backend_kickstart_failed" in recovery["errors"]


def test_restart_attempts_service_reconciliation_when_build_restore_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "platform"
    repository.mkdir()
    output = tmp_path / "evidence"
    old_build = _build_facts(tree="1")
    candidate_build = _build_facts(tree="2")
    rollback = {
        "path": str(tmp_path / "retained-old-build"),
        "facts": old_build,
        "available_until_restart_outcome": True,
    }
    build_authority = {
        "atomic_activation": {
            "active_before": old_build,
            "active_after": candidate_build,
            "rollback": rollback,
        }
    }
    pre_activation = {
        "processes": {
            "backend": {"pid": 11},
            "frontend": {"pid": 12, "next_build": old_build},
            "connector": _connector_process(),
        }
    }
    reconciliation_targets: list[dict[str, object]] = []

    monkeypatch.setattr(
        restart_stack,
        "git_identity",
        lambda _root, require_clean: _identity(),
    )
    monkeypatch.setattr(
        restart_stack,
        "_capture_pre_activation_restart_authority",
        lambda _root, identity: pre_activation,
    )
    monkeypatch.setattr(
        restart_stack,
        "_build_current_frontend",
        lambda _root, _identity_value: (build_authority, {"exit_code": 0}),
    )

    def fail_after_kickstart(**kwargs: object) -> dict[str, object]:
        state = kwargs["restart_state"]
        assert isinstance(state, dict)
        state.update(
            {
                "service_reconciliation_required": True,
                "launchctl": "/usr/bin/launchctl",
                "domain": "gui/501",
                "checks": {
                    "backend": {},
                    "frontend": {},
                    "connector": {},
                },
                "pre_activation_authority": pre_activation,
            }
        )
        raise ReleaseOperationError("post-kickstart failure")

    monkeypatch.setattr(
        restart_stack,
        "_complete_activated_restart",
        fail_after_kickstart,
    )
    monkeypatch.setattr(
        restart_stack,
        "_restore_frontend_rollback",
        lambda **_kwargs: (_ for _ in ()).throw(
            ReleaseOperationError("active frontend changed before rollback")
        ),
    )

    def reconcile(**kwargs: object) -> dict[str, object]:
        target = kwargs["restored_build"]
        assert isinstance(target, dict)
        reconciliation_targets.append(target)
        return {
            "status": "recovery_incomplete",
            "both_services_kickstart_attempted": True,
            "errors": ["frontend_build_not_restored"],
        }

    monkeypatch.setattr(
        restart_stack,
        "_reconcile_services_after_rollback",
        reconcile,
    )

    with pytest.raises(ReleaseOperationError, match="recovery was incomplete"):
        restart_stack.restart_stack(
            repository_root=repository,
            output_dir=output,
            timeout_seconds=0.01,
        )

    assert reconciliation_targets == [old_build]
    recovery = json.loads((output / "restart-failure-recovery.json").read_text(encoding="utf-8"))
    assert recovery["status"] == "recovery_incomplete"
    assert recovery["service_reconciliation"]["both_services_kickstart_attempted"] is True
    assert recovery["manual_recovery_artifacts"]["retained_rollback"] == rollback


def test_follow_cycle_boundary_requires_observation_after_boundary() -> None:
    boundary = {
        "offset": 100,
        "captured_monotonic_ns": time.monotonic_ns(),
        "connector_generation": restart_stack._connector_generation_authority(_connector_process()),
    }
    stale = {
        "start_offset": 100,
        "end_offset": 200,
        "observed_monotonic_ns": boundary["captured_monotonic_ns"],
        "record_sha256": "0" * 64,
        "cycle": restart_stack._validate_connector_cycle(
            _connector_cycle(),
            require_liveness=True,
        ),
        "connector_generation": boundary["connector_generation"],
    }
    with pytest.raises(ReleaseOperationError, match="stale"):
        restart_stack._validate_connector_heartbeat_observation(boundary, stale)


@pytest.mark.parametrize(
    "mutate_at_provisional_publication",
    (False, True),
    ids=("sealed-success", "mutation-rejected"),
)
def test_complete_restart_uses_pre_activation_build_and_fresh_connector_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate_at_provisional_publication: bool,
) -> None:
    repository = tmp_path / "platform"
    active_next = repository / "src" / "frontend" / ".next"
    (active_next / "server").mkdir(parents=True)
    (active_next / "BUILD_ID").write_text("old\n", encoding="utf-8")
    (active_next / "server" / "page.js").write_text("old\n", encoding="utf-8")
    old_build = restart_stack.frontend_build_tree_facts(active_next)
    (active_next / "BUILD_ID").write_text("candidate\n", encoding="utf-8")
    (active_next / "server" / "page.js").write_text(
        "candidate\n",
        encoding="utf-8",
    )
    candidate_build = restart_stack.frontend_build_tree_facts(active_next)
    connector_log = repository / restart_stack.CONNECTOR_LOG
    connector_log.parent.mkdir(parents=True)
    connector_log.write_text(
        json.dumps(_connector_cycle(), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    connector_log.chmod(0o600)
    connector_snapshot = restart_stack._connector_log_snapshot(
        connector_log,
        require_liveness=True,
    )
    identity = GitIdentity(
        **{
            **_identity().__dict__,
            "path": str(repository),
        }
    )
    checks = {
        "backend": {"source_sha256": "b" * 64},
        "frontend": {"source_sha256": "b" * 64},
        "connector": {"source_sha256": "b" * 64},
    }
    runtime_authority = {"authority_sha256": "9" * 64}
    runtime_state = {"current": runtime_authority}
    release = {"facts": {"release_authorized": False}, "command": {}}
    queue = {
        "state_counts": {},
        "queued_or_leased_count": 0,
        "pending_queued_outbox_count": 0,
        "transaction_read_only": True,
    }
    pre_processes = {
        "backend": _service_process(
            restart_stack.BACKEND_LABEL,
            pid=11,
        ),
        "frontend": _service_process(
            restart_stack.FRONTEND_LABEL,
            pid=12,
            next_build=old_build,
        ),
        "connector": _full_connector_process(),
    }
    settings = restart_stack.validate_settings_observation(_settings_document())
    gateway = restart_stack.validate_gateway_observation(_gateway_document())
    pre_activation = {
        "repository": {field: getattr(identity, field) for field in identity.__dataclass_fields__},
        "captured_monotonic_ns": 1,
        "launchctl": "/usr/bin/launchctl",
        "domain": "gui/501",
        "checks": checks,
        "runtime_authority": runtime_authority,
        "processes": pre_processes,
        "connector_generation": restart_stack._connector_generation_authority(
            pre_processes["connector"]
        ),
        "connector_log": connector_snapshot,
        "settings": settings,
        "gateway": gateway,
        "release": release,
        "schema_fingerprint": "schema-v1",
        "command_queue": queue,
    }
    _seal_authority(pre_activation)
    build_authority = {
        "repository": {
            "commit": identity.commit,
            "tree": identity.tree,
        },
        "next": candidate_build,
        "build_inputs": {
            "pre_build": {"authority_sha256": "8" * 64},
            "post_build": {"authority_sha256": "8" * 64},
            "post_activation": {"authority_sha256": "8" * 64},
            "unchanged": True,
        },
        "atomic_activation": {
            "active_before": old_build,
            "active_after": candidate_build,
            "rollback": {
                "path": str(tmp_path / "rollback"),
                "facts": old_build,
                "available_until_restart_outcome": True,
            },
        },
    }
    post_processes = {
        "backend": _service_process(
            restart_stack.BACKEND_LABEL,
            pid=21,
        ),
        "frontend": _service_process(
            restart_stack.FRONTEND_LABEL,
            pid=22,
            next_build=candidate_build,
        ),
        "connector": _full_connector_process(),
    }
    monkeypatch.setattr(
        restart_stack.shutil,
        "which",
        lambda name: "/usr/bin/launchctl" if name == "launchctl" else None,
    )
    monkeypatch.setattr(
        restart_stack,
        "_preflight_check",
        lambda _root, script: checks[
            {
                "run_quant_backend.sh": "backend",
                "run_quant_frontend.sh": "frontend",
                "run_agent_v02_connector.sh": "connector",
            }[script]
        ],
    )
    monkeypatch.setattr(
        restart_stack,
        "_runtime_authority_snapshot",
        lambda _root, _checks: runtime_state["current"],
    )
    monkeypatch.setattr(restart_stack, "Settings", lambda: object())
    monkeypatch.setattr(restart_stack, "get_database", lambda _settings: object())
    monkeypatch.setattr(
        restart_stack,
        "schema_fingerprint",
        lambda _database: "schema-v1",
    )
    monkeypatch.setattr(
        restart_stack,
        "_command_queue_facts",
        lambda _settings: queue,
    )
    monkeypatch.setattr(
        restart_stack,
        "_release_status",
        lambda _root: release,
    )
    monkeypatch.setattr(
        restart_stack,
        "_wait_settings",
        lambda deadline: _settings_document(),
    )
    monkeypatch.setattr(
        restart_stack,
        "_json_get",
        lambda url: (
            _gateway_document() if url == restart_stack.GATEWAY_URL else _settings_document()
        ),
    )
    monkeypatch.setattr(restart_stack, "_wait_tcp", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        restart_stack,
        "git_identity",
        lambda _root, require_clean: identity,
    )

    def process_facts(**kwargs: object) -> dict[str, object]:
        label = str(kwargs["label"])
        return post_processes[
            {
                restart_stack.BACKEND_LABEL: "backend",
                restart_stack.FRONTEND_LABEL: "frontend",
                restart_stack.CONNECTOR_LABEL: "connector",
            }[label]
        ]

    monkeypatch.setattr(restart_stack, "_process_facts", process_facts)
    monkeypatch.setattr(
        restart_stack.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv,
            0,
            stdout=b"",
            stderr=b"",
        ),
    )
    original_wait = restart_stack._wait_fresh_connector_cycle

    def append_then_wait(
        path: Path,
        **kwargs: object,
    ) -> dict[str, object]:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_connector_cycle(), sort_keys=True) + "\n")
        return original_wait(path, **kwargs)

    monkeypatch.setattr(
        restart_stack,
        "_wait_fresh_connector_cycle",
        append_then_wait,
    )
    if mutate_at_provisional_publication:
        original_write_immutable = restart_stack.write_immutable

        def mutate_after_provisional_publication(
            path: Path,
            payload: bytes,
        ) -> None:
            original_write_immutable(path, payload)
            if path.name == "restart-receipt.provisional.json":
                runtime_state["current"] = {"authority_sha256": "7" * 64}

        monkeypatch.setattr(
            restart_stack,
            "write_immutable",
            mutate_after_provisional_publication,
        )
    output = tmp_path / "evidence"
    output.mkdir()
    restart_state = {"service_reconciliation_required": False}
    if mutate_at_provisional_publication:
        with pytest.raises(
            ReleaseOperationError,
            match="runtime_authority",
        ):
            restart_stack._complete_activated_restart(
                repository_root=repository,
                output_dir=output,
                identity=identity,
                frontend_build_authority=build_authority,
                frontend_build_command={"exit_code": 0},
                restart_state=restart_state,
                pre_activation_authority=pre_activation,
                timeout_seconds=0.1,
            )
        provisional = json.loads(
            (output / "restart-receipt.provisional.json").read_text(encoding="utf-8")
        )
        assert provisional["status"] == "provisional"
        assert not (output / "restart-receipt.json").exists()
        assert restart_state["service_reconciliation_required"] is True
        return
    receipt = restart_stack._complete_activated_restart(
        repository_root=repository,
        output_dir=output,
        identity=identity,
        frontend_build_authority=build_authority,
        frontend_build_command={"exit_code": 0},
        restart_state=restart_state,
        pre_activation_authority=pre_activation,
        timeout_seconds=0.1,
    )

    assert receipt["status"] == "passed"
    assert receipt["pre_restart"]["frontend"]["next_build"] == old_build
    assert receipt["post_restart"]["frontend"]["next_build"] == candidate_build
    assert receipt["post_restart"]["fresh_connector_cycle"]["fresh_after_boundary"] is True
    assert receipt["connector_generation_unchanged"] is True
    provisional = json.loads(
        (output / "restart-receipt.provisional.json").read_text(encoding="utf-8")
    )
    assert provisional["status"] == "provisional"
    assert provisional["intended_status"] == "passed"
    assert receipt["publication_seal"]["status"] == "sealed"
    assert receipt["publication_seal"]["fresh_connector_cycle"]["fresh_after_boundary"] is True


def test_recovery_reconciles_both_services_and_exact_prior_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "platform"
    connector_log = repository / restart_stack.CONNECTOR_LOG
    connector_log.parent.mkdir(parents=True)
    connector_log.write_text(
        json.dumps(_connector_cycle(), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    connector_log.chmod(0o600)
    old_build = _build_facts(
        tree="1",
        root=str(repository / "src" / "frontend" / ".next"),
    )
    pre_processes = {
        "backend": _service_process(
            restart_stack.BACKEND_LABEL,
            pid=11,
        ),
        "frontend": _service_process(
            restart_stack.FRONTEND_LABEL,
            pid=12,
            next_build=old_build,
        ),
        "connector": _full_connector_process(),
    }
    recovered_processes = {
        "backend": _service_process(
            restart_stack.BACKEND_LABEL,
            pid=21,
        ),
        "frontend": _service_process(
            restart_stack.FRONTEND_LABEL,
            pid=22,
            next_build=old_build,
        ),
        "connector": _full_connector_process(),
    }
    settings = restart_stack.validate_settings_observation(_settings_document())
    gateway = restart_stack.validate_gateway_observation(_gateway_document())
    release = {"facts": {"release_authorized": False}, "command": {}}
    queue = {
        "state_counts": {},
        "queued_or_leased_count": 0,
        "pending_queued_outbox_count": 0,
        "transaction_read_only": True,
    }
    runtime_authority = {"authority_sha256": "9" * 64}
    checks = {
        "backend": {},
        "frontend": {},
        "connector": {},
    }
    identity = _identity()
    pre_activation = {
        "processes": pre_processes,
        "connector_log": restart_stack._connector_log_snapshot(
            connector_log,
            require_liveness=True,
        ),
        "settings": settings,
        "gateway": gateway,
        "release": release,
        "schema_fingerprint": "schema-v1",
        "command_queue": queue,
        "runtime_authority": runtime_authority,
    }
    restart_state = {
        "service_reconciliation_required": True,
        "launchctl": "/usr/bin/launchctl",
        "domain": "gui/501",
        "checks": checks,
        "pre_activation_authority": pre_activation,
    }
    monkeypatch.setattr(
        restart_stack.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv,
            0,
            stdout=b"",
            stderr=b"",
        ),
    )
    monkeypatch.setattr(restart_stack, "_wait_tcp", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        restart_stack,
        "_wait_settings",
        lambda deadline: _settings_document(),
    )
    monkeypatch.setattr(
        restart_stack,
        "_json_get",
        lambda _url: _gateway_document(),
    )
    monkeypatch.setattr(
        restart_stack,
        "_release_status",
        lambda _root: release,
    )
    monkeypatch.setattr(restart_stack, "Settings", lambda: object())
    monkeypatch.setattr(restart_stack, "get_database", lambda _settings: object())
    monkeypatch.setattr(
        restart_stack,
        "schema_fingerprint",
        lambda _database: "schema-v1",
    )
    monkeypatch.setattr(
        restart_stack,
        "_command_queue_facts",
        lambda _settings: queue,
    )
    monkeypatch.setattr(
        restart_stack,
        "git_identity",
        lambda _root, require_clean: identity,
    )
    monkeypatch.setattr(
        restart_stack,
        "_runtime_authority_snapshot",
        lambda _root, _checks: runtime_authority,
    )

    def process_facts(**kwargs: object) -> dict[str, object]:
        return recovered_processes[
            {
                restart_stack.BACKEND_LABEL: "backend",
                restart_stack.FRONTEND_LABEL: "frontend",
                restart_stack.CONNECTOR_LABEL: "connector",
            }[str(kwargs["label"])]
        ]

    monkeypatch.setattr(restart_stack, "_process_facts", process_facts)
    original_wait = restart_stack._wait_fresh_connector_cycle

    def append_then_wait(
        path: Path,
        **kwargs: object,
    ) -> dict[str, object]:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_connector_cycle(), sort_keys=True) + "\n")
        return original_wait(path, **kwargs)

    monkeypatch.setattr(
        restart_stack,
        "_wait_fresh_connector_cycle",
        append_then_wait,
    )
    recovery = restart_stack._reconcile_services_after_rollback(
        repository_root=repository,
        restart_state=restart_state,
        restored_build=old_build,
        timeout_seconds=0.1,
        identity=identity,
    )

    assert recovery["status"] == "restored"
    assert recovery["both_services_kickstart_attempted"] is True
    assert recovery["exact_prior_process_authority_restored"] is True
    assert recovery["exact_prior_readiness_authority_restored"] is True
    assert recovery["connector_generation_unchanged"] is True
    assert recovery["connector_fresh_reconcile_only_cycle_observed"] is True
    publication_seal = restart_stack._capture_live_restart_publication_seal(
        repository_root=repository,
        launchctl="/usr/bin/launchctl",
        domain="gui/501",
        checks=checks,
        expected={
            "processes": recovered_processes,
            "settings": settings,
            "gateway": gateway,
            "release": release,
            "schema_fingerprint": "schema-v1",
            "command_queue": queue,
            "repository": {
                field: getattr(identity, field) for field in identity.__dataclass_fields__
            },
            "runtime_authority": runtime_authority,
            "connector_generation": restart_stack._connector_generation_authority(
                pre_processes["connector"]
            ),
            "connector_log": recovery["connector_follow_boundary"],
        },
        deadline=time.monotonic() + 0.1,
    )
    assert publication_seal["status"] == "sealed"
    assert publication_seal["processes"]["frontend"]["next_build"] == old_build
    assert publication_seal["fresh_connector_cycle"]["fresh_after_boundary"] is True
