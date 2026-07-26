"""Production-durable Vertical-A request/claim/result authority contracts."""

from __future__ import annotations

import inspect
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from typer.testing import CliRunner

from quant_system.config.settings import (
    LIVE_TRADING_CONFIRMATION_PHRASE,
    DatabaseSettings,
    FutuSettings,
    PaperAccountSettings,
    SafetySettings,
    Settings,
)
from quant_system.hermes import vertical_a_cli
from quant_system.hermes.agent_workspace_actions import (
    canonical_action_digest,
    parse_user_action_v1,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.submission_saga import submit_bind_options_vertical_a
from quant_system.hermes.vertical_a_durable_authority import (
    PostgresVerticalAAuthority,
    VerticalAAdmissionBinding,
    VerticalADurableAuthorityError,
    vertical_a_runtime_security_ready,
    vertical_a_schema_is_ready_on_connection,
)
from quant_system.hermes.vertical_ro_provider import (
    FutuReadOnlyOptionsFacade,
    VerticalRoQuote,
)
from quant_system.hermes.zero_order_observation import (
    ZeroOrderObservationError,
    capture_canonical_zero_order_snapshot,
    prove_zero_orders,
)
from quant_system.storage import database as db

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "sql"
    / "017_agent_v02_vertical_a_authority.sql"
)
CLI_MODULE = (
    Path(__file__).resolve().parents[1] / "src" / "quant_system" / "hermes" / "vertical_a_cli.py"
)


def _safe_settings(*, db_mode: str = "canonical") -> Settings:
    return Settings(
        database=DatabaseSettings(enabled=False, auto_migrate=False),
        paper_account=PaperAccountSettings(
            db_mode=db_mode,
            auto_process_pending_orders_enabled=False,
        ),
        safety=SafetySettings(
            dry_run=True,
            paper_trading=True,
            live_trading_enabled=False,
            kill_switch=True,
        ),
        futu=FutuSettings(enabled=True, options_enabled=True),
    )


