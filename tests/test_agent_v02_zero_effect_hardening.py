from __future__ import annotations

import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from quant_system.ops import zero_effect
from tests.agent_v02_zero_effect_test_support import (
    materialize_hqa_repository,
    materialize_platform_repository,
    run_fixture_script,
)


def test_zero_effect_identity_includes_canonical_state_namespace(tmp_path: Path) -> None:
    first = tmp_path / "first-authority"
    second = tmp_path / "second-authority"

    first_identity = zero_effect.state_namespace_identity(first)
    second_identity = zero_effect.state_namespace_identity(second)

    assert first_identity["canonical_path"] == str(first.absolute())
    assert second_identity["canonical_path"] == str(second.absolute())
    assert first_identity["namespace_sha256"] != second_identity["namespace_sha256"]
    assert zero_effect.default_request_bytes(first_identity) != zero_effect.default_request_bytes(
        second_identity
    )


def test_zero_effect_has_exact_execution_authority_and_two_phase_seal() -> None:
    authority = getattr(zero_effect, "validate_platform_execution_authority", None)
    seal = getattr(zero_effect, "_write_two_phase_authoritative_seal", None)

    assert callable(authority)
    assert callable(seal)
    source = inspect.getsource(zero_effect._run_zero_effect_proof_locked)
    assert "authoritative-seal.json" in source
    assert source.count("_verify_postflight_runtime_identity(") >= 3


def test_zero_effect_route_child_has_os_and_audit_denials() -> None:
    child = getattr(zero_effect, "_execute_repository_block_in_child", None)
    sandbox = getattr(zero_effect, "_apply_route_os_sandbox", None)
    audit_guard = getattr(zero_effect, "_install_route_audit_guard", None)

    assert callable(child)
    assert callable(sandbox)
    assert callable(audit_guard)
    source = inspect.getsource(zero_effect)
    assert "deny network*" in source
    assert "deny process-exec" in source
    assert "deny process-fork" in source
    assert "socket.__new__" in source
    assert "subprocess.Popen" in source


