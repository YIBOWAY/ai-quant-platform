"""Digest-bound final acceptance for the D-34 default-research cutover."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from quant_system.config.settings import Settings
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.factors.registry import build_factor_registry
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.d34_safety_authority import D34SafetyAuthority
from quant_system.storage.database import SCHEMA, get_database

FINAL_ACCEPTANCE_CONTRACT = "hqa.d34_final_acceptance/v1"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def evaluate_final_acceptance(
    *,
    workspace_id: str,
    observed_at: datetime,
    safety: Mapping[str, object],
    database_facts: Mapping[str, object],
    paper_facts: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate every final cutover invariant and bind the facts to one digest."""
    if (
        not workspace_id
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
        or safety.get("contract") != "hqa.effective_paper_safety/v2"
        or safety.get("workspace_id") != workspace_id
    ):
        raise ValueError("d34_final_acceptance_input_invalid")
    d34 = safety.get("d34")
    soak = safety.get("soak")
    emergency = safety.get("emergency_stop")
    budget = safety.get("budget")
    risk = safety.get("risk")
    duplicates = database_facts.get("duplicate_groups")
    if not all(
        isinstance(value, Mapping) for value in (d34, soak, emergency, budget, risk, duplicates)
    ):
        raise ValueError("d34_final_acceptance_input_invalid")

    blockers: list[str] = []
    if soak.get("time_gate_ready") is not True:
        blockers.append("d34_time_gate_not_ready")
    if safety.get("live_execution_enabled") is not False:
        blockers.append("live_execution_not_disabled")
    if emergency.get("active") is True:
        blockers.append("emergency_stop_active")
    if safety.get("paper_execution_enabled") is not True:
        blockers.append("paper_execution_not_enabled")
    if int(d34.get("queued_jobs", -1)) != 0 or int(d34.get("running_jobs", -1)) != 0:
        blockers.append("d34_jobs_not_quiescent")
    try:
        spent = Decimal(str(budget.get("spent_usd")))
        limit = Decimal(str(budget.get("limit_usd")))
        nav_fraction = Decimal(str(database_facts.get("active_canary_nav_fraction")))
        max_nav_fraction = Decimal(str(risk.get("max_total_nav_fraction")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("d34_final_acceptance_input_invalid") from exc
    if spent > limit:
        blockers.append("d34_budget_exceeded")
    if nav_fraction > max_nav_fraction:
        blockers.append("d34_paper_exposure_exceeded")

    for name, count in sorted(duplicates.items()):
        if type(name) is not str or type(count) is not int or count < 0:
            raise ValueError("d34_final_acceptance_input_invalid")
        if count:
            blockers.append(f"duplicate_{name}")
    for field, code in (
        ("non_paper_artifacts", "d34_non_paper_artifact"),
        ("artifact_policy_lineage_mismatches", "d34_policy_lineage_mismatch"),
    ):
        count = database_facts.get(field)
        if type(count) is not int or count < 0:
            raise ValueError("d34_final_acceptance_input_invalid")
        if count:
            blockers.append(code)
    for field, code in (
        ("duplicate_signal_ids", "duplicate_d34_signal_id"),
        ("duplicate_execution_ids", "duplicate_d34_execution_id"),
        ("duplicate_order_batches", "duplicate_d34_order_batch"),
        ("live_registry_factor_matches", "d34_factor_present_in_live_registry"),
        ("missing_factor_ids", "d34_sleeve_factor_identity_missing"),
        ("pending_execution_journals", "d34_pending_execution_journal"),
        ("corrupt_execution_journals", "d34_corrupt_execution_journal"),
        ("non_paper_only_sleeves", "d34_non_paper_only_sleeve"),
    ):
        count = paper_facts.get(field)
        if type(count) is not int or count < 0:
            raise ValueError("d34_final_acceptance_input_invalid")
        if count:
            blockers.append(code)

    completed_cycles = soak.get("completed_cycles")
    if type(completed_cycles) is not int:
        raise ValueError("d34_final_acceptance_input_invalid")
    for field in ("jobs", "artifacts", "canaries", "policy_decisions"):
        count = database_facts.get(field)
        if type(count) is not int or count < 0:
            raise ValueError("d34_final_acceptance_input_invalid")
        if field in {"artifacts", "canaries"} and count < completed_cycles:
            blockers.append(f"d34_{field}_below_completed_cycles")

    document: dict[str, object] = {
        "contract": FINAL_ACCEPTANCE_CONTRACT,
        "workspace_id": workspace_id,
        "observed_at": observed_at.isoformat(),
        "accepted": not blockers,
        "blockers": list(dict.fromkeys(blockers)),
        "live_execution_enabled": safety.get("live_execution_enabled"),
        "soak": dict(soak),
        "budget": dict(budget),
        "risk": dict(risk),
        "database_facts": dict(database_facts),
        "paper_facts": dict(paper_facts),
    }
    document["receipt_digest"] = hashlib.sha256(_canonical_bytes(document)).hexdigest()
    return document


class D34FinalAcceptanceAuditor:
    """Read formal authorities and local paper journals into one receipt."""

    def __init__(
        self,
        settings: Settings,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self.settings = settings
        self.now = now
        self.receipt_path = settings.data.data_dir / "d34" / "acceptance" / "latest.json"

    def audit(self, *, workspace_id: str) -> dict[str, object]:
        safety = D34SafetyAuthority(self.settings).observe(workspace_id=workspace_id)
        database_facts = self._database_facts(workspace_id=workspace_id)
        paper_facts = self._paper_facts()
        return evaluate_final_acceptance(
            workspace_id=workspace_id,
            observed_at=self.now(),
            safety=safety,
            database_facts=database_facts,
            paper_facts=paper_facts,
        )

    def write(self, receipt: Mapping[str, object]) -> Path:
        verify_final_acceptance_receipt(
            receipt,
            expected_digest=str(receipt.get("receipt_digest", "")),
            workspace_id=str(receipt.get("workspace_id", "")),
            require_accepted=False,
        )
        self.receipt_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.receipt_path.with_name(f".{self.receipt_path.name}.tmp")
        temporary.write_bytes(_canonical_bytes(receipt) + b"\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.receipt_path)
        return self.receipt_path

    def _database_facts(self, *, workspace_id: str) -> dict[str, object]:
        database = get_database(self.settings)
        if database is None:
            raise RuntimeError("d34_final_acceptance_database_unavailable")
        params = (ROOT_USER_ID, workspace_id)
        counts: dict[str, int] = {}
        count_tables = {
            "jobs": "d34_experiment_jobs",
            "artifacts": "d34_artifacts",
            "canaries": "d34_canaries",
            "policy_decisions": "d34_policy_decisions",
        }
        with database.connect() as conn:
            for name, table in count_tables.items():
                counts[name] = int(
                    conn.execute(
                        f"SELECT count(*) FROM {SCHEMA}.{table} "
                        "WHERE owner_user_id = %s AND workspace_id = %s",
                        params,
                    ).fetchone()[0]
                )
            duplicate_queries = {
                "jobs_job_key": f"""
                    SELECT count(*) FROM (
                        SELECT mandate_id, job_key FROM {SCHEMA}.d34_experiment_jobs
                        WHERE owner_user_id = %s AND workspace_id = %s
                        GROUP BY mandate_id, job_key HAVING count(*) > 1
                    ) duplicate_groups
                """,
                "artifact_job": f"""
                    SELECT count(*) FROM (
                        SELECT job_id FROM {SCHEMA}.d34_artifacts
                        WHERE owner_user_id = %s AND workspace_id = %s
                        GROUP BY job_id HAVING count(*) > 1
                    ) duplicate_groups
                """,
                "canary_artifact": f"""
                    SELECT count(*) FROM (
                        SELECT artifact_id FROM {SCHEMA}.d34_canaries
                        WHERE owner_user_id = %s AND workspace_id = %s
                        GROUP BY artifact_id HAVING count(*) > 1
                    ) duplicate_groups
                """,
                "canary_sleeve": f"""
                    SELECT count(*) FROM (
                        SELECT sleeve_id FROM {SCHEMA}.d34_canaries
                        WHERE owner_user_id = %s AND workspace_id = %s
                        GROUP BY sleeve_id HAVING count(*) > 1
                    ) duplicate_groups
                """,
                "policy_identity": f"""
                    SELECT count(*) FROM (
                        SELECT subject_kind, subject_id, policy_digest, input_digest
                        FROM {SCHEMA}.d34_policy_decisions
                        WHERE owner_user_id = %s AND workspace_id = %s
                        GROUP BY subject_kind, subject_id, policy_digest, input_digest
                        HAVING count(*) > 1
                    ) duplicate_groups
                """,
                "budget_consumption": f"""
                    SELECT count(*) FROM (
                        SELECT events.job_id, events.attempt_id,
                               events.provider_receipt_digest
                        FROM {SCHEMA}.d34_budget_events events
                        JOIN {SCHEMA}.d34_experiment_jobs jobs
                          ON jobs.job_id = events.job_id
                        WHERE jobs.owner_user_id = %s AND jobs.workspace_id = %s
                          AND events.event_type = 'consumed'
                        GROUP BY events.job_id, events.attempt_id,
                                 events.provider_receipt_digest
                        HAVING count(*) > 1
                    ) duplicate_groups
                """,
            }
            duplicates = {
                name: int(conn.execute(query, params).fetchone()[0])
                for name, query in duplicate_queries.items()
            }
            non_paper = int(
                conn.execute(
                    f"SELECT count(*) FROM {SCHEMA}.d34_artifacts "
                    "WHERE owner_user_id = %s AND workspace_id = %s "
                    "AND qualification_scope <> 'paper_only'",
                    params,
                ).fetchone()[0]
            )
            policy_mismatches = int(
                conn.execute(
                    f"""
                    SELECT count(*) FROM {SCHEMA}.d34_artifacts artifacts
                    JOIN {SCHEMA}.d34_policy_decisions decisions
                      ON decisions.decision_id = artifacts.policy_decision_id
                    WHERE artifacts.owner_user_id = %s
                      AND artifacts.workspace_id = %s
                      AND (
                        decisions.subject_kind <> 'artifact'
                        OR decisions.subject_id <> artifacts.artifact_id
                        OR decisions.outcome <> 'accepted'
                      )
                    """,
                    params,
                ).fetchone()[0]
            )
            nav_fraction = Decimal(
                str(
                    conn.execute(
                        f"""
                        SELECT COALESCE(sum(nav_fraction), 0)
                        FROM {SCHEMA}.d34_canaries
                        WHERE owner_user_id = %s AND workspace_id = %s
                          AND status IN ('provisioning', 'running', 'paused')
                        """,
                        params,
                    ).fetchone()[0]
                )
            )
        return {
            **counts,
            "active_canary_nav_fraction": f"{nav_fraction:.9f}",
            "non_paper_artifacts": non_paper,
            "artifact_policy_lineage_mismatches": policy_mismatches,
            "duplicate_groups": duplicates,
        }

    def _paper_facts(self) -> dict[str, object]:
        storage = PaperStrategySleeveStorage(self.settings.data.data_dir / "api_runs")
        sleeves = [
            sleeve
            for sleeve in storage.list_sleeves()
            if sleeve.metadata.get("automation_source") == "d34"
        ]
        signal_ids: list[str] = []
        execution_ids: list[str] = []
        execution_signal_links: list[tuple[str, str]] = []
        factor_ids: set[str] = set()
        pending, corrupt, non_paper, missing_factor_ids = 0, 0, 0, 0
        for sleeve in sleeves:
            factor_id = sleeve.metadata.get("factor_id")
            if isinstance(factor_id, str) and factor_id:
                factor_ids.add(factor_id)
            else:
                missing_factor_ids += 1
            signal_ids.extend(signal.signal_id for signal in storage.load_signals(sleeve.sleeve_id))
            executions = storage.load_executions(sleeve.sleeve_id)
            execution_ids.extend(execution.execution_id for execution in executions)
            execution_signal_links.extend(
                (execution.sleeve_id, execution.signal_id) for execution in executions
            )
            journal_dir = storage.execution_journal_dir(sleeve.sleeve_id)
            if journal_dir.exists():
                pending += sum(1 for path in journal_dir.glob("*.pending.json") if path.is_file())
                corrupt += sum(1 for path in journal_dir.glob("*.corrupt-*.json") if path.is_file())
            if sleeve.metadata.get("promotion_scope") != "paper_only":
                non_paper += 1
        live_factor_ids = set(build_factor_registry(purpose="live").factor_ids())
        return {
            "d34_sleeves": len(sleeves),
            "signals": len(signal_ids),
            "executions": len(execution_ids),
            "duplicate_signal_ids": len(signal_ids) - len(set(signal_ids)),
            "duplicate_execution_ids": len(execution_ids) - len(set(execution_ids)),
            "duplicate_order_batches": len(execution_signal_links)
            - len(set(execution_signal_links)),
            "live_registry_factor_matches": len(factor_ids & live_factor_ids),
            "missing_factor_ids": missing_factor_ids,
            "pending_execution_journals": pending,
            "corrupt_execution_journals": corrupt,
            "non_paper_only_sleeves": non_paper,
        }


def verify_final_acceptance_receipt(
    receipt: Mapping[str, object],
    *,
    expected_digest: str,
    workspace_id: str,
    require_accepted: bool = True,
) -> None:
    soak = receipt.get("soak")
    if (
        receipt.get("contract") != FINAL_ACCEPTANCE_CONTRACT
        or receipt.get("workspace_id") != workspace_id
        or receipt.get("receipt_digest") != expected_digest
        or (
            require_accepted
            and (
                receipt.get("accepted") is not True
                or receipt.get("blockers") != []
                or receipt.get("live_execution_enabled") is not False
                or not isinstance(soak, Mapping)
                or soak.get("time_gate_ready") is not True
            )
        )
    ):
        raise ValueError("d34_final_acceptance_receipt_invalid")
    unsigned = dict(receipt)
    unsigned.pop("receipt_digest", None)
    actual = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
    if actual != expected_digest:
        raise ValueError("d34_final_acceptance_receipt_invalid")


def verify_current_acceptance(
    receipt: Mapping[str, object],
    current: Mapping[str, object],
) -> None:
    """Reject a cutover when any accepted fact changed after receipt creation."""
    if (
        receipt.get("accepted") is not True
        or current.get("accepted") is not True
        or receipt.get("blockers") != []
        or current.get("blockers") != []
    ):
        raise ValueError("d34_final_acceptance_not_current")
    for field in (
        "live_execution_enabled",
        "soak",
        "budget",
        "risk",
        "database_facts",
        "paper_facts",
    ):
        if receipt.get(field) != current.get(field):
            raise ValueError("d34_final_acceptance_facts_changed")


__all__ = [
    "D34FinalAcceptanceAuditor",
    "FINAL_ACCEPTANCE_CONTRACT",
    "evaluate_final_acceptance",
    "verify_current_acceptance",
    "verify_final_acceptance_receipt",
]
