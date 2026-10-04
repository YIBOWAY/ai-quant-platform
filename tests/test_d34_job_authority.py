from __future__ import annotations

import inspect
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quant_system.config.settings import Settings
from quant_system.d34.research_request import (
    LOCAL_RESEARCH_RESOURCE_ENVELOPE,
    LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
    LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
    build_owner_request_input,
    digest_document,
)
from quant_system.hermes import d34_job_authority as job_module
from quant_system.hermes.d34_job_authority import (
    EnqueueJobCommand,
    JobAuthorityError,
    PostgresJobAuthority,
)


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _ExistingJobConnection:
    def __init__(self, *, command: EnqueueJobCommand) -> None:
        now = datetime(2026, 8, 22, tzinfo=UTC)
        self.existing = (
            "job-existing-response-loss",
            command.resource_envelope_id,
            command.workspace_id,
            command.job_key,
            "queued",
            0,
            command.max_attempts,
            command.input_digest,
            None,
            None,
            None,
            command.budget_reserved_usd,
            Decimal("0"),
            now,
            now,
            1,
            None,
            command.input_document,
        )
        self.queries: list[str] = []

    @contextmanager
    def transaction(self):
        yield

    def execute(self, query, _params):
        normalized = " ".join(str(query).split())
        self.queries.append(normalized)
        if "FROM quant_system.d34_experiment_jobs" in normalized:
            return _Result(self.existing)
        raise AssertionError(f"unexpected query: {normalized}")


class _Database:
    def __init__(self, connection: _ExistingJobConnection) -> None:
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection


class _ConcurrentReplayConnection(_ExistingJobConnection):
    def __init__(self, *, command: EnqueueJobCommand) -> None:
        super().__init__(command=command)
        self.exact_reads = 0

    def execute(self, query, _params):
        normalized = " ".join(str(query).split())
        self.queries.append(normalized)
        if "pg_advisory_xact_lock" in normalized:
            return _Result((None,))
        if "FROM quant_system.d34_experiment_jobs" in normalized and "job_key = %s" in normalized:
            self.exact_reads += 1
            return _Result(None if self.exact_reads == 1 else self.existing)
        if "FROM quant_system.d34_research_resource_envelopes" in normalized:
            return _Result(
                (
                    LOCAL_RESEARCH_RESOURCE_POLICY_DIGEST,
                    LOCAL_RESEARCH_RESOURCE_ENVELOPE,
                )
            )
        if "state IN ('queued', 'leased', 'running')" in normalized:
            return _Result(("job-existing-response-loss",))
        raise AssertionError(f"unexpected query: {normalized}")


def _command() -> EnqueueJobCommand:
    input_document = build_owner_request_input(
        objective="Response-loss research objective",
        universe=["SPY"],
    )
    input_document.update(
        {
            "operation_id": "b" * 64,
            "material_digest": "c" * 64,
            "job_key": "assistant-remote:response-loss",
            "platform_session_id": "platform-session-1",
            "hermes_session_id": "hermes-session-1",
        }
    )
    return EnqueueJobCommand(
        resource_envelope_id=LOCAL_RESEARCH_RESOURCE_ENVELOPE_ID,
        workspace_id="default",
        job_key="assistant-remote:response-loss",
        input_digest=digest_document(input_document),
        input_document=input_document,
        budget_reserved_usd=Decimal("10"),
        max_attempts=1,
    )


def test_existing_job_replay_precedes_resource_and_active_job_rechecks(
    monkeypatch,
) -> None:
    command = _command()
    connection = _ExistingJobConnection(command=command)
    monkeypatch.setattr(
        job_module,
        "get_database",
        lambda _settings: _Database(connection),
    )
    authority = PostgresJobAuthority(Settings())

    replayed = authority.enqueue(command)

    assert replayed.job_id == "job-existing-response-loss"
    assert connection.queries == [connection.queries[0]]
    assert "input_document" in connection.queries[0]
    assert "resource_envelopes" not in connection.queries[0]
    assert "state IN ('queued', 'leased', 'running')" not in connection.queries[0]

    with pytest.raises(JobAuthorityError) as conflict:
        conflicting_document = dict(command.input_document)
        conflicting_document["objective"] = "A different research objective"
        authority.enqueue(
            replace(
                command,
                input_digest=digest_document(conflicting_document),
                input_document=conflicting_document,
            )
        )
    assert conflict.value.code == "d34_job_conflict"


def test_concurrent_exact_replay_rechecks_after_advisory_lock(
    monkeypatch,
) -> None:
    command = _command()
    connection = _ConcurrentReplayConnection(command=command)
    monkeypatch.setattr(
        job_module,
        "get_database",
        lambda _settings: _Database(connection),
    )

    replayed = PostgresJobAuthority(Settings()).enqueue(command)

    assert replayed.job_id == "job-existing-response-loss"
    assert connection.exact_reads == 2
    assert sum("pg_advisory_xact_lock" in query for query in connection.queries) == 1
    assert not any("state IN ('queued', 'leased', 'running')" in q for q in connection.queries)


def test_research_lease_uses_only_fixed_resource_jobs() -> None:
    source = inspect.getsource(PostgresJobAuthority.lease_next)

    assert "d34_mandates" not in source
    assert "d34_execution_authority_events" not in source
    assert "emergency_stop" not in source
    assert "resource_envelope_id IS NOT NULL" in source
    assert "input_document->>'research_only' = 'true'" in source


def test_forward_migration_detaches_new_jobs_and_enforces_one_job() -> None:
    source = (
        Path(__file__).resolve().parent.parent
        / "scripts/sql/034_local_research_resource_envelope.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS quant_system.d34_research_resource_envelopes" in source
    assert "ALTER COLUMN mandate_id DROP NOT NULL" in source
    assert "resource_envelope_id" in source
    assert "uq_d34_local_research_job_key" in source
    assert "WHERE state IN ('queued', 'leased', 'running')" in source
    assert "local-paper-research-v1" in source
    assert "GRANT SELECT, UPDATE" not in source
