"""Append-only D-34 execution-policy audit authority."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from quant_system.config.settings import Settings
from quant_system.execution.paper_execution_policy import PaperExecutionDecision
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import SCHEMA, DatabaseUnavailable, get_database

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class D34PolicyDecisionAuthorityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class RecordedOrderPolicyDecision:
    decision_id: str
    outcome: str
    input_digest: str
    decision_digest: str


class PostgresD34PolicyDecisionAuthority:
    """Persist one deterministic decision per exact D-34 order batch."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def record_order_batch(
        self,
        *,
        mandate_id: str,
        workspace_id: str,
        execution_id: str,
        decision: PaperExecutionDecision,
    ) -> RecordedOrderPolicyDecision:
        if (
            _ID_RE.fullmatch(mandate_id) is None
            or not mandate_id.startswith("mandate-")
            or _WORKSPACE_RE.fullmatch(workspace_id) is None
            or _ID_RE.fullmatch(execution_id) is None
            or decision.source != "d34"
            or len(decision.policy_digest) != 64
            or len(decision.input_digest) != 64
            or len(decision.decision_digest) != 64
        ):
            raise D34PolicyDecisionAuthorityError(
                "d34_policy_audit_validation",
                "D-34 order policy audit request is invalid",
            )
        database = get_database(self._settings)
        if database is None:
            raise D34PolicyDecisionAuthorityError(
                "d34_policy_audit_unavailable",
                "D-34 order policy audit authority is unavailable",
            )
        identity_digest = hashlib.sha256(
            f"{execution_id}\0{decision.decision_digest}".encode()
        ).hexdigest()
        decision_id = f"decision-order-{identity_digest[:32]}"
        outcome = "accepted" if decision.allowed else "rejected"
        document = {
            **decision.to_dict(),
            "contract": "hqa.d34_policy_decision/v1",
            "subject_kind": "order_batch",
            "subject_id": execution_id,
            "mandate_id": mandate_id,
            "workspace_id": workspace_id,
        }
        try:
            with database.connect() as conn, conn.transaction():
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_policy_decisions (
                        decision_id, owner_user_id, workspace_id, mandate_id,
                        subject_kind, subject_id, policy_digest, outcome,
                        reason_codes, input_digest, decision_document
                    ) VALUES (%s, %s, %s, %s, 'order_batch', %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (decision_id) DO NOTHING
                    """,
                    (
                        decision_id,
                        ROOT_USER_ID,
                        workspace_id,
                        mandate_id,
                        execution_id,
                        decision.policy_digest,
                        outcome,
                        list(decision.blockers),
                        decision.input_digest,
                        Jsonb(document),
                    ),
                )
                observed = conn.execute(
                    f"""
                    SELECT subject_kind, subject_id, policy_digest, outcome,
                           reason_codes, input_digest, decision_document
                    FROM {SCHEMA}.d34_policy_decisions
                    WHERE decision_id = %s AND owner_user_id = %s
                    """,
                    (decision_id, ROOT_USER_ID),
                ).fetchone()
                expected = (
                    "order_batch",
                    execution_id,
                    decision.policy_digest,
                    outcome,
                    list(decision.blockers),
                    decision.input_digest,
                    document,
                )
                if observed != expected:
                    raise D34PolicyDecisionAuthorityError(
                        "d34_policy_audit_conflict",
                        "D-34 order policy decision identity collision",
                    )
        except D34PolicyDecisionAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise D34PolicyDecisionAuthorityError(
                "d34_policy_audit_unavailable",
                "D-34 order policy audit authority is unavailable",
            ) from exc
        return RecordedOrderPolicyDecision(
            decision_id=decision_id,
            outcome=outcome,
            input_digest=decision.input_digest,
            decision_digest=decision.decision_digest,
        )


__all__ = [
    "D34PolicyDecisionAuthorityError",
    "PostgresD34PolicyDecisionAuthority",
    "RecordedOrderPolicyDecision",
]