def test_zero_effect_pre_header_hang_is_killed_reaped_and_not_retried(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    child_pids = tmp_path / "child-pids"
    script = "\n".join(
        (
            "import inspect",
            "import json",
            "import os",
            "import time",
            "from pathlib import Path",
            "from quant_system.ops import zero_effect",
            "from quant_system.ops.common import ReleaseOperationError",
            f"platform = Path({str(platform)!r})",
            f"hqa = Path({str(hqa)!r})",
            f"state = Path({str(state)!r})",
            f"child_pids = Path({str(child_pids)!r})",
            "def hang_before_header(**_kwargs):",
            "    with child_pids.open('a', encoding='utf-8') as handle:",
            "        handle.write(f'{os.getpid()}\\n')",
            "        handle.flush()",
            "        os.fsync(handle.fileno())",
            "    time.sleep(60)",
            "zero_effect._route_child_main = hang_before_header",
            "options = {}",
            "if 'route_child_timeout_seconds' in inspect.signature(",
            "    zero_effect.run_zero_effect_proof",
            ").parameters:",
            "    options['route_child_timeout_seconds'] = 0.2",
            "errors = []",
            "for _attempt in range(2):",
            "    try:",
            "        zero_effect.run_zero_effect_proof(",
            "            platform_root=platform,",
            "            hqa_root=hqa,",
            "            state_dir=state,",
            "            **options,",
            "        )",
            "    except ReleaseOperationError as exc:",
            "        errors.append(str(exc))",
            "    else:",
            "        raise SystemExit('hung route child unexpectedly passed')",
            "pid_values = child_pids.read_text(encoding='utf-8').splitlines()",
            "pid = int(pid_values[0])",
            "try:",
            "    waited, _status = os.waitpid(pid, os.WNOHANG)",
            "except ChildProcessError:",
            "    reaped = True",
            "else:",
            "    reaped = False",
            "claim = json.loads(",
            "    (state / 'journal' / 'in-progress-claim.json').read_text(encoding='utf-8')",
            ")",
            "print(json.dumps({",
            "    'errors': errors,",
            "    'child_pids': pid_values,",
            "    'reaped': reaped,",
            "    'claim_timeout': claim.get('route_child_timeout_seconds'),",
            "    'receipt': (state / 'journal' / 'authoritative-receipt.json').exists(),",
            "    'seal': (state / 'journal' / 'authoritative-seal.json').exists(),",
            "}, sort_keys=True))",
        )
    )

    completed = run_fixture_script(platform, script, timeout=3)

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["errors"] == [
        "route child timed out before result header",
        "in-progress claim has no authoritative seal; refusing route retry",
    ]
    assert len(document["child_pids"]) == 1
    assert document["reaped"] is True
    assert document["claim_timeout"] == 0.2
    assert document["receipt"] is False
    assert document["seal"] is False


def test_zero_effect_post_ack_hang_is_killed_reaped_and_not_retried(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    child_pids = tmp_path / "child-pids"
    script = "\n".join(
        (
            "import json",
            "import os",
            "import time",
            "from pathlib import Path",
            "from quant_system.ops import zero_effect",
            "from quant_system.ops.common import ReleaseOperationError, canonical_json_bytes",
            f"platform = Path({str(platform)!r})",
            f"hqa = Path({str(hqa)!r})",
            f"state = Path({str(state)!r})",
            f"child_pids = Path({str(child_pids)!r})",
            "def hang_after_ack(*, write_descriptor, ack_descriptor, **_kwargs):",
            "    with child_pids.open('a', encoding='utf-8') as handle:",
            "        handle.write(f'{os.getpid()}\\n')",
            "        handle.flush()",
            "        os.fsync(handle.fileno())",
            "    zero_effect._write_pipe_payload(",
            "        write_descriptor,",
            "        canonical_json_bytes({'status': 'passed', 'execution': {}}),",
            "    )",
            "    if os.read(ack_descriptor, 1) != b'1':",
            "        os._exit(75)",
            "    time.sleep(60)",
            "zero_effect._route_child_main = hang_after_ack",
            "errors = []",
            "for _attempt in range(2):",
            "    try:",
            "        zero_effect.run_zero_effect_proof(",
            "            platform_root=platform,",
            "            hqa_root=hqa,",
            "            state_dir=state,",
            "            route_child_timeout_seconds=0.2,",
            "        )",
            "    except ReleaseOperationError as exc:",
            "        errors.append(str(exc))",
            "    else:",
            "        raise SystemExit('post-ack hung route child unexpectedly passed')",
            "pid_values = child_pids.read_text(encoding='utf-8').splitlines()",
            "pid = int(pid_values[0])",
            "try:",
            "    waited, _status = os.waitpid(pid, os.WNOHANG)",
            "except ChildProcessError:",
            "    reaped = True",
            "else:",
            "    reaped = False",
            "claim = json.loads(",
            "    (state / 'journal' / 'in-progress-claim.json').read_text(encoding='utf-8')",
            ")",
            "print(json.dumps({",
            "    'errors': errors,",
            "    'child_pids': pid_values,",
            "    'reaped': reaped,",
            "    'claim_timeout': claim.get('route_child_timeout_seconds'),",
            "    'receipt': (state / 'journal' / 'authoritative-receipt.json').exists(),",
            "    'seal': (state / 'journal' / 'authoritative-seal.json').exists(),",
            "}, sort_keys=True))",
        )
    )

    completed = run_fixture_script(platform, script, timeout=3)

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["errors"] == [
        "route child timed out after acknowledgement",
        "in-progress claim has no authoritative seal; refusing route retry",
    ]
    assert len(document["child_pids"]) == 1
    assert document["reaped"] is True
    assert document["claim_timeout"] == 0.2
    assert document["receipt"] is False
    assert document["seal"] is False


def test_zero_effect_cli_timeout_is_explicit_auditable_and_failed_closed(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    output = tmp_path / "output"
    child_pid_path = tmp_path / "child-pid"
    script = "\n".join(
        (
            "import contextlib",
            "import io",
            "import json",
            "import os",
            "import time",
            "from pathlib import Path",
            "from quant_system.ops import release_ops, zero_effect",
            f"platform = Path({str(platform)!r})",
            f"hqa = Path({str(hqa)!r})",
            f"state = Path({str(state)!r})",
            f"output = Path({str(output)!r})",
            f"child_pid_path = Path({str(child_pid_path)!r})",
            "default_args = release_ops._parser().parse_args([",
            "    'zero-effect',",
            "    '--repository-root', str(platform),",
            "    '--output-dir', str(output),",
            "    '--hqa-root', str(hqa),",
            "    '--state-dir', str(state),",
            "])",
            "def hang_before_header(**_kwargs):",
            "    child_pid_path.write_text(str(os.getpid()), encoding='utf-8')",
            "    time.sleep(60)",
            "zero_effect._route_child_main = hang_before_header",
            "captured = io.StringIO()",
            "with contextlib.redirect_stderr(captured):",
            "    exit_code = release_ops.main([",
            "        'zero-effect',",
            "        '--repository-root', str(platform),",
            "        '--output-dir', str(output),",
            "        '--hqa-root', str(hqa),",
            "        '--state-dir', str(state),",
            "        '--route-child-timeout-seconds', '0.2',",
            "    ])",
            "pid = int(child_pid_path.read_text(encoding='utf-8'))",
            "try:",
            "    waited, _status = os.waitpid(pid, os.WNOHANG)",
            "except ChildProcessError:",
            "    reaped = True",
            "else:",
            "    reaped = False",
            "claim = json.loads(",
            "    (state / 'journal' / 'in-progress-claim.json').read_text(encoding='utf-8')",
            ")",
            "error = json.loads(captured.getvalue())",
            "print(json.dumps({",
            "    'default_timeout': default_args.route_child_timeout_seconds,",
            "    'exit_code': exit_code,",
            "    'error': error,",
            "    'claim_timeout': claim.get('route_child_timeout_seconds'),",
            "    'reaped': reaped,",
            "    'command_receipt': (output / 'zero-effect-proof.json').exists(),",
            "    'receipt': (state / 'journal' / 'authoritative-receipt.json').exists(),",
            "    'seal': (state / 'journal' / 'authoritative-seal.json').exists(),",
            "}, sort_keys=True))",
        )
    )

    completed = run_fixture_script(platform, script, timeout=3)

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["default_timeout"] == zero_effect.DEFAULT_ROUTE_CHILD_TIMEOUT_SECONDS
    assert document["exit_code"] == 78
    assert document["error"] == {
        "schema_version": "agent-v0.2.2-release-operation-error.v1",
        "status": "failed_closed",
        "command": "zero-effect",
        "error": "route child timed out before result header",
    }
    assert document["claim_timeout"] == 0.2
    assert document["reaped"] is True
    assert document["command_receipt"] is False
    assert document["receipt"] is False
    assert document["seal"] is False


def test_zero_effect_wrapper_changes_to_exact_release_root() -> None:
    wrapper = (
        Path(__file__).resolve().parents[1] / "scripts" / "verify_agent_v02_zero_effect.sh"
    ).read_text(encoding="utf-8")

    assert 'cd "$ROOT"' in wrapper
    assert "||" + " true" not in wrapper
    assert "/api/" + "health" not in wrapper


def test_zero_effect_real_route_runs_in_confined_child_and_replays(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from quant_system.ops.zero_effect import run_zero_effect_proof",
            f"platform = Path({str(platform)!r})",
            f"hqa = Path({str(hqa)!r})",
            f"state = Path({str(state)!r})",
            "first = run_zero_effect_proof(",
            "    platform_root=platform, hqa_root=hqa, state_dir=state",
            ")",
            "second = run_zero_effect_proof(",
            "    platform_root=platform, hqa_root=hqa, state_dir=state",
            ")",
            "print(json.dumps({'first': first, 'second': second}, sort_keys=True))",
        )
    )

    completed = run_fixture_script(
        platform,
        script,
        extra_env={
            "OPENAI_API_KEY": "route-must-not-inherit",
            "QS_BROKER_PASSWORD": "route-must-not-inherit",
            "QS_DATABASE_URL": "postgresql://route-must-not-inherit",
            "QS_FUTU_HOST": "route-must-not-inherit",
        },
    )

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    first = document["first"]
    second = document["second"]
    assert first["first_submission"]["route_invocations_this_call"] == 1
    assert second["first_submission"]["route_invocations_this_call"] == 0
    assert first["all_effect_counters_zero"] is True
    assert first["safety_unchanged"] is True
    guard = first["first_submission"]["receipt"]["execution_observation"]["route_guard"]
    assert guard["os_self_test"]["network_connect_denied"] is True
    assert guard["os_self_test"]["subprocess_denied"] is True
    assert guard["audit_self_test"]["threaded_c_socket_denied"] is True
    assert guard["audit_self_test"]["subprocess_denied"] is True
    assert guard["environment"]["provider_and_trading_credentials_inherited"] is False
    assert set(guard["environment"]["credential_like_names_removed"]) >= {
        "OPENAI_API_KEY",
        "QS_BROKER_PASSWORD",
        "QS_DATABASE_URL",
        "QS_FUTU_HOST",
    }
    assert guard["environment"]["credential_like_names_present"] == []
    release = first["fresh_release_status_observations_this_call"]
    assert release["preflight"]["facts"]["release_authorized"] is False
    assert release["postflight"]["facts"]["public_write_authorized"] is False


def test_zero_effect_cross_state_directories_have_distinct_idempotency_identity(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    first_state = tmp_path / "first-authority"
    second_state = tmp_path / "second-authority"
    script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from quant_system.ops.zero_effect import run_zero_effect_proof",
            f"platform = Path({str(platform)!r})",
            f"hqa = Path({str(hqa)!r})",
            "results = []",
            f"for raw in ({str(first_state)!r}, {str(second_state)!r}):",
            "    results.append(run_zero_effect_proof(",
            "        platform_root=platform, hqa_root=hqa, state_dir=Path(raw)",
            "    ))",
            "print(json.dumps(results, sort_keys=True))",
        )
    )

    completed = run_fixture_script(platform, script)

    assert completed.returncode == 0, completed.stderr
    first, second = json.loads(completed.stdout)
    assert first["first_submission"]["route_invocations_this_call"] == 1
    assert second["first_submission"]["route_invocations_this_call"] == 1
    assert (
        first["state_namespace"]["namespace_sha256"]
        != second["state_namespace"]["namespace_sha256"]
    )
    assert (
        first["idempotency_identity"]["identity_sha256"]
        != second["idempotency_identity"]["identity_sha256"]
    )
    assert first["request_sha256"] != second["request_sha256"]


def test_zero_effect_rejects_foreign_checkout_before_claim(tmp_path: Path) -> None:
    imported = materialize_platform_repository(tmp_path / "imported-platform")
    foreign = materialize_platform_repository(tmp_path / "foreign-platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from quant_system.ops.common import ReleaseOperationError",
            "from quant_system.ops.zero_effect import run_zero_effect_proof",
            "try:",
            "    run_zero_effect_proof(",
            f"        platform_root=Path({str(foreign)!r}),",
            f"        hqa_root=Path({str(hqa)!r}),",
            f"        state_dir=Path({str(state)!r}),",
            "    )",
            "except ReleaseOperationError as exc:",
            "    print(json.dumps({'error': str(exc)}, sort_keys=True))",
            "else:",
            "    raise SystemExit('foreign checkout unexpectedly passed')",
        )
    )

    completed = run_fixture_script(imported, script)

    assert completed.returncode == 0, completed.stderr
    assert "outside requested root" in json.loads(completed.stdout)["error"]
    assert not (state / "journal" / "in-progress-claim.json").exists()