def _envelope() -> dict[str, object]:
    now = datetime.now(UTC)
    body: dict[str, object] = {
        "tickers": ["AAPL"],
        "fields": ["bid", "ask", "delta", "iv", "expiry", "strike"],
        "max_calls": 100,
        "window_start": (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "window_end": (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "grant_id": "client-assertion-is-not-authority",
    }
    from quant_system.hermes.agent_workspace_actions import (
        canonical_auth_envelope_digest,
    )

    body["grant_digest"] = canonical_auth_envelope_digest(body)
    return body


def _action_document(
    *,
    workspace_id: str = "workspace-durable-a",
    action_id: str = "act-durable-a",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "vertical.options_a.bind",
        "client_action_id": action_id,
        "workspace": {"workspace_id": workspace_id},
        "ticker": "AAPL",
        "goal_note": "read-only AAPL options research",
        "expiry": "2026-12-18",
        "strike": 200.0,
        "bid": 1.0,
        "ask": 1.1,
        "delta": -0.1,
        "iv": 0.2,
        "apr": 0.01,
        "include_provider_evidence": True,
        "provider_mode": "live_futu_ro",
        "auth_envelope": _envelope(),
    }


def _seed_kwargs(
    *,
    workspace_id: str = "workspace-durable-a",
    action_id: str = "act-durable-a",
) -> dict[str, object]:
    action = parse_user_action_v1(_action_document(workspace_id=workspace_id, action_id=action_id))
    return {
        "workspace_id": workspace_id,
        "client_action_id": action_id,
        "action_digest": canonical_action_digest(action),
        "ticker": action.ticker,
        "goal_note": action.goal_note,
        "expiry": action.expiry,
        "strike": action.strike,
        "include_provider_evidence": action.include_provider_evidence,
        "provider_mode": action.provider_mode,
        "auth_envelope": action.auth_envelope,
    }


def test_migration_owns_domain_requests_not_canonical_workflow_facts() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    for relation in (
        "agent_v02_vertical_a_grants",
        "agent_v02_vertical_a_requests",
        "agent_v02_vertical_a_claims",
        "agent_v02_vertical_a_zero_order_observations",
        "agent_v02_vertical_a_provider_receipts",
        "agent_v02_vertical_a_results",
        "agent_v02_vertical_a_outcomes",
        "agent_v02_vertical_a_actions",
    ):
        assert f"quant_system.{relation}" in migration
    for forbidden in (
        "agent_v02_vertical_a_tasks",
        "agent_v02_vertical_a_attempts",
        "agent_v02_vertical_a_runs",
    ):
        assert forbidden not in migration
    assert "admission_id" in migration
    assert "admission_digest" in migration
    assert "provider = 'futu'" in migration
    assert "orders_created = 0" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration


def test_request_thread_only_seeds_and_cli_owns_provider_call() -> None:
    seed_source = inspect.getsource(PostgresVerticalAAuthority.seed_options_vertical_a)
    assert "fetch_option_quote_row" not in seed_source
    assert "build_futu_ro_facade" not in seed_source
    cli_source = CLI_MODULE.read_text(encoding="utf-8")
    assert "build_futu_ro_facade" in cli_source
    assert "claim_request" in cli_source
    assert "finalize_verified_futu_quote" in cli_source


def test_cli_exposes_stable_execute_subcommand() -> None:
    result = CliRunner().invoke(vertical_a_cli.app, ["execute", "--help"])
    assert result.exit_code == 0
    assert "--request-id" in result.stdout
    assert "--session-ref" in result.stdout
    assert "--run-ref" in result.stdout


@pytest.mark.parametrize(
    ("settings", "code"),
    [
        (_safe_settings(db_mode="file"), "canonical_paper_authority_required"),
        (
            Settings(
                database=DatabaseSettings(enabled=False, auto_migrate=False),
                paper_account=PaperAccountSettings(
                    db_mode="canonical",
                    auto_process_pending_orders_enabled=True,
                ),
                safety=SafetySettings(kill_switch=True),
                futu=FutuSettings(enabled=True, options_enabled=True),
            ),
            "paper_order_processing_must_be_disabled",
        ),
        (
            Settings(
                database=DatabaseSettings(enabled=False, auto_migrate=False),
                paper_account=PaperAccountSettings(
                    db_mode="canonical",
                    auto_process_pending_orders_enabled=False,
                ),
                safety=SafetySettings(kill_switch=False),
                futu=FutuSettings(enabled=True, options_enabled=True),
            ),
            "kill_switch_must_be_enabled",
        ),
        (
            Settings(
                database=DatabaseSettings(enabled=False, auto_migrate=False),
                paper_account=PaperAccountSettings(
                    db_mode="canonical",
                    auto_process_pending_orders_enabled=False,
                ),
                safety=SafetySettings(
                    live_trading_enabled=True,
                    manual_live_trading_confirmation=(LIVE_TRADING_CONFIRMATION_PHRASE),
                    kill_switch=True,
                ),
                futu=FutuSettings(enabled=True, options_enabled=True),
            ),
            "live_trading_must_be_disabled",
        ),
    ],
)
def test_production_authority_fails_closed_on_unsafe_configuration(
    settings: Settings,
    code: str,
) -> None:
    authority = PostgresVerticalAAuthority(settings)
    with pytest.raises(VerticalADurableAuthorityError) as exc:
        authority.seed_options_vertical_a(**_seed_kwargs())
    assert exc.value.code == code


class _SnapshotCursor:
    def __init__(self, *, rows: dict[str, list[tuple[object, ...]]]) -> None:
        self.rows = rows
        self._active = ""
        self.queries: list[str] = []

    def execute(
        self,
        query: str,
        _params: tuple[object, ...] | None = None,
    ) -> _SnapshotCursor:
        self.queries.append(query)
        self._active = next(
            (
                name
                for name in (
                    "paper_account_ledger",
                    "paper_pending_orders",
                    "paper_positions_current",
                    "paper_accounts",
                )
                if f"FROM quant_system.{name} AS" in query
            ),
            "",
        )
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows.get(self._active, []))


def _paper_rows() -> dict[str, list[tuple[object, ...]]]:
    return {
        "paper_accounts": [
            (
                {
                    "account_id": "default",
                    "owner_user_id": str(ROOT_USER_ID),
                    "cash": 100000,
                    "kill_switch": True,
                    "version": 1,
                },
            )
        ],
        "paper_account_ledger": [],
        "paper_pending_orders": [],
        "paper_positions_current": [],
    }


def test_zero_order_snapshot_is_bounded_and_covers_all_four_authorities() -> None:
    cursor = _SnapshotCursor(rows=_paper_rows())
    snapshot = capture_canonical_zero_order_snapshot(
        cursor,
        owner_user_id=ROOT_USER_ID,
    )
    assert snapshot.account_count == 1
    assert snapshot.table_counts == {
        "paper_accounts": 1,
        "paper_account_ledger": 0,
        "paper_pending_orders": 0,
        "paper_positions_current": 0,
    }
    assert all("LIMIT" in query.upper() for query in cursor.queries)


def test_zero_order_proof_rejects_any_canonical_authority_delta() -> None:
    begin = capture_canonical_zero_order_snapshot(
        _SnapshotCursor(rows=_paper_rows()),
        owner_user_id=ROOT_USER_ID,
    )
    end = replace(
        begin,
        table_counts={**begin.table_counts, "paper_pending_orders": 1},
        snapshot_digest="b" * 64,
    )
    with pytest.raises(ZeroOrderObservationError) as exc:
        prove_zero_orders(
            action_digest="a" * 64,
            admission_digest="c" * 64,
            begin=begin,
            end=end,
        )
    assert exc.value.code == "zero_order_delta_detected"


def test_modules_expose_no_execution_or_trade_surface() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = "\n".join(
        (
            (
                root / "src" / "quant_system" / "hermes" / "vertical_a_durable_authority.py"
            ).read_text(encoding="utf-8"),
            CLI_MODULE.read_text(encoding="utf-8"),
        )
    )
    for forbidden in (
        "quant_system.execution",
        "OpenSec" + "Trade" + "Context",
        "place_order",
        "unlock_trade",
        "cancel_order",
        "get_account",
        "get_positions",
    ):
        assert forbidden not in sources


class _FakeQuoteProvider:
    def fetch_option_quotes(
        self,
        underlying: str,
        *,
        expiration: str,
        option_type: str = "ALL",
    ) -> Any:
        import pandas as pd

        return pd.DataFrame(
            [
                {
                    "symbol": f"{underlying}261218P00200000",
                    "option_type": option_type,
                    "strike": 200.0,
                    "bid": 5.1,
                    "ask": 5.3,
                    "delta": -0.23,
                    "implied_volatility": 0.31,
                    "expiry": expiration,
                }
            ]
        )

    def fetch_underlying_snapshot(self, symbol: str) -> dict[str, object]:
        return {"symbol": symbol, "last": 220.0}


def test_futu_facade_surface_stays_read_only() -> None:
    facade = FutuReadOnlyOptionsFacade(_FakeQuoteProvider())
    for name in (
        "place_order",
        "cancel_order",
        "unlock_trade",
        "get_account",
        "get_positions",
    ):
        with pytest.raises(AttributeError):
            getattr(facade, name)


def test_post_provider_receipt_loss_seals_unknown_and_never_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed provider attempt is an irreversible one-call reservation."""

    state = {"provider_calls": 0, "sealed": False}
    claim = SimpleNamespace(
        claim_id="claim-receipt-loss",
        claim_digest="a" * 64,
        ticker="AAPL",
        expiry="2026-12-18",
        strike=200.0,
    )

    class FakeAuthority:
        def claim_request(self, **_kwargs: object) -> object:
            if state["sealed"]:
                raise VerticalADurableAuthorityError(
                    "provider_outcome_unknown",
                    "provider_outcome_unknown",
                )
            return claim

        def finalize_verified_futu_quote(self, **_kwargs: object) -> object:
            raise VerticalADurableAuthorityError(
                "durable_authority_unavailable",
                "receipt commit was lost",
            )

        def mark_outcome_unknown(self, **_kwargs: object) -> None:
            state["sealed"] = True

    class FakeFacade:
        def fetch_option_quote_row(self, **_kwargs: object) -> VerticalRoQuote:
            state["provider_calls"] += 1
            return _quote()

    authority = FakeAuthority()
    monkeypatch.setattr(vertical_a_cli, "load_settings", object)
    monkeypatch.setattr(
        vertical_a_cli,
        "PostgresVerticalAAuthority",
        lambda _settings: authority,
    )
    monkeypatch.setattr(
        vertical_a_cli,
        "build_futu_ro_facade",
        lambda _settings: FakeFacade(),
    )
    kwargs = {
        "request_id": "request-receipt-loss",
        "expected_action_digest": "b" * 64,
        "expected_admission_id": "admission-receipt-loss",
        "expected_admission_digest": "c" * 64,
        "session_ref": "session:session-receipt-loss",
        "run_ref": "run:run-receipt-loss",
        "worker_id": "worker-receipt-loss",
    }
    with pytest.raises(VerticalADurableAuthorityError) as first:
        vertical_a_cli.execute_request(**kwargs)
    assert first.value.code == "provider_outcome_unknown"
    assert state == {"provider_calls": 1, "sealed": True}

    with pytest.raises(VerticalADurableAuthorityError) as replay:
        vertical_a_cli.execute_request(**kwargs)
    assert replay.value.code == "provider_outcome_unknown"
    assert state["provider_calls"] == 1


def _test_database_url() -> str:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    name = conninfo_to_dict(url).get("dbname")
    if not name or not (name.endswith("_tmp") or "test" in name):
        pytest.fail(f"QS_TEST_DATABASE_URL must point at a throwaway test database (got {name!r})")
    return url


def _runtime_url(admin_url: str, *, user: str, password: str) -> str:
    params = conninfo_to_dict(admin_url)
    params["user"] = user
    params["password"] = password
    return make_conninfo(**params)


def _pg_settings(url: str) -> Settings:
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=url,
            auto_migrate=False,
            connect_timeout_seconds=1,
        ),
        paper_account=PaperAccountSettings(
            db_mode="canonical",
            auto_process_pending_orders_enabled=False,
        ),
        safety=SafetySettings(
            dry_run=True,
            paper_trading=True,
            live_trading_enabled=False,
            kill_switch=True,
        ),
        futu=FutuSettings(enabled=True, options_enabled=True),
    )


def _quote() -> VerticalRoQuote:
    return VerticalRoQuote(
        provider_name="futu",
        request_id="futu-request-001",
        as_of=datetime.now(UTC),
        ticker="AAPL",
        expiry="2026-12-18",
        strike=200.0,
        bid=5.1,
        ask=5.3,
        delta=-0.23,
        iv=0.31,
        apr=0.14,
        evidence=(
            "provider:futu",
            "request_id:futu-request-001",
        ),
    )


@pytest.mark.pg
def test_pg_two_stage_authority_is_crash_safe_exact_bound_and_restorable() -> None:
    admin_url = _test_database_url()
    admin_database = db.Database(admin_url, connect_timeout=1)
    migrations = [
        path.name for path in sorted(MIGRATION.parent.glob("*.sql")) if int(path.name[:3]) <= 17
    ]
    db.run_migrations(admin_database, only=migrations)
    fingerprint = db.schema_fingerprint(admin_database)
    db.run_migrations(
        admin_database,
        only=["017_agent_v02_vertical_a_authority.sql"],
    )
    assert db.schema_fingerprint(admin_database) == fingerprint

    suffix = uuid.uuid4().hex[:10]
    login = f"aqp_vertical_a_{suffix}"
    password = f"vertical-a-{suffix}"
    workspace_id = f"workspace-vertical-a-{suffix}"
    admission_id = f"admission-{suffix}"
    admission_digest = (suffix * 7)[:64]
    platform_session_id = f"session-{suffix}"
    creation_digest = (f"{suffix}e" * 6)[:64]
    hermes_session_id = f"web_{creation_digest[:40]}"
    hermes_run_id = f"hermes-run-{suffix}"
    command_id = uuid.uuid4()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=20)
    action_document = _action_document(workspace_id=workspace_id)
    action = parse_user_action_v1(action_document)
    action_digest = canonical_action_digest(action)

    try:
        with admin_database.connect() as conn:
            conn.execute(
                sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}").format(
                    sql.Identifier(login), sql.Literal(password)
                )
            )
            conn.execute(sql.SQL("GRANT quant_runtime TO {}").format(sql.Identifier(login)))
            conn.execute(
                """
                INSERT INTO quant_system.paper_accounts (
                    account_id, owner_user_id, base_currency,
                    initial_cash, cash, realized_pnl, kill_switch,
                    version, raw, created_at, updated_at
                )
                VALUES (
                    %s, %s, 'USD', 100000, 100000, 0, TRUE,
                    1, %s::jsonb, %s, %s
                )
                """,
                (
                    f"paper-{suffix}",
                    ROOT_USER_ID,
                    json.dumps({"kill_switch": True, "version": 1}),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO quant_system.agent_v02_candidate_admissions (
                    admission_id, owner_user_id, workspace_id, route,
                    platform_runtime_digest, hqa_runtime_digest,
                    hermes_runtime_digest, database_schema_fingerprint,
                    preflight_evidence_digest, baseline_order_snapshot_digest,
                    admission_digest, status, opened_at, expires_at
                )
                VALUES (
                    %s, %s, %s, '/hermes',
                    %s, %s, %s, %s, %s, %s, %s, 'open', %s, %s
                )
                """,
                (
                    admission_id,
                    ROOT_USER_ID,
                    workspace_id,
                    "1" * 64,
                    "2" * 64,
                    "3" * 64,
                    fingerprint,
                    "4" * 64,
                    "5" * 64,
                    admission_digest,
                    now,
                    expires_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO quant_system.hermes_workspace_sessions (
                    platform_session_id, hermes_session_id, workspace_id,
                    owner_user_id, kind, source_channel,
                    provider_policy_digest, writer,
                    creation_client_action_id, creation_action_digest,
                    provision_state, provisioning_receipt_digest, provisioned_at,
                    created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, 'web_managed_session', NULL,
                    %s, 'web_control_plane',
                    %s, %s,
                    'ready', %s, %s, %s, %s
                )
                """,
                (
                    platform_session_id,
                    hermes_session_id,
                    workspace_id,
                    ROOT_USER_ID,
                    "6" * 64,
                    f"session-create-{suffix}",
                    creation_digest,
                    "9" * 64,
                    now,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO quant_system.hermes_commands (
                    command_id, owner_user_id, platform_session_id,
                    client_request_id, kind, canonical_request_digest,
                    payload_ref, provider_policy_digest, state, version,
                    attempt_count, dispatch_started_at,
                    hermes_session_id, resolved_hermes_session_id,
                    hermes_run_id,
                    created_at, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, 'conversation_turn', %s,
                    %s, %s, 'delivered', 2, 1, %s,
                    %s, %s, %s, %s, %s
                )
                """,
                (
                    command_id,
                    ROOT_USER_ID,
                    platform_session_id,
                    f"command-{suffix}",
                    "7" * 64,
                    f"payload:sha256:{'8' * 64}",
                    "6" * 64,
                    now,
                    hermes_session_id,
                    f"{hermes_session_id}-tip",
                    hermes_run_id,
                    now,
                    now,
                ),
            )

        runtime_settings = _pg_settings(_runtime_url(admin_url, user=login, password=password))
        admission = VerticalAAdmissionBinding(
            admission_id=admission_id,
            admission_digest=admission_digest,
            workspace_id=workspace_id,
            opened_at=now,
            expires_at=expires_at,
        )
        authority = PostgresVerticalAAuthority(
            runtime_settings,
            admission_resolver=lambda _workspace_id: admission,
        )
        db.reset_database_cache()
        assert vertical_a_runtime_security_ready(runtime_settings) is True

        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(
                pool.map(
                    lambda _index: submit_bind_options_vertical_a(
                        runtime_settings,
                        action,
                        mutation_enabled=True,
                        vertical_a_authority=authority,
                    ),
                    range(2),
                )
            )
        assert {receipt.status for receipt in receipts} == {"reconciling"}
        assert len({receipt.domain_request_id for receipt in receipts}) == 1
        seed = receipts[0]
        assert seed.domain_request_id
        assert seed.command_id is None
        assert seed.task_id is None
        assert seed.attempt_id is None
        assert seed.run_id is None
        assert seed.result_id is None

        replay = submit_bind_options_vertical_a(
            runtime_settings,
            action,
            mutation_enabled=True,
            vertical_a_authority=authority,
        )
        assert replay.domain_request_id == seed.domain_request_id
        conflict_action = parse_user_action_v1(
            {**action_document, "goal_note": "different immutable request"}
        )
        conflict = submit_bind_options_vertical_a(
            runtime_settings,
            conflict_action,
            mutation_enabled=True,
            vertical_a_authority=authority,
        )
        assert conflict.status == "conflict"

        with admin_database.connect() as conn:
            assert conn.execute(
                """
                SELECT used_calls, max_calls
                FROM quant_system.agent_v02_vertical_a_grants
                WHERE admission_id = %s
                """,
                (admission_id,),
            ).fetchone() == (0, 1)

        claim = authority.claim_request(
            request_id=str(seed.domain_request_id),
            expected_action_digest=action_digest,
            expected_admission_id=admission_id,
            expected_admission_digest=admission_digest,
            session_ref=f"session:{platform_session_id}",
            run_ref=f"run:{hermes_run_id}",
            worker_id=f"hqa-{suffix}",
        )
        with admin_database.connect() as conn:
            assert conn.execute(
                """
                SELECT used_calls, max_calls
                FROM quant_system.agent_v02_vertical_a_grants
                WHERE admission_id = %s
                """,
                (admission_id,),
            ).fetchone() == (1, 1)
        with pytest.raises(VerticalADurableAuthorityError) as repeated:
            authority.claim_request(
                request_id=str(seed.domain_request_id),
                expected_action_digest=action_digest,
                expected_admission_id=admission_id,
                expected_admission_digest=admission_digest,
                session_ref=f"session:{platform_session_id}",
                run_ref=f"run:{hermes_run_id}",
                worker_id=f"hqa-{suffix}",
            )
        assert repeated.value.code == "provider_outcome_unknown"
        crash_projection = authority.project_workspace(workspace_id)
        assert crash_projection.options_requests[0]["state"] == "outcome_unknown"
        assert (
            crash_projection.options_requests[0]["recovery_action"]
            == "operator_reconcile_no_provider_replay"
        )
        assert crash_projection.provider_health == "dark"

        completed = authority.finalize_verified_futu_quote(
            claim_id=claim.claim_id,
            expected_claim_digest=claim.claim_digest,
            quote=_quote(),
        )
        assert completed.result_id
        assert completed.run_ref == f"run:{hermes_run_id}"
        assert completed.session_ref == f"session:{platform_session_id}"

        completed_replay = authority.finalize_verified_futu_quote(
            claim_id=claim.claim_id,
            expected_claim_digest=claim.claim_digest,
            quote=_quote(),
        )
        assert completed_replay == completed
        act_replay = submit_bind_options_vertical_a(
            runtime_settings,
            action,
            mutation_enabled=True,
            vertical_a_authority=authority,
        )
        assert act_replay.status == "accepted"
        assert act_replay.domain_request_status == "completed"
        assert act_replay.result_id == completed.result_id
        assert act_replay.command_id is None
        assert act_replay.task_id is None
        assert act_replay.attempt_id is None
        assert act_replay.run_id is None

        projection = authority.project_workspace(workspace_id)
        assert projection.tasks == ()
        assert projection.attempts == ()
        assert projection.runs == ()
        assert projection.options_requests[0]["state"] == "completed"
        assert projection.results[0]["result_id"] == completed.result_id
        assert projection.results[0]["run_id"] == hermes_run_id
        assert projection.results[0].get("task_id") is None
        assert projection.provider_health == "ready"

        with admin_database.connect() as conn:
            persisted = conn.execute(
                """
                SELECT receipt.provider, receipt.admission_digest,
                       receipt.action_digest, receipt.capture_digest,
                       result.hermes_session_id, result.hermes_run_id,
                       zero.orders_created, zero.delta_zero,
                       link.platform_resource_type, link.relation,
                       link.resolved_hermes_session_id
                FROM quant_system.agent_v02_vertical_a_provider_receipts AS receipt
                JOIN quant_system.agent_v02_vertical_a_results AS result
                  ON result.provider_receipt_id = receipt.provider_receipt_id
                JOIN quant_system.agent_v02_vertical_a_zero_order_observations AS zero
                  ON zero.capture_digest = receipt.capture_digest
                JOIN quant_system.hermes_run_links AS link
                  ON link.platform_resource_id = result.result_id
                WHERE result.result_id = %s
                """,
                (completed.result_id,),
            ).fetchone()
        assert persisted == (
            "futu",
            admission_digest,
            action_digest,
            persisted[3],
            hermes_session_id,
            hermes_run_id,
            0,
            True,
            "options_result",
            "output",
            f"{hermes_session_id}-tip",
        )

        with admin_database.connect() as conn:
            conn.execute("BEGIN")
            conn.execute(
                """
                ALTER TABLE quant_system.agent_v02_vertical_a_results
                DROP CONSTRAINT ck_agent_v02_vertical_a_result_real
                """
            )
            assert vertical_a_schema_is_ready_on_connection(conn) is False
            conn.execute("ROLLBACK")

        with admin_database.connect() as conn:
            conn.execute(
                "REVOKE INSERT ON quant_system.agent_v02_vertical_a_results FROM quant_runtime"
            )
        try:
            db.reset_database_cache()
            assert vertical_a_runtime_security_ready(runtime_settings) is False
        finally:
            with admin_database.connect() as conn:
                conn.execute(
                    "GRANT INSERT ON quant_system.agent_v02_vertical_a_results TO quant_runtime"
                )
    finally:
        db.reset_database_cache()
        with admin_database.connect() as conn:
            if conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                (login,),
            ).fetchone():
                conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)))
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))
