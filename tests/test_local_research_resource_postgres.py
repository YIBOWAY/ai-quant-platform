from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from quant_system.config.settings import DatabaseSettings, DataSettings, Settings
from quant_system.d34.research_request import (
    LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
    LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
    build_owner_request_input,
    digest_document,
)
from quant_system.d34.worker import D34CycleWorker, D34WorkerConfig
from quant_system.execution.account_repository_factory import build_paper_account_repository
from quant_system.execution.assistant_remote import (
    project_book,
    project_terminal_research_results,
)
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.hermes.d34_job_authority import EnqueueJobCommand, PostgresJobAuthority
from quant_system.hermes.d34_registry_authority import PostgresRegistryAuthority
from quant_system.options.seller_score import is_us_market_session
from quant_system.storage import database as db
from tests.current_capital_fixtures import d34_candidate_kwargs
from tests.postgres_reset import isolated_test_database_url
from tests.test_d34_cycle_worker import Docker, _platform_replay_fixture
from tests.test_hermes_v4r_security import (
    _drop_test_login,
    _provision_test_login,
    _url_as,
)

pytestmark = pytest.mark.pg

_MIGRATION = "034_local_research_resource_envelope.sql"


def _base_database_url() -> str:
    value = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get("QS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    return value


def _init_hermes_checkout(path: Path) -> Path:
    path.mkdir(parents=True, mode=0o700)
    subprocess.run(["git", "-C", str(path), "init", "-q", "-b", "main"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Research Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "config",
            "user.email",
            "research-test@example.invalid",
        ],
        check=True,
    )
    (path / "hermes.py").write_text("VERSION = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "hermes.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "fixture"], check=True)
    hermes = path / ".venv" / "bin" / "hermes"
    hermes.parent.mkdir(parents=True, mode=0o700)
    hermes.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    hermes.chmod(0o700)
    return path