def test_zero_effect_rejects_substituted_route_callable_before_claim(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from fastapi import HTTPException",
            "from quant_system.api.routes import paper as paper_routes",
            "from quant_system.ops.common import ReleaseOperationError",
            "from quant_system.ops.zero_effect import run_zero_effect_proof",
            "def substituted(request, api_runs_dir, settings):",
            "    raise HTTPException(",
            "        status_code=409,",
            "        detail={'code': 'replay_kill_switch_enabled'},",
            "    )",
            "paper_routes.run_paper = substituted",
            "try:",
            "    run_zero_effect_proof(",
            f"        platform_root=Path({str(platform)!r}),",
            f"        hqa_root=Path({str(hqa)!r}),",
            f"        state_dir=Path({str(state)!r}),",
            "    )",
            "except ReleaseOperationError as exc:",
            "    print(json.dumps({'error': str(exc)}, sort_keys=True))",
            "else:",
            "    raise SystemExit('substituted callable unexpectedly passed')",
        )
    )

    completed = run_fixture_script(platform, script)

    assert completed.returncode == 0, completed.stderr
    assert "callable" in json.loads(completed.stdout)["error"]
    assert not (state / "journal" / "in-progress-claim.json").exists()


def test_zero_effect_rejects_noncanonical_cli_wrapper_before_claim(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    cli = platform / ".venv" / "bin" / "quant-system"
    cli.write_text(cli.read_text(encoding="utf-8") + "# substituted\n", encoding="utf-8")
    script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from quant_system.ops.common import ReleaseOperationError",
            "from quant_system.ops.zero_effect import run_zero_effect_proof",
            "try:",
            "    run_zero_effect_proof(",
            f"        platform_root=Path({str(platform)!r}),",
            f"        hqa_root=Path({str(hqa)!r}),",
            f"        state_dir=Path({str(state)!r}),",
            "    )",
            "except ReleaseOperationError as exc:",
            "    print(json.dumps({'error': str(exc)}, sort_keys=True))",
            "else:",
            "    raise SystemExit('substituted CLI unexpectedly passed')",
        )
    )

    completed = run_fixture_script(platform, script)

    assert completed.returncode == 0, completed.stderr
    assert "wrapper bytes are not canonical" in json.loads(completed.stdout)["error"]
    assert not (state / "journal" / "in-progress-claim.json").exists()


