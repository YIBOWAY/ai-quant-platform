from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from quant_system.api.routes import paper as paper_routes
from quant_system.ops.common import (
    ReleaseOperationError,
    canonical_json_bytes,
    ensure_private_directory,
)
from quant_system.ops.postgres_common import (
    database_url,
    temporary_database_name,
    validate_loopback_connection_url,
)
from quant_system.ops.postgres_suite import pg_marked_test_files
from quant_system.ops.restart_stack import (
    _validate_connector_cycle,
    parse_launchctl_pid,
    validate_gateway_observation,
    validate_launcher_source,
    validate_release_observation,
    validate_settings_observation,
)
from quant_system.ops.zero_effect import (
    EXPECTED_BLOCK_CODE,
    OPERATION_ID,
    default_request_bytes,
    run_zero_effect_proof,
)

ROOT = Path(__file__).resolve().parents[1]
WRAPPERS = (
    "verify_agent_v02_postgres_suite.sh",
    "verify_agent_v02_noneditable_upgrade.sh",
    "verify_agent_v02_backup_restore.sh",
    "verify_agent_v02_zero_effect.sh",
    "restart_agent_v02_stack.sh",
)


def _repo(path: Path, *, hqa: bool = False) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "codex/agent-v0-2-release"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "release-ops@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Release Ops Test"], cwd=path, check=True)
    subprocess.run(
        ["git", "remote", "add", "github", f"https://example.invalid/{path.name}.git"],
        cwd=path,
        check=True,
    )
    if hqa:
        (path / "hqa").mkdir()
        (path / "hqa" / "__init__.py").write_text('"""fixture."""\n', encoding="utf-8")
    else:
        (path / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)
    return path


def _install_fake_release_status_cli(
    repository: Path,
    *,
    closed: bool = True,
    exit_code: int = 0,
) -> Path:
    exclude = repository / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(".venv/\n")
    cli = repository / ".venv" / "bin" / "quant-system"
    cli.parent.mkdir(parents=True, exist_ok=True)
    decision = {
        "release_authorized": not closed,
        "public_write_authorized": False,
        "chat_write_ready": False,
        "ready": not closed,
        "blockers": ["release_missing"] if closed else [],
    }
    payload = {
        "contract": "agent-v0.2-release-cli/v1",
        "decision": decision,
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    cli.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"payload = {rendered!r}\n"
        "if sys.argv[1:] != ['hermes', 'release', 'status']:\n"
        "    raise SystemExit(64)\n"
        f"if {exit_code}:\n"
        f"    raise SystemExit({exit_code})\n"
        "print(payload)\n",
        encoding="utf-8",
    )
    cli.chmod(0o755)
    return cli


def test_release_operation_wrappers_are_executable_and_provider_free() -> None:
    for name in WRAPPERS:
        path = ROOT / "scripts" / name
        assert path.is_file(), name
        assert path.stat().st_mode & stat.S_IXUSR, name
        source = path.read_text(encoding="utf-8")
        assert "||" + " true" not in source
        assert "/api/" + "health" not in source
    for name in ("run_quant_backend.sh", "run_quant_frontend.sh"):
        validate_launcher_source((ROOT / "scripts" / name).read_text(encoding="utf-8"))
    backend_source = (ROOT / "scripts" / "run_quant_backend.sh").read_text(
        encoding="utf-8"
    )
    assert backend_source.index('"$ROOT/.venv/bin/python"') < backend_source.index(
        '"$ROOT/ai-quant/bin/python"'
    )


