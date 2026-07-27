from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from quant_system.hermes.command_ledger import ExpiredLeaseReconciliation
from quant_system.hermes.connector_worker import (
    HermesConnectorWorker,
    PostgresCommandWakeupWaiter,
)

ROOT = Path(__file__).resolve().parents[1]


def _copy_runner(tmp_path: Path) -> tuple[Path, Path]:
    release_root = tmp_path / "release"
    scripts_dir = release_root / "scripts"
    scripts_dir.mkdir(parents=True)
    runner = scripts_dir / "run_agent_v02_connector.sh"
    shutil.copy2(ROOT / "scripts" / runner.name, runner)
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)
    (release_root / "src" / "quant_system").mkdir(parents=True)
    return release_root, runner


def _write_env(release_root: Path, contents: str) -> Path:
    env_file = release_root / "connector.env"
    env_file.write_text(contents, encoding="utf-8")
    env_file.chmod(0o600)
    return env_file


def _write_argv_python(path: Path, capture: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env bash\n"
        'printf "argv" >> "$TEST_ARGV_CAPTURE"\n'
        'printf "\\t%s" "$@" >> "$TEST_ARGV_CAPTURE"\n'
        'printf "\\n" >> "$TEST_ARGV_CAPTURE"\n'
        'if [[ "${1:-}" == "-" ]]; then\n'
        "  cat >/dev/null\n"
        "fi\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    assert capture.parent == path.parent
    return path


def _run_runner(
    *,
    release_root: Path,
    runner: Path,
    env_file: Path,
    python: Path,
    capture: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(runner)],
        cwd=release_root,
        env={
            **os.environ,
            "QS_AGENT_V02_CONNECTOR_ENV_FILE": str(env_file),
            "QS_AGENT_V02_CONNECTOR_PYTHON": str(python),
            "TEST_ARGV_CAPTURE": str(capture),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


class _ClaimExplodesLedger:
    def __init__(self) -> None:
        self.reconcile_calls = 0
        self.claim_calls = 0

    def reconcile_expired_leases(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> ExpiredLeaseReconciliation:
        self.reconcile_calls += 1
        return ExpiredLeaseReconciliation(requeued=(), outcome_unknown=())

    def claim_next_command(self, **_kwargs):
        self.claim_calls += 1
        raise AssertionError("reconcile_only must never claim")


class _DispatchExplodes:
    def __init__(self) -> None:
        self.calls = 0

    def submit_or_recover(self, _request):
        self.calls += 1
        raise AssertionError("reconcile_only must never dispatch")


class _NotifyThenTimeoutConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.waits: list[tuple[float, int, str]] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def notifies(self, *, timeout: float, stop_after: int):
        outcome = "notify" if not self.waits else "timeout"
        self.waits.append((timeout, stop_after, outcome))
        if outcome == "notify":
            yield SimpleNamespace(channel="quant_system_hermes_commands")
            return
        time.sleep(timeout)


class _ListenerDatabase:
    def __init__(self) -> None:
        self.connection = _NotifyThenTimeoutConnection()
        self.exits = 0

    @contextmanager
    def connect(self):
        try:
            yield self.connection
        finally:
            self.exits += 1


def test_configured_reconcile_only_is_the_exact_connector_mode_argv(
    tmp_path: Path,
) -> None:
    release_root, runner = _copy_runner(tmp_path)
    capture = tmp_path / "argv.log"
    python = _write_argv_python(tmp_path / "python", capture)
    env_file = _write_env(
        release_root,
        "QS_DATABASE_AUTO_MIGRATE=false\n"
        "QS_AGENT_V02_CONNECTOR_MODE=reconcile_only\n",
    )

    result = _run_runner(
        release_root=release_root,
        runner=runner,
        env_file=env_file,
        python=python,
        capture=capture,
    )

    assert result.returncode == 0, result.stderr
    invocations = [
        line.split("\t")[1:]
        for line in capture.read_text(encoding="utf-8").splitlines()
    ]
    assert invocations[-1] == [
        "-m",
        "quant_system.cli",
        "hermes",
        "connector-worker",
        "--mode",
        "reconcile_only",
        "--poll-interval-seconds",
        "5",
        "--reconcile-limit",
        "100",
        "--worker-id",
        "agent-v02-connector-1",
    ]


def test_invalid_configured_mode_fails_closed_before_python_starts(
    tmp_path: Path,
) -> None:
    release_root, runner = _copy_runner(tmp_path)
    capture = tmp_path / "argv.log"
    python = _write_argv_python(tmp_path / "python", capture)
    env_file = _write_env(
        release_root,
        "QS_DATABASE_AUTO_MIGRATE=false\n"
        "QS_AGENT_V02_CONNECTOR_MODE=unsafe_dispatch\n",
    )

    result = _run_runner(
        release_root=release_root,
        runner=runner,
        env_file=env_file,
        python=python,
        capture=capture,
    )

    assert result.returncode == 78
    assert result.stdout == ""
    assert "connector_config_error=connector_mode_invalid" in result.stderr
    assert not capture.exists()


def test_configured_supervised_dispatch_is_the_exact_connector_mode_argv(
    tmp_path: Path,
) -> None:
    release_root, runner = _copy_runner(tmp_path)
    capture = tmp_path / "argv.log"
    python = _write_argv_python(tmp_path / "python", capture)
    env_file = _write_env(
        release_root,
        "QS_DATABASE_AUTO_MIGRATE=false\n"
        "QS_AGENT_V02_CONNECTOR_MODE=supervised_dispatch\n",
    )

    result = _run_runner(
        release_root=release_root,
        runner=runner,
        env_file=env_file,
        python=python,
        capture=capture,
    )

    assert result.returncode == 0, result.stderr
    final_argv = capture.read_text(encoding="utf-8").splitlines()[-1].split("\t")[1:]
    assert final_argv[4:6] == ["--mode", "supervised_dispatch"]


def test_reconcile_only_cycle_never_claims_dispatches_or_uses_mutation_ports() -> None:
    ledger = _ClaimExplodesLedger()
    dispatch = _DispatchExplodes()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="reconcile_only",
        dispatch_adapter=dispatch,
        now=lambda: datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
    )

    result = worker.run_once()

    assert result.mode == "reconcile_only"
    assert result.claimed_count == 0
    assert result.hermes_mutation_count == 0
    assert result.provider_call_count == 0
    assert ledger.reconcile_calls == 1
    assert ledger.claim_calls == 0
    assert dispatch.calls == 0


def test_reconcile_only_listen_notify_then_periodic_timeout_both_scan() -> None:
    database = _ListenerDatabase()
    waiter = PostgresCommandWakeupWaiter(database=database)
    ledger = _ClaimExplodesLedger()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="reconcile_only",
        now=lambda: datetime(2026, 7, 27, 12, 5, tzinfo=UTC),
    )

    results = worker.run_loop(
        wakeup_waiter=waiter,
        poll_interval_seconds=0.05,
        max_cycles=3,
    )
    waiter.close()

    assert len(results) == 3
    assert all(result.mode == "reconcile_only" for result in results)
    assert all(result.claimed_count == 0 for result in results)
    assert all(result.hermes_mutation_count == 0 for result in results)
    assert all(result.provider_call_count == 0 for result in results)
    assert ledger.reconcile_calls == 3
    assert ledger.claim_calls == 0
    assert database.connection.statements == ["LISTEN quant_system_hermes_commands"]
    assert [item[2] for item in database.connection.waits] == ["notify", "timeout"]
    assert database.exits == 1


def test_operator_docs_require_reconcile_only_and_disclose_legacy_fallback() -> None:
    runbook = (
        ROOT / "docs" / "runbooks" / "agent-v0-2-connector-daemon.md"
    ).read_text(encoding="utf-8")
    scripts_readme = (ROOT / "scripts" / "README.md").read_text(encoding="utf-8")

    for document in (runbook, scripts_readme):
        assert "QS_AGENT_V02_CONNECTOR_MODE=reconcile_only" in document
        assert "absent-env fallback remains `supervised_dispatch`" in document
