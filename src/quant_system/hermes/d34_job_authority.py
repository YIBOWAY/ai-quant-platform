"""Durable lease, attempt, and budget authority for D-34 research jobs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import SCHEMA, DatabaseUnavailable, get_database

JOB_CONTRACT = "hqa.d34_experiment_job/v1"
JOB_STATES = frozenset(
    {"queued", "leased", "running", "succeeded", "rejected", "outcome_unknown", "cancelled"}
)
_TERMINAL_STATES = frozenset({"succeeded", "rejected", "outcome_unknown", "cancelled"})
_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class JobAuthorityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ExperimentJob:
    job_id: str
    mandate_id: str
    workspace_id: str
    job_key: str
    state: str
    attempt_count: int
    max_attempts: int
    input_digest: str
    lease_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    budget_reserved_usd: Decimal
    budget_spent_usd: Decimal
    created_at: datetime
    updated_at: datetime
    version: int
    outcome_code: str | None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "contract": JOB_CONTRACT,
            "job_id": self.job_id,
            "mandate_id": self.mandate_id,
            "workspace_id": self.workspace_id,
            "job_key": self.job_key,
            "state": self.state,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "input_digest": self.input_digest,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "heartbeat_at": self.heartbeat_at,
            "budget_reserved_usd": f"{self.budget_reserved_usd:.6f}",
            "budget_spent_usd": f"{self.budget_spent_usd:.6f}",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "outcome_code": self.outcome_code,
        }


@dataclass(frozen=True)
class EnqueueJobCommand:
    mandate_id: str
    workspace_id: str
    job_key: str
    input_digest: str
    input_document: dict[str, object]
    budget_reserved_usd: Decimal
    max_attempts: int = 3


@dataclass(frozen=True)
class JobLease:
    job: ExperimentJob
    attempt_id: str
    lease_id: str


@dataclass(frozen=True)
class LeasedJobInput:
    job_id: str
    input_digest: str
    input_document: dict[str, object]


class JobAuthorityPort(Protocol):
    def list(
        self, *, workspace_id: str, limit: int, state: str | None
    ) -> list[ExperimentJob | dict[str, object]]: ...

    def cancel_queued(self, *, workspace_id: str, reason: str) -> int: ...


_COLUMNS = """
job_id, mandate_id, workspace_id, job_key, state, attempt_count, max_attempts,
input_digest, lease_owner, lease_expires_at, heartbeat_at, budget_reserved_usd,
budget_spent_usd, created_at, updated_at, version, outcome_code
"""


def _from_row(row: tuple[object, ...]) -> ExperimentJob:
    return ExperimentJob(
        job_id=str(row[0]),
        mandate_id=str(row[1]),
        workspace_id=str(row[2]),
        job_key=str(row[3]),
        state=str(row[4]),
        attempt_count=int(row[5]),
        max_attempts=int(row[6]),
        input_digest=str(row[7]),
        lease_owner=None if row[8] is None else str(row[8]),
        lease_expires_at=row[9],  # type: ignore[arg-type]
        heartbeat_at=row[10],  # type: ignore[arg-type]
        budget_reserved_usd=Decimal(str(row[11])),
        budget_spent_usd=Decimal(str(row[12])),
        created_at=row[13],  # type: ignore[arg-type]
        updated_at=row[14],  # type: ignore[arg-type]
        version=int(row[15]),
        outcome_code=None if row[16] is None else str(row[16]),
    )


class PostgresJobAuthority:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _database(self):
        database = get_database(self._settings)
        if database is None:
            raise JobAuthorityError("d34_job_unavailable", "D-34 job authority is unavailable")
        return database

    def list(self, *, workspace_id: str, limit: int, state: str | None) -> list[ExperimentJob]:
        if (
            _WORKSPACE_RE.fullmatch(workspace_id) is None
            or not 1 <= limit <= 100
            or (state is not None and state not in JOB_STATES)
        ):
            raise JobAuthorityError("d34_job_validation", "research job query is invalid")
        clause = "AND state = %s" if state is not None else ""
        params: tuple[object, ...] = (
            (ROOT_USER_ID, workspace_id, state, limit)
            if state is not None
            else (ROOT_USER_ID, workspace_id, limit)
        )
        try:
            with self._database().connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT {_COLUMNS} FROM {SCHEMA}.d34_experiment_jobs
                    WHERE owner_user_id = %s AND workspace_id = %s {clause}
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    params,
                ).fetchall()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise JobAuthorityError(
                "d34_job_unavailable", "D-34 job authority is unavailable"
            ) from exc
        return [_from_row(row) for row in rows]

    def enqueue(self, command: EnqueueJobCommand) -> ExperimentJob:
        if (
            not command.mandate_id.startswith("mandate-")
            or _WORKSPACE_RE.fullmatch(command.workspace_id) is None
            or not 1 <= len(command.job_key) <= 512
            or _DIGEST_RE.fullmatch(command.input_digest) is None
            or not isinstance(command.input_document, dict)
            or not Decimal("0") <= command.budget_reserved_usd <= Decimal("100000")
            or not 1 <= command.max_attempts <= 20
        ):
            raise JobAuthorityError("d34_job_validation", "research job request is invalid")
        job_id = f"job-{uuid4()}"
        try:
            with self._database().connect() as conn, conn.transaction():
                mandate = conn.execute(
                    f"""
                    SELECT llm_budget_usd, llm_spent_usd, status,
                           (expires_at > clock_timestamp()) AS unexpired
                    FROM {SCHEMA}.d34_mandates
                    WHERE mandate_id = %s AND owner_user_id = %s AND workspace_id = %s
                    FOR UPDATE
                    """,
                    (command.mandate_id, ROOT_USER_ID, command.workspace_id),
                ).fetchone()
                if mandate is None or mandate[2] != "active" or mandate[3] is not True:
                    raise JobAuthorityError("d34_job_conflict", "mandate is not active")
                emergency = conn.execute(
                    f"""
                    SELECT enabled FROM {SCHEMA}.d34_execution_authority_events
                    WHERE owner_user_id = %s AND workspace_id = %s
                      AND event_type = 'emergency_stop'
                    ORDER BY event_seq DESC LIMIT 1
                    """,
                    (ROOT_USER_ID, command.workspace_id),
                ).fetchone()
                if emergency is not None and emergency[0] is True:
                    raise JobAuthorityError(
                        "d34_job_conflict", "emergency stop blocks new research jobs"
                    )
                reserved_row = conn.execute(
                    f"""
                    SELECT COALESCE(sum(budget_reserved_usd), 0)
                    FROM {SCHEMA}.d34_experiment_jobs
                    WHERE mandate_id = %s AND state IN ('queued', 'leased', 'running')
                    """,
                    (command.mandate_id,),
                ).fetchone()
                reserved = Decimal(str(reserved_row[0] if reserved_row else 0))
                if Decimal(str(mandate[1])) + reserved + command.budget_reserved_usd > Decimal(
                    str(mandate[0])
                ):
                    raise JobAuthorityError(
                        "d34_budget_exhausted", "mandate LLM budget is exhausted"
                    )
                row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_experiment_jobs (
                        job_id, mandate_id, owner_user_id, workspace_id, job_key,
                        input_digest, input_document, max_attempts, budget_reserved_usd
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (mandate_id, job_key) DO NOTHING
                    RETURNING {_COLUMNS}
                    """,
                    (
                        job_id,
                        command.mandate_id,
                        ROOT_USER_ID,
                        command.workspace_id,
                        command.job_key,
                        command.input_digest,
                        Jsonb(command.input_document),
                        command.max_attempts,
                        command.budget_reserved_usd,
                    ),
                ).fetchone()
                if row is None:
                    existing = conn.execute(
                        f"""
                        SELECT {_COLUMNS}, input_document
                        FROM {SCHEMA}.d34_experiment_jobs
                        WHERE mandate_id = %s AND job_key = %s
                        """,
                        (command.mandate_id, command.job_key),
                    ).fetchone()
                    if (
                        existing is None
                        or str(existing[7]) != command.input_digest
                        or existing[17] != command.input_document
                    ):
                        raise JobAuthorityError(
                            "d34_job_conflict", "job key was reused with different inputs"
                        )
                    return _from_row(existing[:17])
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_job_events
                    (event_id, job_id, event_type, job_version, event_data)
                    VALUES (%s, %s, 'queued', 1, %s)
                    """,
                    (f"job-event-{uuid4()}", job_id, Jsonb({"input_digest": command.input_digest})),
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_budget_events
                    (event_id, mandate_id, job_id, event_type, amount_usd)
                    VALUES (%s, %s, %s, 'reserved', %s)
                    """,
                    (
                        f"budget-event-{uuid4()}",
                        command.mandate_id,
                        job_id,
                        command.budget_reserved_usd,
                    ),
                )
        except JobAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise JobAuthorityError(
                "d34_job_unavailable", "D-34 job authority is unavailable"
            ) from exc
        return _from_row(row)

    def lease_next(
        self, *, workspace_id: str, worker_id: str, lease_seconds: int = 900
    ) -> JobLease | None:
        if (
            _WORKSPACE_RE.fullmatch(workspace_id) is None
            or not 1 <= len(worker_id) <= 200
            or not 30 <= lease_seconds <= 86400
        ):
            raise JobAuthorityError("d34_job_validation", "job lease request is invalid")
        lease_id, attempt_id = f"lease-{uuid4()}", f"attempt-{uuid4()}"
        try:
            with self._database().connect() as conn, conn.transaction():
                mandate = conn.execute(
                    f"""
                    SELECT mandate_id, max_concurrent_jobs
                    FROM {SCHEMA}.d34_mandates
                    WHERE owner_user_id = %s AND workspace_id = %s
                      AND status = 'active' AND expires_at > clock_timestamp()
                    ORDER BY created_at DESC LIMIT 1
                    FOR UPDATE
                    """,
                    (ROOT_USER_ID, workspace_id),
                ).fetchone()
                if mandate is None:
                    return None
                active = conn.execute(
                    f"""
                    SELECT count(*) FROM {SCHEMA}.d34_experiment_jobs
                    WHERE mandate_id = %s AND state IN ('leased', 'running')
                    """,
                    (mandate[0],),
                ).fetchone()
                if active is None or int(active[0]) >= int(mandate[1]):
                    return None
                candidate = conn.execute(
                    f"""
                    SELECT job_id FROM {SCHEMA}.d34_experiment_jobs AS job
                    WHERE job.owner_user_id = %s AND job.workspace_id = %s
                      AND job.mandate_id = %s
                      AND job.state = 'queued' AND job.attempt_count < job.max_attempts
                      AND NOT COALESCE((
                          SELECT enabled
                          FROM {SCHEMA}.d34_execution_authority_events AS authority
                          WHERE authority.owner_user_id = job.owner_user_id
                            AND authority.workspace_id = job.workspace_id
                            AND authority.event_type = 'emergency_stop'
                          ORDER BY authority.event_seq DESC LIMIT 1
                      ), FALSE)
                    ORDER BY job.created_at FOR UPDATE SKIP LOCKED LIMIT 1
                    """,
                    (ROOT_USER_ID, workspace_id, mandate[0]),
                ).fetchone()
                if candidate is None:
                    return None
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_experiment_jobs
                    SET state = 'leased', attempt_count = attempt_count + 1,
                        lease_id = %s, lease_owner = %s,
                        leased_at = clock_timestamp(), heartbeat_at = clock_timestamp(),
                        lease_expires_at = clock_timestamp() + make_interval(secs => %s),
                        updated_at = clock_timestamp(), version = version + 1
                    WHERE job_id = %s RETURNING {_COLUMNS}
                    """,
                    (lease_id, worker_id, lease_seconds, candidate[0]),
                ).fetchone()
                if row is None:
                    raise RuntimeError("leased job disappeared")
                job = _from_row(row)
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_experiment_attempts
                    (attempt_id, job_id, attempt_number, lease_id, state, worker_id)
                    VALUES (%s, %s, %s, %s, 'leased', %s)
                    """,
                    (attempt_id, job.job_id, job.attempt_count, lease_id, worker_id),
                )
                self._event(
                    conn,
                    job=job,
                    attempt_id=attempt_id,
                    event_type="leased",
                    data={"lease_id": lease_id, "worker_id": worker_id},
                )
        except JobAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error, RuntimeError) as exc:
            raise JobAuthorityError(
                "d34_job_unavailable", "D-34 job authority is unavailable"
            ) from exc
        return JobLease(job=job, attempt_id=attempt_id, lease_id=lease_id)

    def cancel_queued(self, *, workspace_id: str, reason: str) -> int:
        if (
            _WORKSPACE_RE.fullmatch(workspace_id) is None
            or not 1 <= len(reason.strip()) <= 1000
        ):
            raise JobAuthorityError("d34_job_validation", "job cancellation is invalid")
        cancelled = 0
        try:
            with self._database().connect() as conn, conn.transaction():
                rows = conn.execute(
                    f"""
                    SELECT job_id, mandate_id, budget_reserved_usd
                    FROM {SCHEMA}.d34_experiment_jobs
                    WHERE owner_user_id = %s AND workspace_id = %s
                      AND state = 'queued'
                    ORDER BY created_at
                    FOR UPDATE
                    """,
                    (ROOT_USER_ID, workspace_id),
                ).fetchall()
                for job_id, mandate_id, reserved_raw in rows:
                    row = conn.execute(
                        f"""
                        UPDATE {SCHEMA}.d34_experiment_jobs
                        SET state = 'cancelled', outcome_code = 'd34_rollback',
                            outcome_document = %s, finished_at = clock_timestamp(),
                            updated_at = clock_timestamp(), version = version + 1
                        WHERE job_id = %s AND state = 'queued'
                        RETURNING {_COLUMNS}
                        """,
                        (
                            Jsonb(
                                {
                                    "reason": reason.strip(),
                                    "recovery": "create_a_new_job_after_mandate_resume",
                                }
                            ),
                            job_id,
                        ),
                    ).fetchone()
                    if row is None:
                        continue
                    job = _from_row(row)
                    conn.execute(
                        f"""
                        INSERT INTO {SCHEMA}.d34_budget_events
                        (event_id, mandate_id, job_id, event_type, amount_usd, event_data)
                        VALUES (%s, %s, %s, 'released', %s, %s)
                        """,
                        (
                            f"budget-event-{uuid4()}",
                            mandate_id,
                            job_id,
                            Decimal(str(reserved_raw)),
                            Jsonb({"reason": reason.strip()}),
                        ),
                    )
                    self._event(
                        conn,
                        job=job,
                        attempt_id=None,
                        event_type="cancelled",
                        data={"reason": reason.strip()},
                    )
                    cancelled += 1
        except JobAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise JobAuthorityError(
                "d34_job_unavailable", "D-34 job authority is unavailable"
            ) from exc
        return cancelled

    def mark_running(
        self, *, job_id: str, lease_id: str, container_id: str | None
    ) -> ExperimentJob:
        try:
            with self._database().connect() as conn, conn.transaction():
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_experiment_jobs
                    SET state = 'running', started_at = COALESCE(started_at, clock_timestamp()),
                        heartbeat_at = clock_timestamp(), updated_at = clock_timestamp(),
                        version = version + 1
                    WHERE job_id = %s AND lease_id = %s AND state = 'leased'
                    RETURNING {_COLUMNS}
                    """,
                    (job_id, lease_id),
                ).fetchone()
                if row is None:
                    raise JobAuthorityError("d34_job_conflict", "job lease is stale")
                job = _from_row(row)
                attempt = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_experiment_attempts
                    SET state = 'running', container_id = %s, heartbeat_at = clock_timestamp()
                    WHERE job_id = %s AND lease_id = %s AND state = 'leased'
                    RETURNING attempt_id
                    """,
                    (container_id, job_id, lease_id),
                ).fetchone()
                self._event(
                    conn,
                    job=job,
                    attempt_id=str(attempt[0]) if attempt else None,
                    event_type="running",
                    data={"container_id": container_id},
                )
        except JobAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise JobAuthorityError(
                "d34_job_unavailable", "D-34 job authority is unavailable"
            ) from exc
        return job

    def read_leased_input(self, *, job_id: str, lease_id: str) -> LeasedJobInput:
        if not job_id.startswith("job-") or not lease_id.startswith("lease-"):
            raise JobAuthorityError("d34_job_validation", "job lease identity is invalid")
        try:
            with self._database().connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT input_digest, input_document
                    FROM {SCHEMA}.d34_experiment_jobs
                    WHERE job_id = %s AND lease_id = %s
                      AND owner_user_id = %s AND state IN ('leased', 'running')
                    """,
                    (job_id, lease_id, ROOT_USER_ID),
                ).fetchone()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise JobAuthorityError(
                "d34_job_unavailable", "D-34 job authority is unavailable"
            ) from exc
        if row is None or not isinstance(row[1], dict):
            raise JobAuthorityError("d34_job_conflict", "job lease is stale")
        return LeasedJobInput(
            job_id=job_id,
            input_digest=str(row[0]),
            input_document=dict(row[1]),
        )

    def heartbeat(self, *, job_id: str, lease_id: str, lease_seconds: int = 900) -> ExperimentJob:
        if not 30 <= lease_seconds <= 86400:
            raise JobAuthorityError("d34_job_validation", "heartbeat duration is invalid")
        try:
            with self._database().connect() as conn, conn.transaction():
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_experiment_jobs
                    SET heartbeat_at = clock_timestamp(),
                        lease_expires_at = clock_timestamp() + make_interval(secs => %s),
                        updated_at = clock_timestamp(), version = version + 1
                    WHERE job_id = %s AND lease_id = %s AND state IN ('leased', 'running')
                    RETURNING {_COLUMNS}
                    """,
                    (lease_seconds, job_id, lease_id),
                ).fetchone()
                if row is None:
                    raise JobAuthorityError("d34_job_conflict", "job lease is stale")
                job = _from_row(row)
                conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_experiment_attempts SET heartbeat_at = clock_timestamp()
                    WHERE job_id = %s AND lease_id = %s AND state IN ('leased', 'running')
                    """,
                    (job_id, lease_id),
                )
        except JobAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise JobAuthorityError(
                "d34_job_unavailable", "D-34 job authority is unavailable"
            ) from exc
        return job

    def finish(
        self,
        *,
        job_id: str,
        lease_id: str,
        state: str,
        outcome_code: str,
        outcome_document: dict[str, object],
        budget_spent_usd: Decimal,
        provider_receipt_digest: str | None = None,
    ) -> ExperimentJob:
        if (
            state not in _TERMINAL_STATES
            or not 1 <= len(outcome_code) <= 128
            or not isinstance(outcome_document, dict)
            or budget_spent_usd < 0
            or (
                provider_receipt_digest is not None
                and _DIGEST_RE.fullmatch(provider_receipt_digest) is None
            )
        ):
            raise JobAuthorityError("d34_job_validation", "job outcome is invalid")
        try:
            with self._database().connect() as conn, conn.transaction():
                current = conn.execute(
                    f"""
                    SELECT mandate_id, budget_reserved_usd
                    FROM {SCHEMA}.d34_experiment_jobs
                    WHERE job_id = %s AND lease_id = %s
                      AND state IN ('leased', 'running') FOR UPDATE
                    """,
                    (job_id, lease_id),
                ).fetchone()
                if current is None:
                    raise JobAuthorityError("d34_job_conflict", "job lease is stale")
                mandate_id, reserved_raw = current
                reserved = Decimal(str(reserved_raw))
                charged = reserved if state == "outcome_unknown" else budget_spent_usd
                if charged > reserved:
                    raise JobAuthorityError("d34_budget_exhausted", "job exceeded reserved budget")
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_experiment_jobs
                    SET state = %s, outcome_code = %s, outcome_document = %s,
                        budget_spent_usd = %s, finished_at = clock_timestamp(),
                        updated_at = clock_timestamp(), version = version + 1,
                        lease_expires_at = NULL
                    WHERE job_id = %s AND lease_id = %s RETURNING {_COLUMNS}
                    """,
                    (state, outcome_code, Jsonb(outcome_document), charged, job_id, lease_id),
                ).fetchone()
                if row is None:
                    raise JobAuthorityError("d34_job_conflict", "job lease is stale")
                job = _from_row(row)
                attempt = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_experiment_attempts
                    SET state = %s, outcome_code = %s, finished_at = clock_timestamp(),
                        recovery_document = %s
                    WHERE job_id = %s AND lease_id = %s AND state IN ('leased', 'running')
                    RETURNING attempt_id
                    """,
                    (state, outcome_code, Jsonb(outcome_document), job_id, lease_id),
                ).fetchone()
                conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_mandates
                    SET llm_spent_usd = llm_spent_usd + %s,
                        updated_at = clock_timestamp(), version = version + 1
                    WHERE mandate_id = %s
                    """,
                    (charged, mandate_id),
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_budget_events
                    (event_id, mandate_id, job_id, attempt_id, event_type, amount_usd,
                     provider_receipt_digest, event_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        f"budget-event-{uuid4()}",
                        mandate_id,
                        job_id,
                        attempt[0] if attempt else None,
                        "outcome_unknown" if state == "outcome_unknown" else "consumed",
                        charged,
                        provider_receipt_digest,
                        Jsonb({"outcome_code": outcome_code}),
                    ),
                )
                self._event(
                    conn,
                    job=job,
                    attempt_id=str(attempt[0]) if attempt else None,
                    event_type=state,
                    data={"outcome_code": outcome_code},
                )
        except JobAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise JobAuthorityError(
                "d34_job_unavailable", "D-34 job authority is unavailable"
            ) from exc
        return job

    def reconcile_expired(self, *, workspace_id: str) -> int:
        """Conservatively close expired external-effect leases as unknown."""
        if _WORKSPACE_RE.fullmatch(workspace_id) is None:
            raise JobAuthorityError("d34_job_validation", "workspace_id is invalid")
        reconciled = 0
        while True:
            try:
                with self._database().connect() as conn:
                    row = conn.execute(
                        f"""
                        SELECT job_id, lease_id FROM {SCHEMA}.d34_experiment_jobs
                        WHERE owner_user_id = %s AND workspace_id = %s
                          AND state IN ('leased', 'running')
                          AND lease_expires_at <= clock_timestamp()
                        ORDER BY lease_expires_at LIMIT 1
                        """,
                        (ROOT_USER_ID, workspace_id),
                    ).fetchone()
            except (DatabaseUnavailable, psycopg.Error) as exc:
                raise JobAuthorityError(
                    "d34_job_unavailable", "D-34 job authority is unavailable"
                ) from exc
            if row is None:
                return reconciled
            try:
                self.finish(
                    job_id=str(row[0]),
                    lease_id=str(row[1]),
                    state="outcome_unknown",
                    outcome_code="lease_expired",
                    outcome_document={"recovery": "inspect_container_and_receipts"},
                    budget_spent_usd=Decimal("0"),
                )
            except JobAuthorityError as exc:
                if exc.code == "d34_job_conflict":
                    continue
                raise
            reconciled += 1

    @staticmethod
    def _event(
        conn,
        *,
        job: ExperimentJob,
        attempt_id: str | None,
        event_type: str,
        data: dict[str, object],
    ) -> None:
        conn.execute(
            f"""
            INSERT INTO {SCHEMA}.d34_job_events
            (event_id, job_id, attempt_id, event_type, job_version, event_data)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                f"job-event-{uuid4()}",
                job.job_id,
                attempt_id,
                event_type,
                job.version,
                Jsonb(data),
            ),
        )


__all__ = [
    "EnqueueJobCommand",
    "ExperimentJob",
    "JOB_CONTRACT",
    "JOB_STATES",
    "JobAuthorityError",
    "JobAuthorityPort",
    "JobLease",
    "LeasedJobInput",
    "PostgresJobAuthority",
]
