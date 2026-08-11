"""Durable owner Mandates for D-34 autonomous paper research.

The authority deliberately owns the transaction and audit event.  API routes
only authenticate the local owner and translate transport models.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import SCHEMA, DatabaseUnavailable, get_database

MANDATE_CONTRACT = "hqa.mandate/v1"
_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class MandateAuthorityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CreateMandateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_user_id: UUID
    workspace_id: str = Field(min_length=1, max_length=128)
    duration_days: int = Field(ge=1, le=365)
    universe: tuple[str, ...] = Field(min_length=1, max_length=64)
    hypotheses_per_cycle: int = Field(ge=1, le=100)
    max_iterations: int = Field(ge=1, le=100)
    max_experiments_per_iteration: int = Field(ge=1, le=100)
    max_concurrent_jobs: int = Field(ge=1, le=32)
    llm_budget_usd: Decimal = Field(gt=Decimal("0"), le=Decimal("100000"))
    llm_warning_fraction: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"))
    paper_execution_allowed: bool


@dataclass(frozen=True)
class Mandate:
    mandate_id: str
    owner_user_id: UUID
    workspace_id: str
    status: str
    universe: tuple[str, ...]
    hypotheses_per_cycle: int
    max_iterations: int
    max_experiments_per_iteration: int
    max_concurrent_jobs: int
    llm_budget_usd: Decimal
    llm_warning_fraction: Decimal
    paper_execution_allowed: bool
    policy_digest: str
    created_at: datetime
    starts_at: datetime
    expires_at: datetime
    updated_at: datetime
    version: int

    def to_public_dict(self) -> dict[str, object]:
        return {
            "contract": MANDATE_CONTRACT,
            "mandate_id": self.mandate_id,
            "owner_user_id": str(self.owner_user_id),
            "workspace_id": self.workspace_id,
            "status": self.status,
            "universe": list(self.universe),
            "hypotheses_per_cycle": self.hypotheses_per_cycle,
            "max_iterations": self.max_iterations,
            "max_experiments_per_iteration": self.max_experiments_per_iteration,
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "llm_budget_usd": f"{self.llm_budget_usd:.2f}",
            "llm_warning_fraction": f"{self.llm_warning_fraction:.2f}",
            "paper_execution_allowed": self.paper_execution_allowed,
            "policy_digest": self.policy_digest,
            "created_at": self.created_at,
            "starts_at": self.starts_at,
            "expires_at": self.expires_at,
            "updated_at": self.updated_at,
            "version": self.version,
        }


class MandateAuthorityPort(Protocol):
    def create(self, command: CreateMandateCommand) -> Mandate | dict[str, object]: ...

    def get_active(self, *, workspace_id: str) -> Mandate | dict[str, object] | None: ...

    def list(self, *, workspace_id: str, limit: int) -> list[Mandate | dict[str, object]]: ...

    def transition(
        self,
        *,
        mandate_id: str,
        action: str,
        expected_version: int,
        reason: str,
    ) -> Mandate | dict[str, object]: ...


def _policy_document(command: CreateMandateCommand) -> dict[str, object]:
    return {
        "contract": MANDATE_CONTRACT,
        "duration_days": command.duration_days,
        "hypotheses_per_cycle": command.hypotheses_per_cycle,
        "llm_budget_usd": f"{command.llm_budget_usd:.2f}",
        "llm_warning_fraction": f"{command.llm_warning_fraction:.2f}",
        "max_concurrent_jobs": command.max_concurrent_jobs,
        "max_experiments_per_iteration": command.max_experiments_per_iteration,
        "max_iterations": command.max_iterations,
        "paper_execution_allowed": command.paper_execution_allowed,
        "universe": list(command.universe),
        "workspace_id": command.workspace_id,
    }


def mandate_policy_digest(command: CreateMandateCommand) -> str:
    encoded = json.dumps(
        _policy_document(command),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_command(command: CreateMandateCommand) -> None:
    if command.owner_user_id != ROOT_USER_ID:
        raise MandateAuthorityError("d34_mandate_forbidden", "mandate owner is invalid")
    if _WORKSPACE_RE.fullmatch(command.workspace_id) is None:
        raise MandateAuthorityError("d34_mandate_validation", "mandate workspace_id is invalid")
    normalized = tuple(symbol.strip().upper() for symbol in command.universe)
    if (
        normalized != command.universe
        or len(set(normalized)) != len(normalized)
        or any(not re.fullmatch(r"[A-Z][A-Z0-9-]{0,15}", item) for item in normalized)
    ):
        raise MandateAuthorityError("d34_mandate_validation", "mandate universe is invalid")


def _mandate_from_row(row: tuple[object, ...]) -> Mandate:
    return Mandate(
        mandate_id=str(row[0]),
        owner_user_id=UUID(str(row[1])),
        workspace_id=str(row[2]),
        status=str(row[3]),
        universe=tuple(str(item) for item in row[4]),
        hypotheses_per_cycle=int(row[5]),
        max_iterations=int(row[6]),
        max_experiments_per_iteration=int(row[7]),
        max_concurrent_jobs=int(row[8]),
        llm_budget_usd=Decimal(str(row[9])),
        llm_warning_fraction=Decimal(str(row[10])),
        paper_execution_allowed=bool(row[11]),
        policy_digest=str(row[12]),
        created_at=row[13],  # type: ignore[arg-type]
        starts_at=row[14],  # type: ignore[arg-type]
        expires_at=row[15],  # type: ignore[arg-type]
        updated_at=row[16],  # type: ignore[arg-type]
        version=int(row[17]),
    )


_MANDATE_COLUMNS = """
mandate_id, owner_user_id, workspace_id, status, universe,
hypotheses_per_cycle, max_iterations, max_experiments_per_iteration,
max_concurrent_jobs, llm_budget_usd, llm_warning_fraction,
paper_execution_allowed, policy_digest, created_at, starts_at, expires_at,
updated_at, version
"""


class PostgresMandateAuthority:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _database(self):
        database = get_database(self._settings)
        if database is None:
            raise MandateAuthorityError(
                "d34_mandate_unavailable", "D-34 mandate authority is unavailable"
            )
        return database

    def create(self, command: CreateMandateCommand) -> Mandate:
        _validate_command(command)
        mandate_id = f"mandate-{uuid4()}"
        policy_document = _policy_document(command)
        policy_digest = mandate_policy_digest(command)
        try:
            with self._database().connect() as conn, conn.transaction():
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"d34-mandate:{command.owner_user_id}:{command.workspace_id}",),
                )
                row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_mandates (
                        mandate_id, owner_user_id, workspace_id, status,
                        universe, hypotheses_per_cycle, max_iterations,
                        max_experiments_per_iteration, max_concurrent_jobs,
                        llm_budget_usd, llm_warning_fraction,
                        paper_execution_allowed, policy_digest, policy_document,
                        starts_at, expires_at
                    ) VALUES (
                        %s, %s, %s, 'active', %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        clock_timestamp(),
                        clock_timestamp() + make_interval(days => %s)
                    )
                    RETURNING {_MANDATE_COLUMNS}
                    """,
                    (
                        mandate_id,
                        command.owner_user_id,
                        command.workspace_id,
                        list(command.universe),
                        command.hypotheses_per_cycle,
                        command.max_iterations,
                        command.max_experiments_per_iteration,
                        command.max_concurrent_jobs,
                        command.llm_budget_usd,
                        command.llm_warning_fraction,
                        command.paper_execution_allowed,
                        policy_digest,
                        Jsonb(policy_document),
                        command.duration_days,
                    ),
                ).fetchone()
                if row is None:
                    raise RuntimeError("mandate insert returned no row")
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_mandate_events (
                        event_id, mandate_id, owner_user_id, workspace_id,
                        event_type, mandate_version, event_data
                    ) VALUES (%s, %s, %s, %s, 'created', 1, %s)
                    """,
                    (
                        f"mandate-event-{uuid4()}",
                        mandate_id,
                        command.owner_user_id,
                        command.workspace_id,
                        Jsonb({"policy_digest": policy_digest}),
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise MandateAuthorityError(
                "d34_mandate_conflict", "an active D-34 mandate already exists"
            ) from exc
        except MandateAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error, RuntimeError) as exc:
            raise MandateAuthorityError(
                "d34_mandate_unavailable", "D-34 mandate authority is unavailable"
            ) from exc
        return _mandate_from_row(row)

    def get_active(self, *, workspace_id: str) -> Mandate | None:
        if _WORKSPACE_RE.fullmatch(workspace_id) is None:
            raise MandateAuthorityError("d34_mandate_validation", "mandate workspace_id is invalid")
        try:
            with self._database().connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT {_MANDATE_COLUMNS}
                    FROM {SCHEMA}.d34_mandates
                    WHERE owner_user_id = %s
                      AND workspace_id = %s
                      AND status IN ('active', 'paused')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (ROOT_USER_ID, workspace_id),
                ).fetchone()
        except MandateAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise MandateAuthorityError(
                "d34_mandate_unavailable", "D-34 mandate authority is unavailable"
            ) from exc
        return None if row is None else _mandate_from_row(row)

    def list(self, *, workspace_id: str, limit: int) -> list[Mandate]:
        if _WORKSPACE_RE.fullmatch(workspace_id) is None or not 1 <= limit <= 100:
            raise MandateAuthorityError("d34_mandate_validation", "mandate list query is invalid")
        try:
            with self._database().connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT {_MANDATE_COLUMNS}
                    FROM {SCHEMA}.d34_mandates
                    WHERE owner_user_id = %s AND workspace_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (ROOT_USER_ID, workspace_id, limit),
                ).fetchall()
        except MandateAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise MandateAuthorityError(
                "d34_mandate_unavailable", "D-34 mandate authority is unavailable"
            ) from exc
        return [_mandate_from_row(row) for row in rows]

    def transition(
        self,
        *,
        mandate_id: str,
        action: str,
        expected_version: int,
        reason: str,
    ) -> Mandate:
        transitions = {
            "pause": ("active", "paused", "paused"),
            "resume": ("paused", "active", "resumed"),
            "revoke": (("active", "paused"), "revoked", "revoked"),
        }
        if (
            action not in transitions
            or not mandate_id.startswith("mandate-")
            or expected_version < 1
            or not 1 <= len(reason.strip()) <= 1000
        ):
            raise MandateAuthorityError("d34_mandate_validation", "mandate transition is invalid")
        source, target, event_type = transitions[action]
        source_states = (source,) if isinstance(source, str) else source
        try:
            with self._database().connect() as conn, conn.transaction():
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_mandates
                    SET status = %s,
                        updated_at = clock_timestamp(),
                        version = version + 1
                    WHERE mandate_id = %s
                      AND owner_user_id = %s
                      AND version = %s
                      AND status = ANY(%s)
                    RETURNING {_MANDATE_COLUMNS}
                    """,
                    (target, mandate_id, ROOT_USER_ID, expected_version, list(source_states)),
                ).fetchone()
                if row is None:
                    exists = conn.execute(
                        f"SELECT status, version FROM {SCHEMA}.d34_mandates "
                        "WHERE mandate_id = %s AND owner_user_id = %s",
                        (mandate_id, ROOT_USER_ID),
                    ).fetchone()
                    if exists is None:
                        raise MandateAuthorityError("d34_mandate_not_found", "mandate not found")
                    raise MandateAuthorityError(
                        "d34_mandate_conflict",
                        "mandate status or version changed; refresh before retrying",
                    )
                mandate = _mandate_from_row(row)
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_mandate_events (
                        event_id, mandate_id, owner_user_id, workspace_id,
                        event_type, mandate_version, event_data
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        f"mandate-event-{uuid4()}",
                        mandate_id,
                        ROOT_USER_ID,
                        mandate.workspace_id,
                        event_type,
                        mandate.version,
                        Jsonb({"reason": reason.strip()}),
                    ),
                )
        except MandateAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise MandateAuthorityError(
                "d34_mandate_unavailable", "D-34 mandate authority is unavailable"
            ) from exc
        return mandate


__all__ = [
    "CreateMandateCommand",
    "MANDATE_CONTRACT",
    "Mandate",
    "MandateAuthorityError",
    "MandateAuthorityPort",
    "PostgresMandateAuthority",
    "mandate_policy_digest",
]
