"""Provider-free effective D-34 research and paper execution authority."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import psycopg

from quant_system.config.settings import Settings
from quant_system.execution.paper_execution_policy import PaperExecutionLimits
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.paper_safety_authority import PaperSafetyAuthority
from quant_system.storage.database import SCHEMA, DatabaseUnavailable, get_database

_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class D34SafetyAuthorityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class D34SafetyAuthority:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _database(self):
        database = get_database(self._settings)
        if database is None:
            raise D34SafetyAuthorityError(
                "d34_safety_unavailable", "D-34 safety authority is unavailable"
            )
        return database

    def observe(self, *, workspace_id: str) -> dict[str, object]:
        if _WORKSPACE_RE.fullmatch(workspace_id) is None:
            raise D34SafetyAuthorityError(
                "d34_safety_validation", "workspace_id is invalid"
            )
        blockers: list[str] = []
        canonical = PaperSafetyAuthority(self._settings).observe(workspace_id)
        blockers.extend(canonical.blockers)
        mandate_payload: dict[str, object] | None = None
        emergency = {"active": False, "reason": None, "created_at": None}
        job_counts = {"queued": 0, "running": 0}
        active_canaries, allocated_cash, new_today = 0, Decimal("0"), 0
        budget = {
            "limit_usd": None,
            "spent_usd": None,
            "remaining_usd": None,
            "warning_fraction": None,
            "warning": False,
        }
        paper_event_enabled: bool | None = None
        try:
            with self._database().connect() as conn:
                mandate = conn.execute(
                    f"""
                    SELECT mandate_id, status, expires_at, paper_execution_allowed,
                           llm_budget_usd, llm_spent_usd, llm_warning_fraction
                    FROM {SCHEMA}.d34_mandates
                    WHERE owner_user_id = %s AND workspace_id = %s
                      AND status IN ('active', 'paused')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (ROOT_USER_ID, workspace_id),
                ).fetchone()
                now = datetime.now(UTC)
                if mandate is not None:
                    expires_at = mandate[2]
                    remaining = max(0, int((expires_at - now).total_seconds()))
                    mandate_payload = {
                        "mandate_id": str(mandate[0]),
                        "status": str(mandate[1]),
                        "expires_at": expires_at,
                        "remaining_seconds": remaining,
                        "paper_execution_allowed": bool(mandate[3]),
                    }
                    limit, spent, warning_fraction = (
                        Decimal(str(mandate[4])),
                        Decimal(str(mandate[5])),
                        Decimal(str(mandate[6])),
                    )
                    budget = {
                        "limit_usd": f"{limit:.2f}",
                        "spent_usd": f"{spent:.6f}",
                        "remaining_usd": f"{max(Decimal('0'), limit - spent):.6f}",
                        "warning_fraction": f"{warning_fraction:.6f}",
                        "warning": spent >= limit * warning_fraction,
                    }
                emergency_row = conn.execute(
                    f"""
                    SELECT enabled, reason, created_at
                    FROM {SCHEMA}.d34_execution_authority_events
                    WHERE owner_user_id = %s AND workspace_id = %s
                      AND event_type = 'emergency_stop'
                    ORDER BY event_seq DESC LIMIT 1
                    """,
                    (ROOT_USER_ID, workspace_id),
                ).fetchone()
                if emergency_row is not None:
                    emergency = {
                        "active": bool(emergency_row[0]),
                        "reason": str(emergency_row[1]),
                        "created_at": emergency_row[2],
                    }
                paper_event = conn.execute(
                    f"""
                    SELECT enabled FROM {SCHEMA}.d34_execution_authority_events
                    WHERE owner_user_id = %s AND workspace_id = %s
                      AND event_type = 'paper_execution'
                    ORDER BY event_seq DESC LIMIT 1
                    """,
                    (ROOT_USER_ID, workspace_id),
                ).fetchone()
                paper_event_enabled = None if paper_event is None else bool(paper_event[0])
                counts = conn.execute(
                    f"""
                    SELECT
                        count(*) FILTER (WHERE state = 'queued'),
                        count(*) FILTER (WHERE state IN ('leased', 'running'))
                    FROM {SCHEMA}.d34_experiment_jobs
                    WHERE owner_user_id = %s AND workspace_id = %s
                    """,
                    (ROOT_USER_ID, workspace_id),
                ).fetchone()
                if counts is not None:
                    job_counts = {"queued": int(counts[0]), "running": int(counts[1])}
                canary_row = conn.execute(
                    f"""
                    SELECT
                        count(*) FILTER (
                            WHERE status IN ('provisioning', 'running', 'paused')
                        ),
                        COALESCE(sum(allocated_cash) FILTER (
                            WHERE status IN ('provisioning', 'running', 'paused')
                        ), 0),
                        count(*) FILTER (WHERE created_at::date = clock_timestamp()::date)
                    FROM {SCHEMA}.d34_canaries
                    WHERE owner_user_id = %s AND workspace_id = %s
                    """,
                    (ROOT_USER_ID, workspace_id),
                ).fetchone()
                if canary_row is not None:
                    active_canaries = int(canary_row[0])
                    allocated_cash = Decimal(str(canary_row[1]))
                    new_today = int(canary_row[2])
        except D34SafetyAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error):
            blockers.append("d34_authority_unavailable")

        if mandate_payload is None:
            blockers.append("d34_mandate_inactive")
        else:
            if mandate_payload["status"] != "active":
                blockers.append("d34_mandate_paused")
            if int(mandate_payload["remaining_seconds"]) <= 0:
                blockers.append("d34_mandate_expired")
            if mandate_payload["paper_execution_allowed"] is not True:
                blockers.append("d34_mandate_paper_execution_not_allowed")
        if emergency["active"] is True:
            blockers.append("emergency_stop_active")
        if paper_event_enabled is False:
            blockers.append("d34_paper_execution_disabled")
        if self._settings.safety.paper_trading is not True:
            blockers.append("paper_trading_disabled")
        ordered = tuple(dict.fromkeys(blockers))
        limits = PaperExecutionLimits()
        return {
            "contract": "hqa.effective_paper_safety/v2",
            "workspace_id": workspace_id,
            "active_mandate": mandate_payload,
            "paper_execution_enabled": not ordered,
            "blockers": list(ordered),
            "emergency_stop": emergency,
            "d33": {
                "mode_enabled": self._settings.factor_automation.mode is True,
                "auto_land_enabled": self._settings.factor_automation.auto_land is True,
            },
            "d34": {
                "mandate_active": mandate_payload is not None
                and mandate_payload["status"] == "active"
                and int(mandate_payload["remaining_seconds"]) > 0,
                "queued_jobs": job_counts["queued"],
                "running_jobs": job_counts["running"],
                "active_canaries": active_canaries,
            },
            "budget": budget,
            "quota": {
                "new_canaries_today": new_today,
                "max_new_canaries_per_day": limits.max_daily_promotions,
            },
            "canaries": {
                "active_count": active_canaries,
                "allocated_cash": f"{allocated_cash:.2f}",
            },
            "risk": {
                "max_sleeve_cash": f"{limits.max_sleeve_cash:.2f}",
                "max_sleeve_nav_fraction": limits.max_sleeve_nav_fraction,
                "max_total_nav_fraction": limits.max_total_nav_fraction,
                "max_symbol_nav_fraction": limits.max_aggregate_symbol_nav_fraction,
                "max_daily_loss": limits.max_daily_loss,
                "max_drawdown": limits.max_drawdown,
            },
            "live_execution_enabled": False,
        }

    def set_emergency_stop(
        self, *, workspace_id: str, enabled: bool, reason: str
    ) -> dict[str, object]:
        if (
            _WORKSPACE_RE.fullmatch(workspace_id) is None
            or type(enabled) is not bool
            or not 1 <= len(reason.strip()) <= 1000
        ):
            raise D34SafetyAuthorityError(
                "d34_safety_validation", "emergency stop request is invalid"
            )
        try:
            with self._database().connect() as conn, conn.transaction():
                mandate = conn.execute(
                    f"""
                    SELECT mandate_id FROM {SCHEMA}.d34_mandates
                    WHERE owner_user_id = %s AND workspace_id = %s
                      AND status IN ('active', 'paused')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (ROOT_USER_ID, workspace_id),
                ).fetchone()
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.d34_execution_authority_events (
                        event_id, owner_user_id, workspace_id, mandate_id,
                        event_type, enabled, reason
                    ) VALUES (%s, %s, %s, %s, 'emergency_stop', %s, %s)
                    """,
                    (
                        f"execution-authority-{uuid4()}",
                        ROOT_USER_ID,
                        workspace_id,
                        mandate[0] if mandate else None,
                        enabled,
                        reason.strip(),
                    ),
                )
        except D34SafetyAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise D34SafetyAuthorityError(
                "d34_safety_unavailable", "D-34 safety authority is unavailable"
            ) from exc
        return self.observe(workspace_id=workspace_id)


__all__ = ["D34SafetyAuthority", "D34SafetyAuthorityError"]
