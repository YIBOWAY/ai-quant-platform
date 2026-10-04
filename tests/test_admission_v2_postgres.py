"""Real isolated PostgreSQL transactions; producer capability is explicitly sealed."""

import os
from contextlib import contextmanager

import pytest

from quant_system.execution import assistant_remote as remote
from quant_system.execution.account_postgres_repository import PostgresPaperAccountRepository
from quant_system.research import admission_v2
from quant_system.storage import database as db
from tests import test_admission_v2_consumers as fixtures
from tests.postgres_reset import isolated_test_database_url
from tests.test_assistant_remote import _canonical_hang_evidence, _canonical_hang_settings


@pytest.fixture
def context(tmp_path):
    return fixtures.context.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def sealed_producer(monkeypatch):
    yield from fixtures.sealed_producer.__wrapped__(monkeypatch)


@pytest.mark.pg
@pytest.mark.parametrize("lose_commit_response", [False, True])
def test_v2_canonical_one_allocation_and_replay_without_fresh_gates(
    context,
    monkeypatch,
    lose_commit_response,
):
    base_url = os.environ.get("QS_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("requires explicitly isolated QS_TEST_DATABASE_URL")
    file_settings, _, candidate = fixtures.fundable_consumer(context, monkeypatch)
    with isolated_test_database_url(base_url, purpose="v2cash") as url:
        database = db.Database(url, connect_timeout=1)
        db.run_migrations(database)
        settings = _canonical_hang_settings(file_settings.data.data_dir, url)
        repo = remote.build_paper_account_repository(
            settings.data.data_dir / "api_runs", settings=settings
        )
        repo.reset(initial_cash=1000000)
        monkeypatch.setattr(admission_v2, "AUTHORITATIVE_ENABLED", True)
        original = PostgresPaperAccountRepository.save
        called = []

        def save(repository, account, **kwargs):
            result = original(repository, account, **kwargs)
            called.append("commit")
            if lose_commit_response and len(called) == 1:
                raise RuntimeError("sealed response loss after actual PG commit")
            return result

        monkeypatch.setattr(PostgresPaperAccountRepository, "save", save)
        kwargs = dict(
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
        )
        if lose_commit_response:
            with pytest.raises(remote.AssistantRemoteError, match="hang_account_outcome_unknown"):
                remote.hang_candidate(settings, **kwargs)
        else:
            assert remote.hang_candidate(settings, **kwargs)["status"] == "hung"
        first = repo.load()
        assert len([r for r in first.ledger if r.kind == "sleeve_cash_allocated"]) == 1
        assert sum(value for key, value in first.sleeve_cash.items() if key != "manual") == 10000
        monkeypatch.setattr(admission_v2, "AUTHORITATIVE_ENABLED", False)
        with (settings.data.data_dir / "trials/trials.jsonl").open("a") as handle:
            handle.write("\n")
        assert remote.hang_candidate(settings, **kwargs)["status"] == "hung"
        final = repo.load()
        assert len([r for r in final.ledger if r.kind == "sleeve_cash_allocated"]) == 1
        assert final.sleeve_cash == first.sleeve_cash
        assert not (settings.data.data_dir / "api_runs/paper_account/account.json").exists()


@pytest.mark.pg
def test_v2_pg_locked_family_change_has_no_persistent_effect(context, monkeypatch):
    base_url = os.environ.get("QS_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("requires explicitly isolated QS_TEST_DATABASE_URL")
    file_settings, _, candidate = fixtures.fundable_consumer(context, monkeypatch)
    with isolated_test_database_url(base_url, purpose="v2cas") as url:
        database = db.Database(url, connect_timeout=1)
        db.run_migrations(database)
        settings = _canonical_hang_settings(file_settings.data.data_dir, url)
        repo = remote.build_paper_account_repository(
            settings.data.data_dir / "api_runs", settings=settings
        )
        repo.reset(initial_cash=1000000)
        monkeypatch.setattr(admission_v2, "AUTHORITATIVE_ENABLED", True)
        original = remote._book_mutation_lock

        @contextmanager
        def race(current, **kwargs):
            with original(current, **kwargs):
                with (settings.data.data_dir / "trials/trials.jsonl").open("a") as handle:
                    handle.write("\n")
                yield

        before = _canonical_hang_evidence(database, settings.data.data_dir)
        monkeypatch.setattr(remote, "_book_mutation_lock", race)
        with pytest.raises(remote.AssistantRemoteError, match="family_changed"):
            remote.hang_candidate(
                settings,
                candidate_id=candidate["candidate_id"],
                expected_source_digest=candidate["source_digest"],
            )
        assert _canonical_hang_evidence(database, settings.data.data_dir) == before
