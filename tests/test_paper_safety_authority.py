from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID

from quant_system.config.settings import (
    PaperAccountSettings,
    SafetySettings,
    Settings,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.paper_safety_authority import PaperSafetyAuthority


class _Result:
    def __init__(self, row: tuple[object, ...]) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...]:
        return self._row


class _Connection:
    def __init__(self, row: tuple[object, ...]) -> None:
        self.row = row
        self.statements: list[str] = []
        self.parameters: list[tuple[object, ...] | None] = []

    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] | None = None,
    ) -> _Result:
        self.statements.append(statement)
        self.parameters.append(parameters)
        return _Result(self.row)


class _Database:
    def __init__(self, row: tuple[object, ...]) -> None:
        self.connection = _Connection(row)

    @contextmanager
    def connect(self):
        yield self.connection


def _canonical_settings(*, global_kill_switch: bool = True) -> Settings:
    return Settings(
        safety=SafetySettings(kill_switch=global_kill_switch),
        paper_account=PaperAccountSettings(db_mode="canonical"),
    )


def test_effective_paper_safety_observes_one_frozen_root_account_and_epoch() -> None:
    database = _Database((1, True, 41))

    observation = PaperSafetyAuthority(
        _canonical_settings(),
        database=database,
    ).observe("ws-local-main")

    assert observation.owner_user_id == str(ROOT_USER_ID)
    assert UUID(observation.owner_user_id) == ROOT_USER_ID
    assert observation.workspace_id == "ws-local-main"
    assert observation.global_kill_switch is True
    assert observation.canonical_account_count == 1
    assert observation.canonical_account_frozen is True
    assert observation.current_paper_authority_epoch == 41
    assert observation.effective is True
    assert observation.blockers == ()
    assert len(database.connection.statements) == 1
    assert database.connection.statements[0].lstrip().upper().startswith("SELECT")
    assert database.connection.parameters == [
        (ROOT_USER_ID, "ws-local-main", ROOT_USER_ID)
    ]
    sql = database.connection.statements[0]
    assert "account.account_id = 'default'" in sql
    assert "account.raw ->> 'kill_switch' = 'true'" in sql


def test_effective_paper_safety_keeps_global_and_account_kill_switches_independent() -> None:
    database = _Database((1, False, 41))

    observation = PaperSafetyAuthority(
        _canonical_settings(global_kill_switch=False),
        database=database,
    ).observe("ws-local-main")

    assert observation.global_kill_switch is False
    assert observation.canonical_account_frozen is False
    assert observation.blockers == (
        "kill_switch_off",
        "canonical_account_kill_switch_off",
    )
    assert observation.effective is False


def test_effective_paper_safety_reports_stale_candidate_epoch_separately() -> None:
    observation = PaperSafetyAuthority(
        _canonical_settings(),
        database=_Database((1, True, 42)),
    ).observe(
        "ws-local-main",
        candidate_paper_authority_epoch=41,
    )

    assert observation.current_paper_authority_epoch == 42
    assert observation.canonical_account_frozen is True
    assert observation.blockers == ("candidate_paper_authority_epoch_stale",)
    assert observation.effective is False


def test_effective_paper_safety_treats_missing_candidate_epoch_as_stale() -> None:
    observation = PaperSafetyAuthority(
        _canonical_settings(),
        database=_Database((1, True, 42)),
    ).observe(
        "ws-local-main",
        candidate_paper_authority_epoch=None,
    )

    assert observation.blockers == ("candidate_paper_authority_epoch_stale",)
    assert observation.effective is False


def test_effective_paper_safety_fails_closed_without_one_canonical_root_account() -> None:
    observation = PaperSafetyAuthority(
        _canonical_settings(),
        database=_Database((2, None, 42)),
    ).observe("ws-local-main")

    assert observation.canonical_account_count == 2
    assert observation.canonical_account_frozen is None
    assert observation.blockers == ("canonical_paper_authority_unavailable",)
    assert observation.effective is False


def test_effective_paper_safety_rejects_noncanonical_storage_without_query() -> None:
    database = _Database((1, True, 42))

    observation = PaperSafetyAuthority(
        Settings(paper_account=PaperAccountSettings(db_mode="mirror")),
        database=database,
    ).observe("ws-local-main")

    assert observation.canonical_account_count is None
    assert observation.canonical_account_frozen is None
    assert observation.current_paper_authority_epoch is None
    assert observation.blockers == ("canonical_paper_authority_required",)
    assert observation.effective is False
    assert database.connection.statements == []