def test_zero_effect_real_sigkill_after_route_never_retries(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    script = "\n".join(
        (
            "import json",
            "import os",
            "import signal",
            "from pathlib import Path",
            "from quant_system.ops import zero_effect",
            "from quant_system.ops.common import ReleaseOperationError",
            f"platform = Path({str(platform)!r})",
            f"hqa = Path({str(hqa)!r})",
            f"state = Path({str(state)!r})",
            "calls = 0",
            "real_execute = zero_effect._execute_repository_block_in_child",
            "real_ack = zero_effect._acknowledge_route_child",
            "def counted_execute(**kwargs):",
            "    global calls",
            "    calls += 1",
            "    return real_execute(**kwargs)",
            "def kill_after_real_route(process_id, descriptor):",
            "    del descriptor",
            "    os.kill(process_id, signal.SIGKILL)",
            "zero_effect._execute_repository_block_in_child = counted_execute",
            "zero_effect._acknowledge_route_child = kill_after_real_route",
            "errors = []",
            "try:",
            "    zero_effect.run_zero_effect_proof(",
            "        platform_root=platform, hqa_root=hqa, state_dir=state",
            "    )",
            "except ReleaseOperationError as exc:",
            "    errors.append(str(exc))",
            "zero_effect._acknowledge_route_child = real_ack",
            "first_calls = calls",
            "try:",
            "    zero_effect.run_zero_effect_proof(",
            "        platform_root=platform, hqa_root=hqa, state_dir=state",
            "    )",
            "except ReleaseOperationError as exc:",
            "    errors.append(str(exc))",
            "print(json.dumps({",
            "    'errors': errors,",
            "    'first_calls': first_calls,",
            "    'retry_calls': calls - first_calls,",
            "    'claim': (state / 'journal' / 'in-progress-claim.json').is_file(),",
            "    'receipt': (state / 'journal' / 'authoritative-receipt.json').exists(),",
            "    'seal': (state / 'journal' / 'authoritative-seal.json').exists(),",
            "}, sort_keys=True))",
        )
    )

    completed = run_fixture_script(platform, script)

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["first_calls"] == 1
    assert document["retry_calls"] == 0
    assert "signal" in document["errors"][0]
    assert "no authoritative seal" in document["errors"][1]
    assert document["claim"] is True
    assert document["receipt"] is False
    assert document["seal"] is False


def test_zero_effect_receipt_fsync_mutation_prevents_authoritative_seal(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    tracked = platform / "runtime.py"
    script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from quant_system.ops import zero_effect",
            "from quant_system.ops.common import ReleaseOperationError",
            f"platform = Path({str(platform)!r})",
            f"hqa = Path({str(hqa)!r})",
            f"state = Path({str(state)!r})",
            f"tracked = Path({str(tracked)!r})",
            "real_fsync = zero_effect._fsync_directory",
            "mutations = 0",
            "def mutate_at_receipt_fsync(path):",
            "    global mutations",
            "    real_fsync(path)",
            "    receipt = path / 'authoritative-receipt.json'",
            "    seal = path / 'authoritative-seal.json'",
            "    if receipt.exists() and not seal.exists() and mutations == 0:",
            "        tracked.write_text(tracked.read_text() + '# receipt race\\n')",
            "        mutations += 1",
            "zero_effect._fsync_directory = mutate_at_receipt_fsync",
            "try:",
            "    zero_effect.run_zero_effect_proof(",
            "        platform_root=platform, hqa_root=hqa, state_dir=state",
            "    )",
            "except ReleaseOperationError as exc:",
            "    error = str(exc)",
            "else:",
            "    raise SystemExit('receipt-write mutation unexpectedly passed')",
            "print(json.dumps({",
            "    'error': error,",
            "    'mutations': mutations,",
            "    'receipt': (state / 'journal' / 'authoritative-receipt.json').is_file(),",
            "    'seal': (state / 'journal' / 'authoritative-seal.json').exists(),",
            "}, sort_keys=True))",
        )
    )

    completed = run_fixture_script(platform, script)

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["mutations"] == 1
    assert "postflight Platform repository identity is not clean" in document["error"]
    assert document["receipt"] is True
    assert document["seal"] is False


