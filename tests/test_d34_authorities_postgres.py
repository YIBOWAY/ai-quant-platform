from __future__ import annotations

import os
from contextlib import contextmanager
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.d34.engine_comparison import (
    ComparisonPolicy,
    EngineReceipt,
    compare_engine_receipts,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.d34_job_authority import (
    EnqueueJobCommand,
    JobAuthorityError,
    PostgresJobAuthority,
)
from quant_system.hermes.d34_mandate_authority import (
    CreateMandateCommand,
    PostgresMandateAuthority,
)
from quant_system.hermes.d34_registry_authority import (
    PostgresRegistryAuthority,
    ProvisionCanaryCommand,
    RegisterArtifactCommand,
)
from quant_system.hermes.d34_safety_authority import D34SafetyAuthority
from quant_system.storage import database as db
from quant_system.storage.database import list_migration_files
from tests.postgres_reset import isolated_test_database_url

pytestmark = pytest.mark.pg


def _base_url() -> str:
    value = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get(
        "QS_TEST_DATABASE_URL"
    )
    if not value:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    database_name = conninfo_to_dict(value).get("dbname", "")
    if not (database_name.endswith("_tmp") or "test" in database_name):
        pytest.fail("D-34 PostgreSQL tests require a throwaway base database")
    return value


@contextmanager
def _authorities():
    with isolated_test_database_url(_base_url(), purpose="d34authority") as isolated_url:
        admin = db.Database(isolated_url, connect_timeout=2)
        migrations = tuple(
            name
            for name in list_migration_files()
            if name[:3].isdigit() and int(name[:3]) <= 32
        )
        db.run_migrations(admin, only=migrations)
        suffix = uuid4().hex[:12]
        login, password = f"d34_runtime_{suffix}", f"d34-runtime-{suffix}"
        with psycopg.connect(isolated_url) as conn:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION PASSWORD {}"
                ).format(sql.Identifier(login), sql.Literal(password))
            )
            conn.execute(sql.SQL("GRANT quant_runtime TO {}").format(sql.Identifier(login)))
        params = conninfo_to_dict(isolated_url)
        params.update(user=login, password=password)
        runtime_url = make_conninfo(**params)
        settings = Settings(
            database=DatabaseSettings(
                enabled=True,
                url=runtime_url,
                auto_migrate=False,
                connect_timeout_seconds=2,
            )
        )
        try:
            yield (
                admin,
                PostgresMandateAuthority(settings),
                PostgresJobAuthority(settings),
                PostgresRegistryAuthority(settings),
                D34SafetyAuthority(settings),
            )
        finally:
            with psycopg.connect(isolated_url, autocommit=True) as conn:
                conn.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE usename = %s AND pid <> pg_backend_pid()",
                    (login,),
                )
                conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(login)))


def _receipt(*, engine: str, digest: str) -> EngineReceipt:
    return EngineReceipt(
        engine=engine,  # type: ignore[arg-type]
        snapshot_digest="a" * 64,
        universe_digest="b" * 64,
        calendar_digest="c" * 64,
        target_weights_digest="d" * 64,
        daily_returns=(0.0, 0.01, -0.002),
        return_dates=("2026-08-07", "2026-08-10", "2026-08-11"),
        terminal_nav=1.008,
        terminal_weights={"SPY": 0.5, "QQQ": 0.5},
        receipt_digest=digest * 64,
    )