def _install_physical_wrapper(
    tmp_path: Path,
    *,
    hqa_root: Path,
    platform_facade: Path,
) -> Path:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    hermes_home = home / ".hermes"
    helper = hermes_home / "bin" / "hqa-intent-payload-crypto"
    helper.parent.mkdir(parents=True, mode=0o700)
    helper.write_text("#!/bin/bash\nexit 64\n", encoding="utf-8")
    helper.chmod(0o700)
    source = _init_hermes_checkout(tmp_path / "hermes-source")
    env = {
        **os.environ,
        "HOME": str(home),
        "HERMES_HOME": str(hermes_home),
        "HQA_AIQP_DIR": str(platform_facade),
        "HQA_HERMES_SOURCE_DIR": str(source),
        "HQA_SKIP_NATIVE_BUILD": "1",
    }
    installed = subprocess.run(
        ["bash", str(hqa_root / "scripts" / "install.sh")],
        cwd=hqa_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    wrapper = hermes_home / "scripts" / "hqa-paper-research.sh"
    assert wrapper.is_file() and os.access(wrapper, os.X_OK)
    return wrapper


class _FutuBoundary:
    provider_name = "futu"

    def __init__(self) -> None:
        self.calls = 0

    def fetch_ohlcv(self, symbols, *, start, end, interval):
        self.calls += 1
        assert interval == "1d"
        sessions = [
            value
            for value in pd.date_range(start, end, tz="UTC")
            if is_us_market_session(value.date())
        ]
        assert len(sessions) >= 240
        observed_at = pd.Timestamp(end, tz="UTC") + pd.Timedelta(hours=23)
        rows: list[dict[str, object]] = []
        for offset, symbol in enumerate(symbols):
            for day, timestamp in enumerate(sessions, start=1):
                close = 100.0 + offset + day / 10
                rows.append(
                    {
                        "symbol": symbol,
                        "timestamp": timestamp,
                        "open": close - 0.5,
                        "high": close + 1.0,
                        "low": close - 1.0,
                        "close": close,
                        "volume": 1_000_000,
                        "provider": "futu",
                        "interval": "1d",
                        "event_ts": timestamp,
                        "knowledge_ts": observed_at,
                        "price_adjustment": "qfq",
                    }
                )
        return pd.DataFrame(rows)


class _AcceptedDocker(Docker):
    """Artificial engine boundary with original-file evidence, never market alpha."""

    def run(self, *, job_id, command, timeout_seconds=None):
        receipt = super().run(
            job_id=job_id,
            command=command,
            timeout_seconds=timeout_seconds,
        )
        if command[0] != "research":
            return receipt
        output = dict(receipt.output)
        raw_path = self.workspace / str(output["qlib_receipt_path"]).removeprefix("/workspace/d34/")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        raw.pop("receipt_digest")
        request_path = self.workspace / command[command.index("--request") + 1].removeprefix(
            "/workspace/d34/"
        )
        request = json.loads(request_path.read_text(encoding="utf-8"))
        config = {
            "contract": "hqa.d34_qlib_config/v1",
            "expression": request["formula"],
            "universe": request["universe"],
            "start_time": request["calendar"][0],
            "end_time": request["calendar"][-1],
            "execution_timing": "next_open",
            "exchange": {
                "open_cost": 0.0006,
                "close_cost": 0.0006,
                "min_cost": 0,
                "deal_price": "$open",
            },
        }
        count = len(raw["return_dates"])
        daily_returns = [
            0.0,
            *[0.006 if index % 2 else -0.001 for index in range(1, count)],
        ]
        terminal_nav = 1.0
        for value in daily_returns:
            terminal_nav *= 1.0 + value
        raw.update(
            {
                "daily_returns": daily_returns,
                "terminal_nav": terminal_nav,
                "snapshot_id": request["snapshot_id"],
                "selected_experiment": "iteration-01-experiment-01",
                "qlib_config": config,
                "qlib_config_digest": digest_document(config),
                "metrics": {"turnover": 0.2},
            }
        )
        raw_digest = digest_document(raw)
        raw_path.write_text(
            json.dumps(
                {**raw, "receipt_digest": raw_digest},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        output["qlib_receipt_digest"] = raw_digest
        # Keep the worker's actual selected trial, observation, batch, raw
        # receipt and host ledger on the same artificial input. The old fixture
        # changed only the raw return series and left an unrelated trial behind.
        batch_path = self.workspace / str(output["experiment_trials_path"]).removeprefix(
            "/workspace/d34/"
        )
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        batch.pop("receipt_digest")
        assert batch["experiment_count"] == 1  # One supplied same-chat formula.
        selected = batch["experiments"][0]
        proposal = {"operator": "momentum", "experiment_id": selected["experiment_id"]}
        assert selected["proposal_digest"] == digest_document(proposal)
        evaluation = {
            "schema": "hqa.d34_experiment_evaluation/v1",
            "return_definition": "net_total_return",
            "frequency": "daily",
            "initial_cash": request["initial_cash"],
            "request_digest": output["request_digest"],
            "snapshot_id": request["snapshot_id"],
            "snapshot_digest": request["snapshot_digest"],
            "snapshot_source": request["snapshot_source"],
            "universe_digest": digest_document(request["universe"]),
            "calendar_digest": digest_document(request["calendar"]),
            "qlib_config": config,
            "qlib_config_digest": digest_document(config),
            "implementation": {
                "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "runner_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
        }
        observation = {
            "experiment_id": selected["experiment_id"],
            "status": "succeeded",
            "proposal": proposal,
            "returns_digest": digest_document(
                {"values": daily_returns, "dates": raw["return_dates"]}
            ),
            "return_dates_digest": digest_document(raw["return_dates"]),
            "evaluation_contract": evaluation,
        }
        observation_path = (
            raw_path.parent / "experiments" / selected["experiment_id"] / "receipt.json"
        )
        observation_path.parent.mkdir(parents=True)
        observation_path.write_text(json.dumps(observation, sort_keys=True), encoding="utf-8")
        selected.update(
            daily_returns=daily_returns,
            evaluation_contract=evaluation,
            experiment_receipt_digest=hashlib.sha256(observation_path.read_bytes()).hexdigest(),
        )
        batch_digest = digest_document(batch)
        batch_path.write_text(json.dumps({**batch, "receipt_digest": batch_digest}, sort_keys=True))
        attempt_path = (
            batch_path.parent
            / f"experiment-trial-attempts-{output['request_digest'][:32]}"
            / f"{selected['experiment_id']}.json"
        )
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        attempt.pop("receipt_digest")
        attempt.update(
            {
                key: selected[key]
                for key in ("daily_returns", "experiment_receipt_digest", "evaluation_contract")
            }
        )
        attempt_path.write_text(
            json.dumps({**attempt, "receipt_digest": digest_document(attempt)}, sort_keys=True)
        )
        output.update(
            run_id=request["run_id"],
            selected_experiment=selected["experiment_id"],
            qlib_receipt_file=raw_path.name,
            qlib_receipt_file_digest=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            qlib_config_digest=digest_document(config),
            experiment_trials_digest=batch_digest,
            experiment_trials_file_digest=hashlib.sha256(batch_path.read_bytes()).hexdigest(),
        )
        (raw_path.parent / "research_receipt.json").write_text(json.dumps(output, sort_keys=True))
        return receipt.__class__(
            contract=receipt.contract,
            job_id=receipt.job_id,
            image_ref=receipt.image_ref,
            image_digest=receipt.image_digest,
            command=receipt.command,
            output=output,
            receipt_digest=digest_document(output),
        )


def _run_wrapper(
    wrapper: Path,
    *,
    command_id: str,
    hermes_run_id: str,
) -> dict[str, object]:
    result = subprocess.run(
        [str(wrapper), "chat-research"],
        input=json.dumps(
            {
                "contract": "hqa.chat_research_material/v1",
                "status": "material_ready",
                "note": "Research the supplied twenty-day reversal formula",
                "formula": "Ref($close, 20) / $close - 1",
                "universe": ["SPY", "QQQ", "IWM", "DIA"],
                "missing_fields": [],
            }
        ),
        env={
            **os.environ,
            "HERMES_PLATFORM_COMMAND_ID": command_id,
            "HERMES_PLATFORM_SESSION_ID": "platform-session-pg-physical",
            "HERMES_PLATFORM_MANAGED_SESSION_ID": "hermes-session-pg-physical",
            "HERMES_PLATFORM_RUN_ID": hermes_run_id,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _postgres_uri(conninfo: str) -> str:
    values = conninfo_to_dict(conninfo)
    return (
        "postgresql://"
        f"{quote(values['user'], safe='')}:{quote(values['password'], safe='')}"
        f"@{values['host']}:{values['port']}/{quote(values['dbname'], safe='')}"
    )


def test_migration_034_and_physical_chat_wrapper_converge_to_one_candidate(
    tmp_path: Path,
) -> None:
    platform_root = Path(__file__).resolve().parent.parent
    configured_hqa = os.environ.get("QS_TEST_HQA_ROOT")
    hqa_root = (
        Path(configured_hqa).resolve()
        if configured_hqa
        else platform_root.parent / "Hermes-quant-agent"
    )
    assert (hqa_root / "hqa" / "chat_research_cli.py").is_file(), (
        "Set QS_TEST_HQA_ROOT to the explicit HQA source checkout when testing a Platform worktree"
    )
    sql_root = platform_root / "scripts" / "sql"
    predecessors = tuple(
        path.name for path in sorted(sql_root.glob("*.sql")) if path.name < _MIGRATION
    )

    with isolated_test_database_url(_base_database_url(), purpose="rsch034") as url:
        database = db.Database(url, connect_timeout=1)
        db.run_migrations(database, only=predecessors)
        db.run_migrations(database, only=(_MIGRATION,))
        db.run_migrations(database, only=(_MIGRATION,))

        with psycopg.connect(url) as connection:
            envelope = connection.execute(
                """
                SELECT resource_envelope_id, policy_digest, policy_document
                FROM quant_system.d34_research_resource_envelopes
                """
            ).fetchall()
            constraints = connection.execute(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname IN (
                    'ck_d34_job_single_resource_authority',
                    'ck_d34_budget_event_single_resource_authority',
                    'ck_d34_policy_single_resource_authority',
                    'ck_d34_receipt_single_resource_authority',
                    'ck_d34_artifact_single_resource_authority'
                )
                """
            ).fetchone()
            indexes = connection.execute(
                """
                SELECT count(*)
                FROM pg_indexes
                WHERE schemaname = 'quant_system'
                  AND indexname IN (
                    'uq_d34_local_research_job_key',
                    'uq_d34_one_active_local_research_job'
                  )
                """
            ).fetchone()
        assert len(envelope) == 1
        assert envelope[0][0] == "local-paper-research-v1"
        assert envelope[0][1] == "f539564775cd6f0c51fbd8478697265c1f4df86987513dad5e7a842b92191270"
        assert envelope[0][2]["timeout_seconds"] == 7200
        assert constraints == (5,)
        assert indexes == (2,)

        data_root = tmp_path / "platform-data"
        data_root.mkdir()
        facade = tmp_path / "platform-facade"
        (facade / "data" / "_runtime").mkdir(parents=True)
        (facade / "src").symlink_to(platform_root / "src", target_is_directory=True)
        runtime_env = facade / "data" / "_runtime" / "agent-v0.2-backend.env"
        runtime_env.write_text(
            "QS_DATABASE_ENABLED=true\n"
            f"QS_DATABASE_URL={_postgres_uri(url)}\n"
            "QS_DATABASE_AUTO_MIGRATE=false\n"
            f"QS_DATA_DIR={data_root}\n"
            f"QS_QUANT_BACKEND_PYTHON={Path(sys.executable).absolute()}\n",
            encoding="utf-8",
        )
        runtime_env.chmod(0o600)
        wrapper = _install_physical_wrapper(
            tmp_path,
            hqa_root=hqa_root,
            platform_facade=facade,
        )

        queued = _run_wrapper(
            wrapper,
            command_id="command-pg-physical-1",
            hermes_run_id="hermes-run-pg-physical-1",
        )
        assert queued["status"] == "queued"

        settings = Settings(
            data=DataSettings(
                data_dir=data_root,
                parquet_dir=data_root / "parquet",
                duckdb_path=data_root / "quant_system.duckdb",
                reports_dir=data_root / "reports",
            ),
            database=DatabaseSettings(
                enabled=True,
                url=url,
                auto_migrate=False,
                connect_timeout_seconds=1,
            ),
        )
        db.reset_database_cache()
        jobs = PostgresJobAuthority(settings)
        registry = PostgresRegistryAuthority(settings)
        queued_jobs = jobs.list(workspace_id="default", limit=100, state=None)
        assert len(queued_jobs) == 1
        assert queued_jobs[0].state == "queued"

        workspace = data_root / "_runtime" / "d34"
        cache = workspace / "cache"
        workspace.mkdir(parents=True)
        cache.mkdir()
        docker = _AcceptedDocker(workspace)
        futu = _FutuBoundary()
        replay_calls: list[str] = []

        def replay(**kwargs):
            replay_calls.append(kwargs["job_id"])
            qlib = kwargs.pop("qlib_receipt")
            return _platform_replay_fixture(
                output_root=kwargs["output_root"],
                qlib=qlib,
                job_id=kwargs["job_id"],
                run_id=kwargs["run_id"],
            )

        worker = D34CycleWorker(
            config=D34WorkerConfig(
                workspace_root=workspace,
                data_root=data_root,
                platform_root=platform_root,
                hqa_root=hqa_root,
                cache_root=cache,
                workspace_id="default",
                worker_id="pg-physical-worker",
            ),
            jobs=jobs,
            registry=registry,
            docker_runtime=docker,
            futu_provider=futu,
            platform_replay=replay,
            now=lambda: datetime(2026, 8, 11, 22, 30, tzinfo=UTC),
        )
        terminal = worker.run_once()
        assert terminal.status == "candidate_ready"
        assert terminal.code == "verified_candidate_not_hung"
        assert futu.calls == 1
        assert replay_calls == [terminal.job_id]
        assert [command[0] for command in docker.commands] == [
            "llm-smoke",
            "qlib-adapt",
            "research",
        ]

        # Supply prior artificial comparable experiments, without creating
        # extra authority jobs, registry artifacts or book candidates. The
        # current worker still records exactly its one requested formula.
        job_root = workspace / "jobs" / terminal.job_id
        raw = json.loads(next((job_root / "research").rglob("qlib_receipt.json")).read_text())
        bound = json.loads((job_root / "qlib_engine_receipt.json").read_text())
        assert bound["turnover_period"] == raw["metrics"]["turnover"] == 0.2
        factor = next((job_root / "research").rglob("candidate_factor.py"))
        d34_candidate_kwargs(
            settings,
            candidate_id="artificial-physical-wrapper-family-support",
            source_path=factor,
            source_digest=hashlib.sha256(factor.read_bytes()).hexdigest(),
            factor_id=raw["factor_id"],
            universe=["SPY", "QQQ", "IWM", "DIA"],
            daily_returns=[
                0.005 * math.sin(day * 0.73 + 2) for day in range(len(raw["return_dates"]))
            ],
            return_dates=raw["return_dates"],
            turnover_period=0.2,
        )

        projected = project_terminal_research_results(
            settings,
            jobs=jobs,
            registry=registry,
        )
        assert projected["requests_projected"] == 1
        finished_jobs = jobs.list(workspace_id="default", limit=100, state=None)
        artifacts = registry.list_artifacts(workspace_id="default", limit=100)
        book = project_book(settings)
        assert len(finished_jobs) == 1
        assert finished_jobs[0].state == "succeeded"
        assert len(artifacts) == 1
        # The worker remains research-only; the same-chat result projector owns
        # the current automatic simulated activation after all quality checks.
        assert book["verified_count"] == 0
        assert book["hung_count"] == 1
        assert len(book["candidates"]) == 1
        candidate = book["candidates"][0]
        assert candidate["status"] == "hung"
        quality = candidate["new_capital_quality_snapshot"]
        assert quality["eligible"] is True and quality["tier"] == "T2"
        assert quality["n_family_members"] == quality["family"]["n_applicable_trials"] == 19
        assert quality["family"]["excluded"] == []
        assert quality["evidence_binding"]["selected_engine"] == "qlib"
        assert quality["evidence_binding"]["exposure_engine"] == "platform"
        assert candidate["artifact_id"] == artifacts[0].artifact_id
        assert candidate["source_digest"] == artifacts[0].candidate_code_digest
        assert candidate["comparison_digest"] == artifacts[0].comparison_digest
        assert (
            hashlib.sha256(Path(candidate["source_path"]).read_bytes()).hexdigest()
            == (candidate["source_digest"])
        )
        request = book["requests"][0]
        assert request["job_id"] == terminal.job_id
        assert request["candidate_id"] == candidate["candidate_id"]
        assert request["source_digest"] == candidate["source_digest"]
        assert request["result_reply"]["code"] == "paper_running"
        assert request["result_reply"]["provenance"]["candidate_id"] == candidate["candidate_id"]
        assert request["result_reply"]["provenance"]["source_digest"] == candidate["source_digest"]

        sleeves = PaperStrategySleeveStorage(data_root / "api_runs")
        persisted_sleeves = sleeves.list_sleeves()
        assert len(persisted_sleeves) == 1
        sleeve = persisted_sleeves[0]
        assert sleeve.sleeve_id == candidate["sleeve_id"]
        assert sleeve.status.value == "running"
        assert sleeve.mode.value == "allocated"
        assert sleeve.initial_allocated_cash == sleeve.cash == 10_000.0
        assert sleeve.metadata["candidate_id"] == candidate["candidate_id"]
        assert sleeve.metadata["source_digest"] == candidate["source_digest"]
        assert sleeve.metadata["candidate_code_digest"] == candidate["source_digest"]
        assert sleeve.metadata["comparison_digest"] == candidate["comparison_digest"]
        config = sleeves.load_strategy_config(sleeve.strategy_config_id)
        assert config.symbols == candidate["universe"]
        assert config.factor_ids == [candidate["factor_id"]]

        account_store = build_paper_account_repository(data_root / "api_runs", settings=settings)
        account = account_store.load()
        assert account.account_id == sleeve.account_id
        assert account.sleeve_cash[sleeve.sleeve_id] == 10_000.0
        assert account.cash == account.initial_cash  # Allocation is not a trade or profit.
        allocations = [row for row in account.ledger if row.kind == "sleeve_cash_allocated"]
        assert len(allocations) == 1
        assert allocations[0].source == f"strategy:{sleeve.sleeve_id}"
        assert "10000.00" in allocations[0].note
        assert not account.positions
        assert not sleeves.load_signals(sleeve.sleeve_id)
        assert not sleeves.load_executions(sleeve.sleeve_id)
        assert not sleeves.load_sleeve_lots(sleeve.sleeve_id)
        account_before_replay = account.model_dump(mode="json")
        sleeve_before_replay = sleeve.model_dump(mode="json")

        replayed = _run_wrapper(
            wrapper,
            command_id="command-pg-physical-2",
            hermes_run_id="hermes-run-pg-physical-2",
        )
        assert replayed["status"] == "verified_candidate"
        assert replayed["result_reply"]["code"] == "paper_running"
        assert replayed["candidate_id"] == candidate["candidate_id"]
        assert replayed["source_digest"] == candidate["source_digest"]
        assert len(jobs.list(workspace_id="default", limit=100, state=None)) == 1
        assert len(registry.list_artifacts(workspace_id="default", limit=100)) == 1
        repeated_book = project_book(settings)
        assert repeated_book["verified_count"] == 0 and repeated_book["hung_count"] == 1
        assert len(repeated_book["candidates"]) == 1
        assert repeated_book["candidates"][0]["sleeve_id"] == sleeve.sleeve_id
        assert len(sleeves.list_sleeves()) == 1
        assert sleeves.load_sleeve(sleeve.sleeve_id).model_dump(mode="json") == sleeve_before_replay
        assert account_store.load().model_dump(mode="json") == account_before_replay
        assert futu.calls == 1 and replay_calls == [terminal.job_id]
        db.reset_database_cache()


_RUNTIME_ACL_LOGIN = "aqp_rsch034_runtime_test"
_RUNTIME_ACL_PASSWORD = "rsch034-runtime-test-only"
_READONLY_ACL_LOGIN = "aqp_rsch034_readonly_test"
_READONLY_ACL_PASSWORD = "rsch034-readonly-test-only"


def test_migration_034_keeps_fixed_policy_read_only_during_runtime_enqueue() -> None:
    """The runtime can enqueue without gaining write access to fixed policy."""
    with isolated_test_database_url(_base_database_url(), purpose="rsch034a") as url:
        database = db.Database(url, connect_timeout=1)
        db.run_migrations(database)
        try:
            with database.connect() as connection:
                _provision_test_login(
                    connection,
                    login=_RUNTIME_ACL_LOGIN,
                    password=_RUNTIME_ACL_PASSWORD,
                    group="quant_runtime",
                )
                _provision_test_login(
                    connection,
                    login=_READONLY_ACL_LOGIN,
                    password=_READONLY_ACL_PASSWORD,
                    group="quant_readonly",
                )

            runtime_url = _url_as(
                url,
                user=_RUNTIME_ACL_LOGIN,
                password=_RUNTIME_ACL_PASSWORD,
            )
            runtime_settings = Settings(
                database=DatabaseSettings(
                    enabled=True,
                    url=runtime_url,
                    auto_migrate=False,
                    connect_timeout_seconds=1,
                )
            )
            db.reset_database_cache()
            jobs = PostgresJobAuthority(runtime_settings)
            input_document = build_owner_request_input(
                objective="Restricted-role enqueue probe",
                universe=["SPY"],
            )
            command = EnqueueJobCommand(
                resource_envelope_id=LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
                workspace_id="default",
                job_key="assistant-remote:rsch034-acl",
                input_digest=digest_document(input_document),
                input_document=input_document,
                budget_reserved_usd=Decimal("10"),
                max_attempts=1,
            )
            queued = jobs.enqueue(command)
            assert queued.state == "queued"
            assert queued.resource_envelope_id == LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID
            replayed = jobs.enqueue(command)
            assert replayed.job_id == queued.job_id
            listed = jobs.list(workspace_id="default", limit=100, state="queued")
            assert [job.job_id for job in listed] == [queued.job_id]

            with psycopg.connect(runtime_url) as connection:
                can_update = connection.execute(
                    """
                    SELECT has_table_privilege(
                        current_user,
                        'quant_system.d34_research_resource_envelopes',
                        'UPDATE'
                    )
                    """
                ).fetchone()
                assert can_update == (False,)
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(
                        """
                        UPDATE quant_system.d34_research_resource_envelopes
                        SET policy_document = policy_document
                        WHERE resource_envelope_id = %s
                        """,
                        (LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,),
                    )
                connection.rollback()

            readonly_url = _url_as(
                url,
                user=_READONLY_ACL_LOGIN,
                password=_READONLY_ACL_PASSWORD,
            )
            with psycopg.connect(readonly_url) as connection:
                envelope = connection.execute(
                    """
                    SELECT resource_envelope_id, policy_digest
                    FROM quant_system.d34_research_resource_envelopes
                    """
                ).fetchall()
            assert envelope == [
                (
                    LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
                    LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
                )
            ]
        finally:
            db.reset_database_cache()
            cleanup = db.Database(url, connect_timeout=1)
            with cleanup.connect() as connection:
                _drop_test_login(connection, _RUNTIME_ACL_LOGIN)
                _drop_test_login(connection, _READONLY_ACL_LOGIN)
            db.reset_database_cache()