def test_zero_effect_proof_is_exact_same_bytes_idempotent_and_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QS_KILL_SWITCH", "true")
    monkeypatch.setenv("QS_LIVE_TRADING_ENABLED", "false")
    platform = _repo(tmp_path / "platform")
    hqa = _repo(tmp_path / "hqa-repo", hqa=True)
    _install_fake_release_status_cli(platform)
    state_dir = tmp_path / "authority"
    original_pipeline = paper_routes.run_paper_trading
    original_persist = paper_routes.persist_run

    result = run_zero_effect_proof(
        platform_root=platform,
        hqa_root=hqa,
        state_dir=state_dir,
    )
    rerun = run_zero_effect_proof(
        platform_root=platform,
        hqa_root=hqa,
        state_dir=state_dir,
    )

    assert paper_routes.run_paper_trading is original_pipeline
    assert paper_routes.persist_run is original_persist
    assert result["status"] == "passed"
    assert result["operation_id"] == OPERATION_ID
    assert result["same_authoritative_receipt"] is True
    assert result["all_effect_counters_zero"] is True
    assert result["repository_block_executed"] is True
    assert result["safety_unchanged"] is True
    assert result["first_submission"]["idempotent_replay"] is False
    assert result["first_submission"]["route_invocations_this_call"] == 1
    assert rerun["first_submission"]["idempotent_replay"] is True
    assert rerun["first_submission"]["route_invocations_this_call"] == 0
    assert rerun["exact_same_bytes_replay"]["route_invocations"] == 0
    observation = result["first_submission"]["receipt"]["execution_observation"]
    assert observation["repository_blocked_result"]["status_code"] == 409
    assert (
        observation["repository_blocked_result"]["detail"]["code"]
        == EXPECTED_BLOCK_CODE
    )
    assert all(value == 0 for value in observation["effect_counters"].values())
    assert all(value == 0 for value in observation["boundary_counters"].values())
    assert observation["passive_call_observations"]["route_invocations"] == 1
    assert observation["account_before"] == observation["account_after"]
    assert observation["tree_before"] == observation["tree_after"]
    assert observation["downstream_globals_restored"] is True
    assert observation["dependency_surface"]["requested_provider"] == "sample"
    assert observation["dependency_surface"]["futu_trade_context_binding_count"] == 0
    receipt = result["first_submission"]["receipt"]
    assert receipt["safety_preflight"]["global_kill_switch"] is True
    assert receipt["safety_preflight"]["paper_account_local_kill_switch"] is True
    assert receipt["safety_preflight"]["replay_enable_kill_switch"] is True
    assert receipt["safety_preflight"]["live_trading_enabled"] is False
    assert receipt["safety_preflight"]["release_authorized"] is False
    assert receipt["safety_preflight"]["public_write_authorized"] is False
    assert receipt["safety_preflight"]["chat_write_ready"] is False
    assert (
        receipt["authoritative_receipt_sha256"]
        == rerun["first_submission"]["receipt"]["authoritative_receipt_sha256"]
    )
    artifact_paths = {
        Path(phase["artifact"]["path"])
        for phase in (
            receipt["release_status_artifacts"]["preflight"],
            receipt["release_status_artifacts"]["postflight"],
            rerun["fresh_release_status_observations_this_call"]["preflight"],
            rerun["fresh_release_status_observations_this_call"]["postflight"],
        )
    }
    assert len(artifact_paths) == 4
    for path in artifact_paths:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for path in (
        state_dir / "journal" / "request.json",
        state_dir / "journal" / "authoritative-receipt.json",
        state_dir / "disposable-runtime" / "paper-account.json",
    ):
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600


def test_zero_effect_proof_fails_closed_on_open_switch_or_changed_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = _repo(tmp_path / "platform")
    hqa = _repo(tmp_path / "hqa-repo", hqa=True)
    _install_fake_release_status_cli(platform)
    state_dir = tmp_path / "authority"

    monkeypatch.setenv("QS_KILL_SWITCH", "false")
    monkeypatch.setenv("QS_LIVE_TRADING_ENABLED", "false")
    with pytest.raises(ReleaseOperationError, match="global kill switch"):
        run_zero_effect_proof(
            platform_root=platform,
            hqa_root=hqa,
            state_dir=tmp_path / "open-global-switch",
        )

    monkeypatch.setenv("QS_KILL_SWITCH", "true")
    _install_fake_release_status_cli(platform, closed=False)
    with pytest.raises(ReleaseOperationError, match="release status is not closed"):
        run_zero_effect_proof(
            platform_root=platform,
            hqa_root=hqa,
            state_dir=tmp_path / "open-release",
        )
    assert not (tmp_path / "open-release" / "release-status").exists()

    _install_fake_release_status_cli(platform, exit_code=70)
    with pytest.raises(ReleaseOperationError, match="release status command failed"):
        run_zero_effect_proof(
            platform_root=platform,
            hqa_root=hqa,
            state_dir=tmp_path / "failed-release-cli",
        )
    assert not (tmp_path / "failed-release-cli" / "release-status").exists()

    _install_fake_release_status_cli(platform)
    run_zero_effect_proof(
        platform_root=platform,
        hqa_root=hqa,
        state_dir=state_dir,
    )
    changed = json.loads(default_request_bytes())
    changed["paper_run_request"]["initial_cash"] = 200_000.0
    with pytest.raises(ReleaseOperationError, match="different request bytes"):
        run_zero_effect_proof(
            platform_root=platform,
            hqa_root=hqa,
            state_dir=state_dir,
            request_bytes=canonical_json_bytes(changed),
        )