def test_030_032_runtime_authorities_complete_idempotent_artifact_canary_flow() -> None:
    with _authorities() as (admin, mandates, jobs, registry, safety):
        mandate = mandates.create(
            CreateMandateCommand(
                owner_user_id=ROOT_USER_ID,
                workspace_id="default",
                duration_days=30,
                universe=("SPY", "QQQ", "IWM", "DIA"),
                hypotheses_per_cycle=1,
                max_iterations=3,
                max_experiments_per_iteration=3,
                max_concurrent_jobs=1,
                llm_budget_usd=Decimal("100"),
                llm_warning_fraction=Decimal("0.8"),
                paper_execution_allowed=True,
            )
        )
        job = jobs.enqueue(
            EnqueueJobCommand(
                mandate_id=mandate.mandate_id,
                workspace_id="default",
                job_key="cycle-1:hypothesis-1",
                input_digest="9" * 64,
                input_document={"cycle": 1, "hypothesis": 1},
                budget_reserved_usd=Decimal("10"),
            )
        )
        lease = jobs.lease_next(
            workspace_id="default", worker_id="launchagent-d34", lease_seconds=60
        )
        assert lease is not None and lease.job.job_id == job.job_id
        jobs.mark_running(
            job_id=job.job_id,
            lease_id=lease.lease_id,
            container_id="container-test",
        )
        jobs.finish(
            job_id=job.job_id,
            lease_id=lease.lease_id,
            state="succeeded",
            outcome_code="receipts_ready",
            outcome_document={"snapshot_digest": "a" * 64},
            budget_spent_usd=Decimal("1.25"),
            provider_receipt_digest="8" * 64,
        )

        qlib, platform = _receipt(engine="qlib", digest="e"), _receipt(
            engine="platform", digest="f"
        )
        comparison = compare_engine_receipts(
            qlib=qlib,
            platform=platform,
            policy=ComparisonPolicy.initial(),
        )
        command = RegisterArtifactCommand(
            job_id=job.job_id,
            mandate_id=mandate.mandate_id,
            workspace_id="default",
            qlib_receipt=qlib,
            platform_receipt=platform,
            comparison=comparison,
            candidate_code_digest="1" * 64,
            qlib_config_digest="2" * 64,
            rdagent_commit="3" * 40,
            qlib_commit="4" * 40,
            docker_image_digest="sha256:" + "5" * 64,
        )

        first = registry.record_artifact_evaluation(command)
        replay = registry.record_artifact_evaluation(command)

        assert first.accepted is True and first.artifact is not None
        assert replay.artifact == first.artifact
        assert first.artifact.qualification_scope == "paper_only"
        canary = registry.provision_canary(
            ProvisionCanaryCommand(
                artifact_id=first.artifact.artifact_id,
                sleeve_id="sleeve-d34-cycle-1",
                nav=Decimal("100000"),
                allocated_cash=Decimal("1000"),
                workspace_id="default",
            )
        )
        assert canary.status == "running"
        assert registry.provision_canary(
            ProvisionCanaryCommand(
                artifact_id=first.artifact.artifact_id,
                sleeve_id="sleeve-d34-cycle-1",
                nav=Decimal("100000"),
                allocated_cash=Decimal("1000"),
                workspace_id="default",
            )
        ) == canary
        paused = registry.transition_canary(
            canary_id=canary.canary_id,
            action="pause",
            expected_version=1,
            reason="risk threshold",
        )
        assert paused.status == "paused"
        assert registry.list_artifacts(workspace_id="default", limit=10)[0].status == "paused"

        stopped = safety.set_emergency_stop(
            workspace_id="default", enabled=True, reason="owner stop"
        )
        assert stopped["emergency_stop"]["active"] is True  # type: ignore[index]
        assert stopped["paper_execution_enabled"] is False
        with pytest.raises(JobAuthorityError) as blocked_job:
            jobs.enqueue(
                EnqueueJobCommand(
                    mandate_id=mandate.mandate_id,
                    workspace_id="default",
                    job_key="cycle-2:hypothesis-1",
                    input_digest="7" * 64,
                    input_document={"cycle": 2},
                    budget_reserved_usd=Decimal("1"),
                )
            )
        assert blocked_job.value.code == "d34_job_conflict"

        with (
            admin.connect() as conn,
            pytest.raises(psycopg.errors.RaiseException, match="append-only"),
        ):
            conn.execute(
                "UPDATE quant_system.d34_policy_decisions "
                "SET decision_document = '{}'::jsonb"
            )