def test_zero_effect_concurrent_processes_execute_real_route_exactly_once(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from quant_system.ops.zero_effect import run_zero_effect_proof",
            "result = run_zero_effect_proof(",
            f"    platform_root=Path({str(platform)!r}),",
            f"    hqa_root=Path({str(hqa)!r}),",
            f"    state_dir=Path({str(state)!r}),",
            ")",
            "print(json.dumps(result, sort_keys=True))",
        )
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        completed = list(
            executor.map(
                lambda _index: run_fixture_script(platform, script, timeout=45),
                range(4),
            )
        )

    for item in completed:
        assert item.returncode == 0, item.stderr
    documents = [json.loads(item.stdout) for item in completed]
    invocations = sorted(
        item["first_submission"]["route_invocations_this_call"] for item in documents
    )
    assert invocations == [0, 0, 0, 1]
    receipt_digests = {
        item["first_submission"]["receipt"]["authoritative_receipt_sha256"] for item in documents
    }
    seal_digests = {item["first_submission"]["seal"]["seal_sha256"] for item in documents}
    assert len(receipt_digests) == 1
    assert len(seal_digests) == 1


def assert_zero_effect_postflight_drift_fails(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    platform_path = tmp_path / "platform"
    targets: dict[str, Path | str] = {
        "platform": platform_path / "runtime.py",
        "hqa": hqa / "hqa" / "__init__.py",
        "platform_runtime": "__SELF__",
    }
    platform = materialize_platform_repository(
        platform_path,
        mutate_on_postflight=targets[drift_kind],
    )
    state = tmp_path / "authority"
    script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from quant_system.ops.common import ReleaseOperationError",
            "from quant_system.ops.zero_effect import run_zero_effect_proof",
            "try:",
            "    run_zero_effect_proof(",
            f"        platform_root=Path({str(platform)!r}),",
            f"        hqa_root=Path({str(hqa)!r}),",
            f"        state_dir=Path({str(state)!r}),",
            "    )",
            "except ReleaseOperationError as exc:",
            "    error = str(exc)",
            "else:",
            "    raise SystemExit('postflight drift unexpectedly passed')",
            "print(json.dumps({",
            "    'error': error,",
            "    'claim': (Path(" + repr(str(state)) + ") / 'journal' / "
            "        'in-progress-claim.json').is_file(),",
            "    'receipt': (Path(" + repr(str(state)) + ") / 'journal' / "
            "        'authoritative-receipt.json').exists(),",
            "    'seal': (Path(" + repr(str(state)) + ") / 'journal' / "
            "        'authoritative-seal.json').exists(),",
            "}, sort_keys=True))",
        )
    )

    completed = run_fixture_script(platform, script)

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert "postflight" in document["error"]
    assert document["claim"] is True
    assert document["receipt"] is False
    assert document["seal"] is False


