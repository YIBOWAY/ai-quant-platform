"""Transactional dual-engine artifact registry."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

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
class D34ComparisonSummary:
    accepted: bool
    exact_inputs: bool
    reason_codes: tuple[str, ...]
    daily_return_correlation: float
    terminal_nav_difference_bps: float
    max_symbol_weight_difference_bps: float

    def to_public_dict(self) -> dict[str, object]:
        return {
            "contract": "hqa.d34_comparison/v1",
            "accepted": self.accepted,
            "exact_inputs": self.exact_inputs,
            "reason_codes": list(self.reason_codes),
            "daily_return_correlation": self.daily_return_correlation,
            "terminal_nav_difference_bps": self.terminal_nav_difference_bps,
            "max_symbol_weight_difference_bps": (self.max_symbol_weight_difference_bps),
        }


@dataclass(frozen=True)
class D34Artifact:
    artifact_id: str
    resource_envelope_id: str
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
    comparison: D34ComparisonSummary | None = None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "contract": "hqa.d34_artifact/v2",
            **self.__dict__,
            "comparison": (
                self.comparison.to_public_dict() if self.comparison is not None else None
            ),
        }


@dataclass(frozen=True)
class RegisterArtifactCommand:
    job_id: str
    resource_envelope_id: str
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


class RegistryAuthorityPort(Protocol):
    def list_artifacts(
        self, *, workspace_id: str, limit: int
    ) -> list[D34Artifact | dict[str, object]]: ...


_ARTIFACT_COLUMNS = """
artifact_id, resource_envelope_id, workspace_id, status, qualification_scope,
policy_digest, snapshot_digest, candidate_code_digest, qlib_config_digest,
rdagent_commit, qlib_commit, docker_image_digest, qlib_receipt_digest,
platform_receipt_digest, comparison_digest, policy_decision_id,
created_at, updated_at, version
"""


def _artifact(
    row: tuple[object, ...],
    *,
    comparison: D34ComparisonSummary | None = None,
) -> D34Artifact:
    return D34Artifact(
        artifact_id=str(row[0]),
        resource_envelope_id=str(row[1]),
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
        comparison=comparison,
    )


def _comparison_summary(value: EngineComparison) -> D34ComparisonSummary:
    return D34ComparisonSummary(
        accepted=value.accepted,
        exact_inputs=value.exact_inputs,
        reason_codes=value.reason_codes,
        daily_return_correlation=value.daily_return_correlation,
        terminal_nav_difference_bps=value.terminal_nav_difference_bps,
        max_symbol_weight_difference_bps=value.max_symbol_weight_difference_bps,
    )


def _listed_comparison(row: tuple[object, ...]) -> D34ComparisonSummary:
    document = dict(row[23])  # type: ignore[arg-type]
    return D34ComparisonSummary(
        accepted=bool(row[19]),
        exact_inputs=bool(document["exact_inputs"]),
        reason_codes=tuple(str(value) for value in document["reason_codes"]),
        daily_return_correlation=float(row[20]),
        terminal_nav_difference_bps=float(row[21]),
        max_symbol_weight_difference_bps=float(row[22]),
    )


class PostgresRegistryAuthority:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def list_artifacts(self, *, workspace_id: str, limit: int) -> list[D34Artifact]:
        if _WORKSPACE_RE.fullmatch(workspace_id) is None or not 1 <= limit <= 100:
            raise RegistryAuthorityError("d34_registry_validation", "registry query is invalid")
        columns = ", ".join(
            f"artifact.{name.strip()}"
            for name in _ARTIFACT_COLUMNS.replace("\n", " ").split(",")
            if name.strip()
        )
        try:
            with self._database().connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT {columns}, comparison.accepted,
                           comparison.daily_return_correlation,
                           comparison.terminal_nav_difference_bps,
                           comparison.max_symbol_weight_difference_bps,
                           comparison.comparison_document
                    FROM {SCHEMA}.d34_artifacts AS artifact
                    JOIN {SCHEMA}.d34_comparisons AS comparison
                      ON comparison.comparison_digest = artifact.comparison_digest
                    WHERE artifact.owner_user_id = %s AND artifact.workspace_id = %s
                      AND artifact.resource_envelope_id IS NOT NULL
                    ORDER BY artifact.created_at DESC LIMIT %s
                    """,
                    (ROOT_USER_ID, workspace_id, limit),
                ).fetchall()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise RegistryAuthorityError(
                "d34_registry_unavailable", "D-34 Artifact Registry is unavailable"
            ) from exc
        return [_artifact(row[:19], comparison=_listed_comparison(row)) for row in rows]

    def get_artifact_for_job(
        self,
        *,
        workspace_id: str,
        job_id: str,
        artifact_id: str,
    ) -> D34Artifact | None:
        if (
            _WORKSPACE_RE.fullmatch(workspace_id) is None
            or not job_id.startswith("job-")
            or not artifact_id.startswith("artifact-")
        ):
            raise RegistryAuthorityError("d34_registry_validation", "registry query is invalid")
        columns = ", ".join(
            f"artifact.{name.strip()}"
            for name in _ARTIFACT_COLUMNS.replace("\n", " ").split(",")
            if name.strip()
        )
        try:
            with self._database().connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT {columns}, comparison.accepted,
                           comparison.daily_return_correlation,
                           comparison.terminal_nav_difference_bps,
                           comparison.max_symbol_weight_difference_bps,
                           comparison.comparison_document
                    FROM {SCHEMA}.d34_artifacts AS artifact
                    JOIN {SCHEMA}.d34_comparisons AS comparison
                      ON comparison.comparison_digest = artifact.comparison_digest
                    WHERE artifact.owner_user_id = %s
                      AND artifact.workspace_id = %s
                      AND artifact.job_id = %s
                      AND artifact.artifact_id = %s
                      AND artifact.resource_envelope_id IS NOT NULL
                    """,
                    (ROOT_USER_ID, workspace_id, job_id, artifact_id),
                ).fetchone()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise RegistryAuthorityError(
                "d34_registry_unavailable", "D-34 Artifact Registry is unavailable"
            ) from exc
        return None if row is None else _artifact(row[:19], comparison=_listed_comparison(row))

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
            or _WORKSPACE_RE.fullmatch(command.resource_envelope_id) is None
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

    def record_artifact_evaluation(self, command: RegisterArtifactCommand) -> ArtifactEvaluation:
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
                    SELECT resource_envelope_id, owner_user_id, workspace_id, state
                    FROM {SCHEMA}.d34_experiment_jobs
                    WHERE job_id = %s FOR UPDATE
                    """,
                    (command.job_id,),
                ).fetchone()
                if (
                    job is None
                    or str(job[0]) != command.resource_envelope_id
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
                            receipt_id, job_id, mandate_id, resource_envelope_id,
                            owner_user_id, workspace_id,
                            engine, snapshot_digest, universe_digest, calendar_digest,
                            target_weights_digest, receipt_digest, receipt_document
                        ) VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (receipt_id) DO NOTHING
                        """,
                        (
                            receipt_id,
                            command.job_id,
                            command.resource_envelope_id,
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
                        resource_envelope_id,
                        subject_kind, subject_id, policy_digest, outcome,
                        reason_codes, input_digest, decision_document
                    ) VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (decision_id) DO NOTHING
                    """,
                    (
                        decision_id,
                        ROOT_USER_ID,
                        command.workspace_id,
                        command.resource_envelope_id,
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
                    "contract": "hqa.d34_artifact/v2",
                    "job_id": command.job_id,
                    "resource_envelope_id": command.resource_envelope_id,
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
                        artifact_id, job_id, mandate_id, resource_envelope_id,
                        owner_user_id, workspace_id,
                        status, qualification_scope, policy_digest, snapshot_digest,
                        candidate_code_digest, qlib_config_digest, rdagent_commit,
                        qlib_commit, docker_image_digest, qlib_receipt_digest,
                        platform_receipt_digest, comparison_digest, policy_decision_id,
                        artifact_document
                    ) VALUES (
                        %s, %s, NULL, %s, %s, %s, 'qualified', 'paper_only', %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) ON CONFLICT (artifact_id) DO NOTHING
                    RETURNING {_ARTIFACT_COLUMNS}
                    """,
                    (
                        artifact_id,
                        command.job_id,
                        command.resource_envelope_id,
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
                artifact = _artifact(row, comparison=_comparison_summary(comparison))
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
                        Jsonb({"comparison_digest": comparison.comparison_digest}),
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


__all__ = [
    "D34Artifact",
    "ArtifactEvaluation",
    "PostgresRegistryAuthority",
    "RegisterArtifactCommand",
    "RegistryAuthorityError",
    "RegistryAuthorityPort",
]
