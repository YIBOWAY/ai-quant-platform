"""Transactional D-34 Artifact Registry and paper canary lifecycle."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from quant_system.config.settings import Settings
from quant_system.d34.engine_comparison import EngineComparison, EngineReceipt
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import SCHEMA, DatabaseUnavailable, get_database

_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class RegistryAuthorityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class D34Artifact:
    artifact_id: str
    mandate_id: str
    workspace_id: str
    status: str
    qualification_scope: str
    policy_digest: str
    snapshot_digest: str
    candidate_code_digest: str
    qlib_config_digest: str
    rdagent_commit: str
    qlib_commit: str
    docker_image_digest: str
    qlib_receipt_digest: str
    platform_receipt_digest: str
    comparison_digest: str
    policy_decision_id: str
    created_at: datetime
    updated_at: datetime
    version: int

    def to_public_dict(self) -> dict[str, object]:
        return {"contract": "hqa.d34_artifact/v1", **self.__dict__}


@dataclass(frozen=True)
class D34Canary:
    canary_id: str
    artifact_id: str
    mandate_id: str
    workspace_id: str
    sleeve_id: str
    status: str
    allocated_cash: Decimal
    nav_fraction: Decimal
    daily_pnl: Decimal
    drawdown_fraction: Decimal
    created_at: datetime
    updated_at: datetime
    version: int

    def to_public_dict(self) -> dict[str, object]:
        return {
            "contract": "hqa.d34_canary/v1",
            **self.__dict__,
            "allocated_cash": f"{self.allocated_cash:.2f}",
            "nav_fraction": f"{self.nav_fraction:.6f}",
            "daily_pnl": f"{self.daily_pnl:.2f}",
            "drawdown_fraction": f"{self.drawdown_fraction:.6f}",
        }


@dataclass(frozen=True)
class RegisterArtifactCommand:
    job_id: str
    mandate_id: str
    workspace_id: str
    qlib_receipt: EngineReceipt
    platform_receipt: EngineReceipt
    comparison: EngineComparison
    candidate_code_digest: str
    qlib_config_digest: str
    rdagent_commit: str
    qlib_commit: str
    docker_image_digest: str


@dataclass(frozen=True)
class ArtifactEvaluation:
    decision_id: str
    accepted: bool
    artifact: D34Artifact | None


@dataclass(frozen=True)
class ProvisionCanaryCommand:
    artifact_id: str
    sleeve_id: str
    nav: Decimal
    allocated_cash: Decimal
    workspace_id: str


class RegistryAuthorityPort(Protocol):
    def get_canary(
        self, canary_id: str
    ) -> D34Canary | dict[str, object]: ...

    def list_artifacts(
        self, *, workspace_id: str, limit: int
    ) -> list[D34Artifact | dict[str, object]]: ...

    def list_canaries(
        self, *, workspace_id: str, limit: int
    ) -> list[D34Canary | dict[str, object]]: ...

    def provision_canary(
        self, command: ProvisionCanaryCommand
    ) -> D34Canary | dict[str, object]: ...

    def transition_canary(
        self,
        *,
        canary_id: str,
        action: str,
        expected_version: int,
        reason: str,
    ) -> D34Canary | dict[str, object]: ...


_ARTIFACT_COLUMNS = """
artifact_id, mandate_id, workspace_id, status, qualification_scope,
policy_digest, snapshot_digest, candidate_code_digest, qlib_config_digest,
rdagent_commit, qlib_commit, docker_image_digest, qlib_receipt_digest,
platform_receipt_digest, comparison_digest, policy_decision_id,
created_at, updated_at, version
"""
_CANARY_COLUMNS = """
canary_id, artifact_id, mandate_id, workspace_id, sleeve_id, status,
allocated_cash, nav_fraction, daily_pnl, drawdown_fraction,
created_at, updated_at, version
"""


def _artifact(row: tuple[object, ...]) -> D34Artifact:
    return D34Artifact(
        artifact_id=str(row[0]),
        mandate_id=str(row[1]),
        workspace_id=str(row[2]),
        status=str(row[3]),
        qualification_scope=str(row[4]),
        policy_digest=str(row[5]),
        snapshot_digest=str(row[6]),
        candidate_code_digest=str(row[7]),
        qlib_config_digest=str(row[8]),
        rdagent_commit=str(row[9]),
        qlib_commit=str(row[10]),
        docker_image_digest=str(row[11]),
        qlib_receipt_digest=str(row[12]),
        platform_receipt_digest=str(row[13]),
        comparison_digest=str(row[14]),
        policy_decision_id=str(row[15]),
        created_at=row[16],  # type: ignore[arg-type]
        updated_at=row[17],  # type: ignore[arg-type]
        version=int(row[18]),
    )


def _canary(row: tuple[object, ...]) -> D34Canary:
    return D34Canary(
        canary_id=str(row[0]),
        artifact_id=str(row[1]),
        mandate_id=str(row[2]),
        workspace_id=str(row[3]),
        sleeve_id=str(row[4]),
        status=str(row[5]),
        allocated_cash=Decimal(str(row[6])),
        nav_fraction=Decimal(str(row[7])),
        daily_pnl=Decimal(str(row[8])),
        drawdown_fraction=Decimal(str(row[9])),
        created_at=row[10],  # type: ignore[arg-type]
        updated_at=row[11],  # type: ignore[arg-type]
        version=int(row[12]),
    )


class PostgresRegistryAuthority:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _list(self, *, table: str, columns: str, workspace_id: str, limit: int):
        if _WORKSPACE_RE.fullmatch(workspace_id) is None or not 1 <= limit <= 100:
            raise RegistryAuthorityError("d34_registry_validation", "registry query is invalid")
        database = get_database(self._settings)
        if database is None:
            raise RegistryAuthorityError(
                "d34_registry_unavailable", "D-34 Artifact Registry is unavailable"
            )
        try:
            with database.connect() as conn:
                return conn.execute(
                    f"""
                    SELECT {columns} FROM {SCHEMA}.{table}
                    WHERE owner_user_id = %s AND workspace_id = %s
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (ROOT_USER_ID, workspace_id, limit),
                ).fetchall()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise RegistryAuthorityError(
                "d34_registry_unavailable", "D-34 Artifact Registry is unavailable"
            ) from exc

    def list_artifacts(self, *, workspace_id: str, limit: int) -> list[D34Artifact]:
        rows = self._list(
            table="d34_artifacts",
            columns=_ARTIFACT_COLUMNS,
            workspace_id=workspace_id,
            limit=limit,
        )
        return [_artifact(row) for row in rows]

    def list_canaries(self, *, workspace_id: str, limit: int) -> list[D34Canary]:
        rows = self._list(
            table="d34_canaries",
            columns=_CANARY_COLUMNS,
            workspace_id=workspace_id,
            limit=limit,
        )
        return [_canary(row) for row in rows]

    def get_canary(self, canary_id: str) -> D34Canary:
        if not canary_id.startswith("canary-") or len(canary_id) > 256:
            raise RegistryAuthorityError(
                "d34_registry_validation", "canary id is invalid"
            )
        try:
            with self._database().connect() as conn:
                row = conn.execute(
                    f"SELECT {_CANARY_COLUMNS} FROM {SCHEMA}.d34_canaries "
                    "WHERE canary_id = %s AND owner_user_id = %s",
                    (canary_id, ROOT_USER_ID),
                ).fetchone()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise RegistryAuthorityError(
                "d34_registry_unavailable", "D-34 Artifact Registry is unavailable"
            ) from exc
        if row is None:
            raise RegistryAuthorityError("d34_registry_not_found", "canary not found")
        return _canary(row)

    def _database(self):
        database = get_database(self._settings)
        if database is None:
            raise RegistryAuthorityError(
                "d34_registry_unavailable", "D-34 Artifact Registry is unavailable"
            )
        return database

    @staticmethod
    def _validate_registration(command: RegisterArtifactCommand) -> None:
        qlib, platform, comparison = (
            command.qlib_receipt,
            command.platform_receipt,
            command.comparison,
        )
        if (
            not command.job_id.startswith("job-")
            or not command.mandate_id.startswith("mandate-")
            or _WORKSPACE_RE.fullmatch(command.workspace_id) is None
            or qlib.engine != "qlib"
            or platform.engine != "platform"
            or comparison.qlib_receipt_digest != qlib.receipt_digest
            or comparison.platform_receipt_digest != platform.receipt_digest
            or any(
                _DIGEST_RE.fullmatch(value) is None
                for value in (
                    command.candidate_code_digest,
                    command.qlib_config_digest,
                    comparison.policy_digest,
                    comparison.comparison_digest,
                )
            )
            or _COMMIT_RE.fullmatch(command.rdagent_commit) is None
            or _COMMIT_RE.fullmatch(command.qlib_commit) is None
            or _IMAGE_RE.fullmatch(command.docker_image_digest) is None
        ):
            raise RegistryAuthorityError(
                "d34_registry_validation", "artifact evaluation is invalid"
            )
        if comparison.accepted and not comparison.exact_inputs:
            raise RegistryAuthorityError(
                "d34_registry_validation", "accepted comparison does not bind exact inputs"
            )

    @staticmethod
    def _receipt_id(receipt: EngineReceipt) -> str:
        return f"receipt-{receipt.engine}-{receipt.receipt_digest[:32]}"

    def record_artifact_evaluation(
        self, command: RegisterArtifactCommand
    ) -> ArtifactEvaluation:
        """Atomically persist both engines, comparison, policy and artifact."""
        self._validate_registration(command)
        qlib, platform, comparison = (
            command.qlib_receipt,
            command.platform_receipt,
            command.comparison,
        )
        qlib_id, platform_id = self._receipt_id(qlib), self._receipt_id(platform)
        comparison_id = f"comparison-{comparison.comparison_digest[:32]}"
        decision_id = f"decision-{comparison.comparison_digest[:32]}"
        artifact_id = f"artifact-{comparison.comparison_digest[:32]}"
        outcome = "accepted" if comparison.accepted else "rejected"
        expected_job_state = "succeeded" if comparison.accepted else "rejected"
        try:
            with self._database().connect() as conn, conn.transaction():
                job = conn.execute(
                    f"""
                    SELECT mandate_id, owner_user_id, workspace_id, state
                    FROM {SCHEMA}.d34_experiment_jobs
                    WHERE job_id = %s FOR UPDATE
                    """,
                    (command.job_id,),
                ).fetchone()
                if (
                    job is None
                    or str(job[0]) != command.mandate_id
                    or str(job[1]) != str(ROOT_USER_ID)
                    or str(job[2]) != command.workspace_id
                    or str(job[3]) != expected_job_state
                ):
                    raise RegistryAuthorityError(
                        "d34_registry_conflict", "research job is not eligible for evaluation"
                    )
                for receipt_id, receipt in ((qlib_id, qlib), (platform_id, platform)):
                    conn.execute(
                        f"""
                        INSERT INTO {SCHEMA}.d34_engine_receipts (
                            receipt_id, job_id, mandate_id, owner_user_id, workspace_id,
                            engine, snapshot_digest, universe_digest, calendar_digest,
                            target_weights_digest, receipt_digest, receipt_document
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (receipt_id) DO NOTHING
                        """,
                        (
                            receipt_id,
                            command.job_id,
                            command.mandate_id,
                            ROOT_USER_ID,
                            command.workspace_id,
                            receipt.engine,
                            receipt.snapshot_digest,
                            receipt.universe_digest,
                            receipt.calendar_digest,
                            receipt.target_weights_digest,
                            receipt.receipt_digest,
                            Jsonb(asdict(receipt)),
                        ),
                    )
                    observed = conn.execute(
                        f"""
                        SELECT job_id, engine, receipt_digest
                        FROM {SCHEMA}.d34_engine_receipts WHERE receipt_id = %s
                        """,
                        (receipt_id,),
                    ).fetchone()
                    if observed != (command.job_id, receipt.engine, receipt.receipt_digest):
                        raise RegistryAuthorityError(
                            "d34_registry_conflict", "engine receipt identity collision"
                        )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_comparisons (
                        comparison_id, job_id, qlib_receipt_id, platform_receipt_id,
                        policy_digest, comparison_digest, accepted,
                        daily_return_correlation, terminal_nav_difference_bps,
                        max_symbol_weight_difference_bps, comparison_document
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (comparison_id) DO NOTHING
                    """,
                    (
                        comparison_id,
                        command.job_id,
                        qlib_id,
                        platform_id,
                        comparison.policy_digest,
                        comparison.comparison_digest,
                        comparison.accepted,
                        comparison.daily_return_correlation,
                        comparison.terminal_nav_difference_bps,
                        comparison.max_symbol_weight_difference_bps,
                        Jsonb(asdict(comparison)),
                    ),
                )
                observed_comparison = conn.execute(
                    f"""
                    SELECT job_id, comparison_digest, accepted
                    FROM {SCHEMA}.d34_comparisons WHERE comparison_id = %s
                    """,
                    (comparison_id,),
                ).fetchone()
                if observed_comparison != (
                    command.job_id,
                    comparison.comparison_digest,
                    comparison.accepted,
                ):
                    raise RegistryAuthorityError(
                        "d34_registry_conflict", "comparison identity collision"
                    )
                reason_codes = list(comparison.reason_codes)
                decision_document = {
                    "contract": "hqa.d34_policy_decision/v1",
                    "comparison_digest": comparison.comparison_digest,
                    "outcome": outcome,
                    "reason_codes": reason_codes,
                }
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_policy_decisions (
                        decision_id, owner_user_id, workspace_id, mandate_id,
                        subject_kind, subject_id, policy_digest, outcome,
                        reason_codes, input_digest, decision_document
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (decision_id) DO NOTHING
                    """,
                    (
                        decision_id,
                        ROOT_USER_ID,
                        command.workspace_id,
                        command.mandate_id,
                        "artifact" if comparison.accepted else "experiment",
                        artifact_id if comparison.accepted else command.job_id,
                        comparison.policy_digest,
                        outcome,
                        reason_codes,
                        comparison.comparison_digest,
                        Jsonb(decision_document),
                    ),
                )
                observed_decision = conn.execute(
                    f"""
                    SELECT outcome, input_digest FROM {SCHEMA}.d34_policy_decisions
                    WHERE decision_id = %s
                    """,
                    (decision_id,),
                ).fetchone()
                if observed_decision != (outcome, comparison.comparison_digest):
                    raise RegistryAuthorityError(
                        "d34_registry_conflict", "policy decision identity collision"
                    )
                if not comparison.accepted:
                    return ArtifactEvaluation(
                        decision_id=decision_id,
                        accepted=False,
                        artifact=None,
                    )
                artifact_document = {
                    "contract": "hqa.d34_artifact/v1",
                    "job_id": command.job_id,
                    "mandate_id": command.mandate_id,
                    "policy_digest": comparison.policy_digest,
                    "snapshot_digest": qlib.snapshot_digest,
                    "candidate_code_digest": command.candidate_code_digest,
                    "qlib_config_digest": command.qlib_config_digest,
                    "rdagent_commit": command.rdagent_commit,
                    "qlib_commit": command.qlib_commit,
                    "docker_image_digest": command.docker_image_digest,
                    "qlib_receipt_digest": qlib.receipt_digest,
                    "platform_receipt_digest": platform.receipt_digest,
                    "comparison_digest": comparison.comparison_digest,
                    "policy_decision_id": decision_id,
                    "qualification_scope": "paper_only",
                }
                row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_artifacts (
                        artifact_id, job_id, mandate_id, owner_user_id, workspace_id,
                        status, qualification_scope, policy_digest, snapshot_digest,
                        candidate_code_digest, qlib_config_digest, rdagent_commit,
                        qlib_commit, docker_image_digest, qlib_receipt_digest,
                        platform_receipt_digest, comparison_digest, policy_decision_id,
                        artifact_document
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'qualified', 'paper_only', %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) ON CONFLICT (artifact_id) DO NOTHING
                    RETURNING {_ARTIFACT_COLUMNS}
                    """,
                    (
                        artifact_id,
                        command.job_id,
                        command.mandate_id,
                        ROOT_USER_ID,
                        command.workspace_id,
                        comparison.policy_digest,
                        qlib.snapshot_digest,
                        command.candidate_code_digest,
                        command.qlib_config_digest,
                        command.rdagent_commit,
                        command.qlib_commit,
                        command.docker_image_digest,
                        qlib.receipt_digest,
                        platform.receipt_digest,
                        comparison.comparison_digest,
                        decision_id,
                        Jsonb(artifact_document),
                    ),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        f"SELECT {_ARTIFACT_COLUMNS} FROM {SCHEMA}.d34_artifacts "
                        "WHERE artifact_id = %s",
                        (artifact_id,),
                    ).fetchone()
                if row is None or str(row[14]) != comparison.comparison_digest:
                    raise RegistryAuthorityError(
                        "d34_registry_conflict", "artifact identity collision"
                    )
                artifact = _artifact(row)
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_artifact_events (
                        event_id, artifact_id, event_type, artifact_version, event_data
                    ) VALUES (%s, %s, 'registered', %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (
                        f"artifact-event-registered-{artifact_id}",
                        artifact_id,
                        artifact.version,
                        Jsonb(
                            {"comparison_digest": comparison.comparison_digest}
                        ),
                    ),
                )
        except RegistryAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise RegistryAuthorityError(
                "d34_registry_unavailable", "D-34 Artifact Registry is unavailable"
            ) from exc
        return ArtifactEvaluation(
            decision_id=decision_id,
            accepted=True,
            artifact=artifact,
        )

    def provision_canary(self, command: ProvisionCanaryCommand) -> D34Canary:
        if (
            not command.artifact_id.startswith("artifact-")
            or not command.sleeve_id.startswith("sleeve-")
            or _WORKSPACE_RE.fullmatch(command.workspace_id) is None
            or command.nav <= 0
            or command.allocated_cash <= 0
        ):
            raise RegistryAuthorityError(
                "d34_registry_validation", "canary request is invalid"
            )
        maximum = min(Decimal("10000"), command.nav * Decimal("0.01"))
        if command.allocated_cash > maximum:
            raise RegistryAuthorityError(
                "d34_canary_limit", "single canary allocation exceeds policy"
            )
        canary_id = f"canary-{command.artifact_id.removeprefix('artifact-')}"
        try:
            with self._database().connect() as conn, conn.transaction():
                artifact = conn.execute(
                    f"""
                    SELECT mandate_id, workspace_id, status
                    FROM {SCHEMA}.d34_artifacts
                    WHERE artifact_id = %s AND owner_user_id = %s FOR UPDATE
                    """,
                    (command.artifact_id, ROOT_USER_ID),
                ).fetchone()
                if (
                    artifact is None
                    or str(artifact[1]) != command.workspace_id
                    or str(artifact[2]) not in {"qualified", "canary_active"}
                ):
                    raise RegistryAuthorityError(
                        "d34_registry_conflict", "artifact is not canary eligible"
                    )
                mandate_id = str(artifact[0])
                mandate = conn.execute(
                    f"""
                    SELECT status, paper_execution_allowed, expires_at > clock_timestamp()
                    FROM {SCHEMA}.d34_mandates WHERE mandate_id = %s FOR UPDATE
                    """,
                    (mandate_id,),
                ).fetchone()
                if mandate is None or mandate != ("active", True, True):
                    raise RegistryAuthorityError(
                        "d34_registry_conflict", "mandate does not authorize paper execution"
                    )
                daily_count = conn.execute(
                    f"""
                    SELECT count(*) FROM {SCHEMA}.d34_canaries
                    WHERE owner_user_id = %s AND workspace_id = %s
                      AND created_at::date = clock_timestamp()::date
                    """,
                    (ROOT_USER_ID, command.workspace_id),
                ).fetchone()
                if daily_count and int(daily_count[0]) >= 1:
                    existing = conn.execute(
                        f"SELECT {_CANARY_COLUMNS} FROM {SCHEMA}.d34_canaries "
                        "WHERE canary_id = %s",
                        (canary_id,),
                    ).fetchone()
                    if existing is not None and str(existing[4]) == command.sleeve_id:
                        return _canary(existing)
                    raise RegistryAuthorityError(
                        "d34_canary_limit", "daily canary quota is exhausted"
                    )
                total = conn.execute(
                    f"""
                    SELECT COALESCE(sum(allocated_cash), 0) FROM {SCHEMA}.d34_canaries
                    WHERE owner_user_id = %s AND workspace_id = %s
                      AND status IN ('provisioning', 'running', 'paused')
                    """,
                    (ROOT_USER_ID, command.workspace_id),
                ).fetchone()
                if Decimal(str(total[0] if total else 0)) + command.allocated_cash > (
                    command.nav * Decimal("0.10")
                ):
                    raise RegistryAuthorityError(
                        "d34_canary_limit", "aggregate canary allocation exceeds policy"
                    )
                document = {
                    "contract": "hqa.d34_canary/v1",
                    "artifact_id": command.artifact_id,
                    "sleeve_id": command.sleeve_id,
                    "allocated_cash": str(command.allocated_cash),
                    "nav": str(command.nav),
                }
                row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_canaries (
                        canary_id, artifact_id, mandate_id, owner_user_id, workspace_id,
                        sleeve_id, status, allocated_cash, nav_fraction, canary_document
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'running', %s, %s, %s)
                    ON CONFLICT (canary_id) DO NOTHING RETURNING {_CANARY_COLUMNS}
                    """,
                    (
                        canary_id,
                        command.artifact_id,
                        mandate_id,
                        ROOT_USER_ID,
                        command.workspace_id,
                        command.sleeve_id,
                        command.allocated_cash,
                        command.allocated_cash / command.nav,
                        Jsonb(document),
                    ),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        f"SELECT {_CANARY_COLUMNS} FROM {SCHEMA}.d34_canaries "
                        "WHERE canary_id = %s",
                        (canary_id,),
                    ).fetchone()
                if row is None or str(row[4]) != command.sleeve_id:
                    raise RegistryAuthorityError(
                        "d34_registry_conflict", "canary identity collision"
                    )
                canary = _canary(row)
                conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_artifacts
                    SET status = 'canary_active', updated_at = clock_timestamp(),
                        version = version + 1
                    WHERE artifact_id = %s AND status = 'qualified'
                    """,
                    (command.artifact_id,),
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_canary_events
                    (event_id, canary_id, event_type, canary_version, event_data)
                    VALUES (%s, %s, 'running', %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (
                        f"canary-event-running-{canary_id}",
                        canary_id,
                        canary.version,
                        Jsonb({"sleeve_id": command.sleeve_id}),
                    ),
                )
        except RegistryAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise RegistryAuthorityError(
                "d34_registry_unavailable", "D-34 Artifact Registry is unavailable"
            ) from exc
        return canary

    def transition_canary(
        self,
        *,
        canary_id: str,
        action: str,
        expected_version: int,
        reason: str,
    ) -> D34Canary:
        targets = {"pause": "paused", "demote": "demoted", "rollback": "rolled_back"}
        if (
            action not in targets
            or not canary_id.startswith("canary-")
            or expected_version < 1
            or not 1 <= len(reason.strip()) <= 1000
        ):
            raise RegistryAuthorityError(
                "d34_registry_validation", "canary transition is invalid"
            )
        target = targets[action]
        try:
            with self._database().connect() as conn, conn.transaction():
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_canaries
                    SET status = %s, updated_at = clock_timestamp(), version = version + 1
                    WHERE canary_id = %s AND owner_user_id = %s AND version = %s
                      AND status IN ('provisioning', 'running', 'paused')
                    RETURNING {_CANARY_COLUMNS}
                    """,
                    (target, canary_id, ROOT_USER_ID, expected_version),
                ).fetchone()
                if row is None:
                    raise RegistryAuthorityError(
                        "d34_registry_conflict", "canary status or version changed"
                    )
                canary = _canary(row)
                artifact_status = "paused" if target == "paused" else target
                conn.execute(
                    f"""
                    UPDATE {SCHEMA}.d34_artifacts
                    SET status = %s, updated_at = clock_timestamp(), version = version + 1
                    WHERE artifact_id = %s
                    """,
                    (artifact_status, canary.artifact_id),
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_canary_events
                    (event_id, canary_id, event_type, canary_version, event_data)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        f"canary-event-{uuid4()}",
                        canary_id,
                        target,
                        canary.version,
                        Jsonb({"reason": reason.strip()}),
                    ),
                )
        except RegistryAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise RegistryAuthorityError(
                "d34_registry_unavailable", "D-34 Artifact Registry is unavailable"
            ) from exc
        return canary


__all__ = [
    "D34Artifact",
    "D34Canary",
    "ArtifactEvaluation",
    "PostgresRegistryAuthority",
    "ProvisionCanaryCommand",
    "RegisterArtifactCommand",
    "RegistryAuthorityError",
    "RegistryAuthorityPort",
]