def test_postgres_names_and_urls_are_owned_loopback_only() -> None:
    name = temporary_database_name(purpose="contract")
    assert name.startswith("agent_v02_contract_")
    assert name.endswith("_tmp")
    url = database_url(
        "postgresql://operator:secret@127.0.0.1:55432/postgres",
        name,
    )
    facts = validate_loopback_connection_url(url, require_disposable=True)
    assert facts["dbname"] == name
    assert facts["host"] == "127.0.0.1"

    with pytest.raises(ReleaseOperationError, match="loopback"):
        validate_loopback_connection_url(
            "postgresql://operator:secret@db.example/agent_v02_bad_tmp",
            require_disposable=True,
        )
    with pytest.raises(ReleaseOperationError, match="owned temporary namespace"):
        validate_loopback_connection_url(
            "postgresql://operator:secret@127.0.0.1/quantplatform",
            require_disposable=True,
        )
    with pytest.raises(ReleaseOperationError, match="owned namespace"):
        database_url(
            "postgresql://operator:secret@127.0.0.1/postgres",
            "quantplatform",
        )
    with pytest.raises(ReleaseOperationError, match="literal loopback"):
        validate_loopback_connection_url(
            "postgresql://operator:secret@localhost/agent_v02_bad_tmp",
            require_disposable=True,
        )
    with pytest.raises(ReleaseOperationError, match="indirection"):
        validate_loopback_connection_url(
            "postgresql://operator:secret@127.0.0.1/agent_v02_bad_tmp"
            "?hostaddr=127.0.0.1",
            require_disposable=True,
        )


def test_postgres_module_discovery_is_additive_and_excludes_unrelated_skips(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_pg_one.py").write_text(
        "import pytest\npytestmark = pytest.mark.pg\n",
        encoding="utf-8",
    )
    (tests / "test_pg_two.py").write_text(
        "import pytest\n@pytest.mark.pg\ndef test_it(): pass\n",
        encoding="utf-8",
    )
    (tests / "test_unrelated_skip.py").write_text(
        "import pytest\npytest.skip('external service', allow_module_level=True)\n",
        encoding="utf-8",
    )

    assert pg_marked_test_files(tmp_path) == (
        "tests/test_pg_one.py",
        "tests/test_pg_two.py",
    )


def test_private_output_directory_rejects_symlink_components(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    link = tmp_path / "redirect"
    link.symlink_to(destination, target_is_directory=True)
    with pytest.raises(ReleaseOperationError, match="symlink"):
        ensure_private_directory(link / "evidence")


def test_restart_observation_contract_has_deliberate_red_and_green() -> None:
    assert parse_launchctl_pid("state = running\n\tpid = 12345\n") == 12345
    with pytest.raises(ReleaseOperationError, match="no running pid"):
        parse_launchctl_pid("state = exited\n")

    settings = {
        "settings": {
            "safety": {
                "kill_switch": True,
                "live_trading_enabled": False,
            }
        },
        "safety": {
            "kill_switch": True,
            "live_trading_enabled": False,
            "bind_address": "127.0.0.1",
            "dry_run": True,
            "paper_trading": True,
        },
    }
    assert validate_settings_observation(settings)["kill_switch"] is True
    open_settings = json.loads(json.dumps(settings))
    open_settings["safety"]["kill_switch"] = False
    with pytest.raises(ReleaseOperationError, match="kill_switch"):
        validate_settings_observation(open_settings)

    release = {
        "contract": "agent-v0.2-release-cli/v1",
        "decision": {
            "release_authorized": False,
            "public_write_authorized": False,
            "chat_write_ready": False,
            "ready": False,
            "blockers": ["release_missing"],
            "release_stamp_id": None,
            "public_cutover_id": None,
            "event_cursor": 0,
        },
    }
    assert validate_release_observation(release)["release_authorized"] is False
    release["decision"]["release_authorized"] = True
    with pytest.raises(ReleaseOperationError, match="release_authorized"):
        validate_release_observation(release)

    gateway = {
        "chat_write_ready": False,
        "read_status": "unavailable",
        "connected": False,
        "session_api_available": False,
        "blockers": ["gateway_unavailable"],
    }
    assert validate_gateway_observation(gateway)["chat_write_ready"] is False
    gateway["chat_write_ready"] = True
    with pytest.raises(ReleaseOperationError, match="chat write"):
        validate_gateway_observation(gateway)

    connector_cycle = {
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
    assert _validate_connector_cycle(connector_cycle)["mode"] == "reconcile_only"
    connector_cycle["provider_call_count"] = 1
    with pytest.raises(ReleaseOperationError, match="provider_call_count"):
        _validate_connector_cycle(connector_cycle)

    validate_launcher_source("#!/bin/sh\nexit 0\n")
    with pytest.raises(ReleaseOperationError, match="masking"):
        validate_launcher_source("probe ||" + " true\n")
    with pytest.raises(ReleaseOperationError, match="readiness"):
        validate_launcher_source("curl /api/" + "health\n")
