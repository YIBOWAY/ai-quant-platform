"""Provider-free observation of the effective paper safety authority."""

from __future__ import annotations

import re
from dataclasses import dataclass

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import Database, get_database

_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_CANDIDATE_EPOCH_UNSET = object()


@dataclass(frozen=True)
class EffectivePaperSafetyObservation:
    owner_user_id: str
    workspace_id: str
    global_kill_switch: bool
    canonical_account_count: int | None
    canonical_account_frozen: bool | None
    current_paper_authority_epoch: int | None
    effective: bool
    blockers: tuple[str, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "blockers": list(self.blockers),
            "canonical_account_count": self.canonical_account_count,
            "canonical_account_frozen": self.canonical_account_frozen,
            "current_paper_authority_epoch": self.current_paper_authority_epoch,
            "effective": self.effective,
            "global_kill_switch": self.global_kill_switch,
            "owner_user_id": self.owner_user_id,
            "workspace_id": self.workspace_id,
        }


class PaperSafetyAuthority:
    """Read only PostgreSQL paper facts without touching a provider or account snapshot."""

    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
    ) -> None:
        self._settings = settings
        self._database_override = database

    def observe(
        self,
        workspace_id: str,
        *,
        candidate_paper_authority_epoch: int | None | object = (
            _CANDIDATE_EPOCH_UNSET
        ),
    ) -> EffectivePaperSafetyObservation:
        workspace = str(workspace_id)
        global_kill_switch = self._settings.safety.kill_switch is True
        blockers: list[str] = []
        if not global_kill_switch:
            blockers.append("kill_switch_off")

        count: int | None = None
        frozen: bool | None = None
        current_epoch: int | None = None
        if self._settings.paper_account.db_mode != "canonical":
            blockers.append("canonical_paper_authority_required")
        elif _WORKSPACE_RE.fullmatch(workspace) is None:
            blockers.append("canonical_paper_authority_unavailable")
        else:
            try:
                database = self._database_override or get_database(self._settings)
                if database is None:
                    raise RuntimeError("PostgreSQL is unavailable")
                with database.connect() as conn:
                    row = conn.execute(
                        """
                        SELECT
                            count(*)::BIGINT,
                            CASE
                                WHEN count(*) = 1
                                THEN bool_and(
                                    account.account_id = 'default'
                                    AND account.kill_switch
                                    AND jsonb_typeof(
                                        account.raw -> 'kill_switch'
                                    ) = 'boolean'
                                    AND account.raw ->> 'kill_switch' = 'true'
                                    AND account.raw ->> 'account_id' =
                                        account.account_id
                                )
                                ELSE NULL
                            END,
                            quant_system.current_agent_v02_paper_authority_epoch(
                                %s,
                                %s
                            )
                        FROM quant_system.paper_accounts AS account
                        WHERE account.owner_user_id = %s
                        """,
                        (ROOT_USER_ID, workspace, ROOT_USER_ID),
                    ).fetchone()
                if row is None:
                    raise RuntimeError("paper safety query returned no row")
                count = int(row[0])
                frozen = None if row[1] is None else bool(row[1])
                current_epoch = None if row[2] is None else int(row[2])
                if count != 1 or current_epoch is None:
                    blockers.append("canonical_paper_authority_unavailable")
                elif frozen is not True:
                    blockers.append("canonical_account_kill_switch_off")
            except Exception:  # noqa: BLE001 - uncertain paper facts fail closed
                count = None
                frozen = None
                current_epoch = None
                blockers.append("canonical_paper_authority_unavailable")

        if candidate_paper_authority_epoch is not _CANDIDATE_EPOCH_UNSET and (
            isinstance(candidate_paper_authority_epoch, bool)
            or not isinstance(candidate_paper_authority_epoch, int)
            or current_epoch != candidate_paper_authority_epoch
        ):
            blockers.append("candidate_paper_authority_epoch_stale")

        ordered = tuple(dict.fromkeys(blockers))
        return EffectivePaperSafetyObservation(
            owner_user_id=str(ROOT_USER_ID),
            workspace_id=workspace,
            global_kill_switch=global_kill_switch,
            canonical_account_count=count,
            canonical_account_frozen=frozen,
            current_paper_authority_epoch=current_epoch,
            effective=not ordered,
            blockers=ordered,
        )


__all__ = [
    "EffectivePaperSafetyObservation",
    "PaperSafetyAuthority",
]