def test_zero_effect_postflight_drift_fails_before_receipt(tmp_path: Path) -> None:
    for drift_kind in ("platform", "hqa", "platform_runtime"):
        child_root = tmp_path / drift_kind
        child_root.mkdir()
        assert_zero_effect_postflight_drift_fails(child_root, drift_kind)


def test_zero_effect_changed_same_identity_request_fails_before_observation(
    tmp_path: Path,
) -> None:
    platform = materialize_platform_repository(tmp_path / "platform")
    hqa = materialize_hqa_repository(tmp_path / "hqa")
    state = tmp_path / "authority"
    seed_script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from quant_system.ops.zero_effect import run_zero_effect_proof",
            "result = run_zero_effect_proof(",
            f"    platform_root=Path({str(platform)!r}),",
            f"    hqa_root=Path({str(hqa)!r}),",
            f"    state_dir=Path({str(state)!r}),",
            ")",
            "print(json.dumps(result, sort_keys=True))",
        )
    )
    seeded = run_fixture_script(platform, seed_script)
    assert seeded.returncode == 0, seeded.stderr
    request_path = state / "journal" / "request.json"
    changed = json.loads(request_path.read_bytes())
    changed["paper_run_request"]["initial_cash"] = 200_000.0
    request_path.write_bytes(
        (
            json.dumps(
                changed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    status_counter = platform / ".venv" / "bin" / "status-call-count"
    calls_before = status_counter.read_text(encoding="utf-8")
    replay_script = "\n".join(
        (
            "import json",
            "from pathlib import Path",
            "from quant_system.ops.common import ReleaseOperationError",
            "from quant_system.ops.zero_effect import run_zero_effect_proof",
            "try:",
            "    run_zero_effect_proof(",
            f"        platform_root=Path({str(platform)!r}),",
            f"        hqa_root=Path({str(hqa)!r}),",
            f"        state_dir=Path({str(state)!r}),",
            "    )",
            "except ReleaseOperationError as exc:",
            "    print(json.dumps({'error': str(exc)}, sort_keys=True))",
            "else:",
            "    raise SystemExit('changed request unexpectedly passed')",
        )
    )

    replayed = run_fixture_script(platform, replay_script)

    assert replayed.returncode == 0, replayed.stderr
    assert "different request bytes" in json.loads(replayed.stdout)["error"]
    assert status_counter.read_text(encoding="utf-8") == calls_before
