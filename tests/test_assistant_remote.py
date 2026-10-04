import copy
import hashlib
import io
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_system.config.settings import (
    DatabaseSettings,
    DataSettings,
    PaperAccountSettings,
    SafetySettings,
    Settings,
    reload_settings,
)
from quant_system.d34.paper_cycle import plan_d34_paper_cycle, run_d34_paper_cycle
from quant_system.d34.research_driver import READ_ONLY_DSR_CANDIDATE_ID
from quant_system.d34.research_request import digest_document
from quant_system.execution.account import PendingAccountOrder
from quant_system.execution.account_repository_factory import (
    build_paper_account_repository,
)
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.assistant_remote import (
    AssistantRemoteError,
    CandidateEvidenceRef,
    intake_research_operation,
    load_book,
    project_book,
    project_research_evidence,
    project_research_request,
    project_terminal_research_results,
    reconcile_research_result,
    record_verified_candidate,
    record_verified_from_dual_engine_artifact,
    resolve_hang_sleeve_strategy,
)
from quant_system.execution.assistant_remote import (
    hang_candidate as _hang_candidate,
)
from quant_system.execution.paper_observation import hung_sleeve_eligible
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    SignalStatus,
    SleeveLot,
    StrategyExecutionPlan,
    StrategySignal,
)
from quant_system.options.seller_score import is_us_market_session
from quant_system.storage import database as db
from tests.postgres_reset import isolated_test_database_url

_FIXTURE_FACTOR = """from __future__ import annotations
import pandas as pd
from quant_system.factors.base import BaseFactor

class GeneratedFactor(BaseFactor):
    factor_id = "d34_oracle"
    factor_name = "D34 Oracle"
    display_name_zh = "隔离测试因子"
    default_lookback = 2
    direction = "higher_is_better"
    description = "Isolation digest-bound fixture."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        return frame.groupby("symbol", sort=False)["close"].pct_change(
            self.lookback, fill_method=None
        )

D34_FACTOR = GeneratedFactor
""".encode()


def _settings(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "file")
    return reload_settings()


def _write_fixture_factor(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "fixture_d34_oracle.py"
    path.write_bytes(_FIXTURE_FACTOR)
    return path, hashlib.sha256(_FIXTURE_FACTOR).hexdigest()


def _canonical_hang_settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        data=DataSettings(
            data_dir=tmp_path,
            parquet_dir=tmp_path / "parquet",
            duckdb_path=tmp_path / "quant_system.duckdb",
            reports_dir=tmp_path / "reports",
        ),
        database=DatabaseSettings(
            enabled=True,
            url=database_url,
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
    )


def _record_strong_hang_candidate(
    settings: Settings,
    tmp_path: Path,
    *,
    candidate_id: str,
) -> None:
    from tests.current_capital_fixtures import d34_candidate_kwargs

    path, digest = _write_fixture_factor(tmp_path)
    original = d34_candidate_kwargs(
        settings,
        candidate_id=candidate_id,
        daily_returns=_strong_returns(),
        turnover_period=1.0,
        objective="canonical account hang",
        source_digest=digest,
        source_path=str(path),
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
    )
    record_verified_candidate(settings, **original)


def _record_current_candidate(settings, **arguments):
    """Explicit complete artificial originals for intended funding/lock tests.

    This prepares a new specimen before the real record/funding calls. It never
    runs from the hang wrapper or repairs bad evidence during the tested action.
    """
    from tests.current_capital_fixtures import d34_candidate_kwargs

    keys = {"candidate_id", "source_path", "source_digest", "factor_id", "universe",
            "daily_returns", "return_dates", "turnover_period", "top_n", "strategy_id",
            "objective"}
    prepared = d34_candidate_kwargs(settings, **{key: value for key, value in arguments.items()
                                                if key in keys})
    if "operator" in arguments:
        prepared["operator"] = arguments["operator"]
    return record_verified_candidate(settings, **prepared)


def hang_candidate(
    settings: Settings,
    *,
    candidate_id: str,
    expected_source_digest: str | None = None,
):
    """Supply the candidate's current digest to legacy hang-path fixtures."""

    if expected_source_digest is None:
        candidate = next(
            (
                item
                for item in project_book(settings)["candidates"]
                if item.get("candidate_id") == candidate_id
            ),
            None,
        )
        expected_source_digest = str(
            (candidate or {}).get("source_digest")
            or (candidate or {}).get("candidate_code_digest")
            or "0" * 64
        )
    return _hang_candidate(
        settings,
        candidate_id=candidate_id,
        expected_source_digest=expected_source_digest,
    )


def _stable_json_hash(value) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _research_operation_id(
    platform_session_id: str,
    hermes_session_id: str,
    material_digest: str,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "contract": "hqa.chat_research_operation/v1",
                "hermes_session_id": hermes_session_id,
                "material_digest": material_digest,
                "platform_session_id": platform_session_id,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _tree_hash(root: Path) -> str:
    rows: list[tuple[str, str]] = []
    if root.exists():
        for path in sorted(
            item for item in root.rglob("*") if item.is_file() and item.suffix != ".lock"
        ):
            rows.append(
                (
                    str(path.relative_to(root)),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
    return _stable_json_hash(rows)


def _canonical_hang_evidence(database: db.Database, tmp_path: Path) -> dict:
    with database.connect() as conn:
        account_row = conn.execute(
            """
            SELECT raw
            FROM quant_system.paper_accounts
            WHERE account_id = 'default'
            """
        ).fetchone()
        ledger_rows = conn.execute(
            """
            SELECT raw
            FROM quant_system.paper_account_ledger
            WHERE account_id = 'default'
            ORDER BY seq
            """
        ).fetchall()
    assert account_row is not None
    raw = account_row[0]
    if isinstance(raw, str):
        raw = json.loads(raw)
    ledger = [row[0] for row in ledger_rows]
    sleeve_cash = raw["sleeve_cash"]
    return {
        "raw_hash": _stable_json_hash(raw),
        "manual_cash": sleeve_cash.get("manual"),
        "partition_sum": sum(float(value) for value in sleeve_cash.values()),
        "ledger_count": len(ledger),
        "ledger_hash": _stable_json_hash(ledger),
        "book_hash": _tree_hash(tmp_path / "assistant_remote"),
        "sleeve_tree_hash": _tree_hash(tmp_path / "api_runs" / "paper_strategy_sleeves"),
        "file_account_exists": PaperAccountStorage(tmp_path / "api_runs").account_path.exists(),
    }


def test_cli_book_is_projection_only_and_byte_stable(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    from quant_system import assistant_remote_cli
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    remote_module.save_book(
        settings,
        {
            "contract": remote_module.BOOK_CONTRACT,
            "candidates": [],
            "requests": [],
        },
    )
    book_path = tmp_path / "assistant_remote" / "book.json"
    before = book_path.read_bytes()
    monkeypatch.setattr(assistant_remote_cli, "load_settings", lambda: settings)

    assert assistant_remote_cli.main(["book"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["requests"] == []
    assert book_path.read_bytes() == before


def test_record_verified_candidate_requires_source_digest_and_universe(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)

    with pytest.raises(AssistantRemoteError) as missing:
        record_verified_candidate(
            settings,
            candidate_id="candidate-no-digest",
            objective="preview verified candidate",
            source="preview_seed",
        )
    assert missing.value.code == "candidate_digest_required"

    with pytest.raises(AssistantRemoteError) as no_universe:
        record_verified_candidate(
            settings,
            candidate_id="candidate-no-universe",
            objective="preview verified candidate",
            source="preview_seed",
            source_digest=digest,
            source_path=str(path),
            factor_id="d34_oracle",
        )
    assert no_universe.value.code == "candidate_universe_required"


def test_hang_rejects_source_bytes_that_no_longer_match_digest(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    record_verified_candidate(
        settings,
        candidate_id="candidate-tampered",
        objective="digest must be rechecked at hang",
        source="preview_seed",
        source_digest=digest,
        source_path=str(path),
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
    )
    path.write_bytes(_FIXTURE_FACTOR + b"# changed\n")

    with pytest.raises(AssistantRemoteError) as mismatch:
        hang_candidate(settings, candidate_id="candidate-tampered")
    assert mismatch.value.code == "candidate_source_digest_mismatch"
    assert project_book(settings)["hung_count"] == 0


def test_hang_rejects_stale_expected_digest_without_any_tree_write(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id="candidate-digest-cas",
    )
    before = _tree_hash(tmp_path)

    with pytest.raises(AssistantRemoteError) as mismatch:
        hang_candidate(
            settings,
            candidate_id="candidate-digest-cas",
            expected_source_digest="f" * 64,
        )

    assert mismatch.value.code == "candidate_source_digest_mismatch"
    assert _tree_hash(tmp_path) == before
    assert project_book(settings)["hung_count"] == 0


def test_hang_rejects_already_hung_demo_sleeve_without_digest(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    book_path = tmp_path / "assistant_remote" / "book.json"
    book_path.parent.mkdir(parents=True)
    book_path.write_text(
        '{"contract":"hqa.assistant_remote_book/v1","candidates":[{"candidate_id":'
        '"candidate-preview-unhung","objective":"old demo","status":"hung",'
        '"source":"preview_seed","artifact_id":null,'
        '"sleeve_id":"sleeve-1273d32417c8"}],"requests":[]}',
        encoding="utf-8",
    )

    with pytest.raises(AssistantRemoteError) as missing:
        hang_candidate(settings, candidate_id="candidate-preview-unhung")
    assert missing.value.code == "candidate_digest_required"
    assert project_book(settings)["hung_count"] == 0


def test_record_verified_candidate_does_not_launder_existing_digestless_row(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    book_path = tmp_path / "assistant_remote" / "book.json"
    book_path.parent.mkdir(parents=True)
    book_path.write_text(
        '{"contract":"hqa.assistant_remote_book/v1","candidates":[{"candidate_id":'
        '"candidate-preview-unhung","objective":"old demo","status":"hung",'
        '"source":"preview_seed","artifact_id":null,'
        '"sleeve_id":"sleeve-1273d32417c8"}],"requests":[]}',
        encoding="utf-8",
    )
    path, digest = _write_fixture_factor(tmp_path)

    with pytest.raises(AssistantRemoteError) as conflict:
        record_verified_candidate(
            settings,
            candidate_id="candidate-preview-unhung",
            objective="cannot overwrite a digest-less hung demo",
            source="preview_seed",
            source_digest=digest,
            source_path=str(path),
            factor_id="d34_oracle",
            universe=["SPY", "QQQ"],
        )
    assert conflict.value.code == "candidate_lineage_conflict"


def test_hang_rejects_verified_candidate_without_bound_digest(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    book_path = tmp_path / "assistant_remote" / "book.json"
    book_path.parent.mkdir(parents=True)
    book_path.write_text(
        '{"contract":"hqa.assistant_remote_book/v1","candidates":[{"candidate_id":'
        '"candidate-legacy","objective":"old demo","status":"verified",'
        '"source":"preview_seed","artifact_id":null,"sleeve_id":null}],"requests":[]}',
        encoding="utf-8",
    )

    with pytest.raises(AssistantRemoteError) as missing:
        hang_candidate(settings, candidate_id="candidate-legacy")
    assert missing.value.code == "candidate_digest_required"
    assert project_book(settings)["hung_count"] == 0
    assert not (tmp_path / "api_runs").exists()


def test_hang_binds_source_digest_and_does_not_mint_generic_momentum(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    with pytest.raises(AssistantRemoteError) as missing:
        hang_candidate(settings, candidate_id="candidate-missing")
    assert missing.value.code == "candidate_not_found"

    path, digest = _write_fixture_factor(tmp_path)
    record = _record_current_candidate(
        settings,
        candidate_id="candidate-ready-1",
        daily_returns=_strong_returns(),
        turnover_period=1.0,
        objective="preview verified candidate",
        source="preview_seed",
        source_digest=digest,
        source_path=str(path),
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="a" * 64,
        top_n=2,
    )
    hung = hang_candidate(settings, candidate_id="candidate-ready-1")
    again = hang_candidate(settings, candidate_id="candidate-ready-1")

    assert hung["status"] == "hung"
    assert hung["already_hung"] is False
    assert hung["source_digest"] == digest
    assert hung["factor_id"] == "d34_oracle"
    assert hung["universe"] == ["SPY", "QQQ"]
    assert again["already_hung"] is True
    assert again["sleeve_id"] == hung["sleeve_id"]
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = storage.load_sleeve(hung["sleeve_id"])
    config = storage.load_strategy_config(sleeve.strategy_config_id)
    assert hung_sleeve_eligible(sleeve) is True
    assert sleeve.metadata.get("candidate_code_digest") == digest
    assert sleeve.metadata.get("source_digest") == digest
    assert sleeve.metadata.get("comparison_digest") == record["comparison_digest"]
    assert sleeve.metadata.get("candidate_id") == "candidate-ready-1"
    assert config.symbols == ["SPY", "QQQ"]
    assert config.factor_ids == ["d34_oracle"]
    assert config.strategy_id == "cross_sectional_top_n"
    assert config.top_n == 2
    assert config.factor_ids != ["momentum"]
    assert config.symbols != ["AAPL", "MSFT"]
    book = project_book(settings)
    assert book["verified_count"] == 0
    assert book["hung_count"] == 1
    assert book["candidates"][0]["source_digest"] == digest
    assert book["candidates"][0]["sleeve_id"] == hung["sleeve_id"]


@pytest.mark.pg
def test_hang_persists_allocation_in_canonical_account_without_file_side_write(
    tmp_path,
) -> None:
    base_url = os.environ.get("QS_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    with isolated_test_database_url(base_url, purpose="f3hang") as database_url:
        database = db.Database(database_url, connect_timeout=1)
        db.run_migrations(database)
        settings = _canonical_hang_settings(tmp_path, database_url)
        account_repository = build_paper_account_repository(
            tmp_path / "api_runs",
            settings=settings,
        )
        account_repository.reset(initial_cash=1_000_000.0)
        _record_strong_hang_candidate(
            settings,
            tmp_path,
            candidate_id="candidate-canonical-hang",
        )

        receipt = hang_candidate(
            settings,
            candidate_id="candidate-canonical-hang",
        )

        canonical = account_repository.load()
        assert canonical is not None
        assert account_repository.reconciliation()["status"] == "in_sync"
        assert canonical.sleeve_cash[receipt["sleeve_id"]] == 10_000.0
        assert canonical.sleeve_cash["manual"] == 990_000.0
        assert (
            sum(
                entry.kind == "sleeve_cash_allocated"
                and entry.source == f"strategy:{receipt['sleeve_id']}"
                for entry in canonical.ledger
            )
            == 1
        )
        sleeve = PaperStrategySleeveStorage(tmp_path / "api_runs").load_sleeve(receipt["sleeve_id"])
        assert sleeve.account_id == canonical.account_id
        assert sleeve.cash == canonical.sleeve_cash[sleeve.sleeve_id]
        assert PaperAccountStorage(tmp_path / "api_runs").account_path.exists() is False


@pytest.mark.pg
def test_hang_retry_finalizes_pending_sleeve_without_second_allocation(
    tmp_path,
    monkeypatch,
) -> None:
    base_url = os.environ.get("QS_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    with isolated_test_database_url(base_url, purpose="f3retry") as database_url:
        database = db.Database(database_url, connect_timeout=1)
        db.run_migrations(database)
        settings = _canonical_hang_settings(tmp_path, database_url)
        account_repository = build_paper_account_repository(
            tmp_path / "api_runs",
            settings=settings,
        )
        account_repository.reset(initial_cash=1_000_000.0)
        _record_strong_hang_candidate(
            settings,
            tmp_path,
            candidate_id="candidate-canonical-retry",
        )
        original_finalize = PaperStrategySleeveStorage.finalize_pending_sleeve
        calls = 0

        def fail_once(storage, sleeve_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated finalize failure")
            return original_finalize(storage, sleeve_id)

        monkeypatch.setattr(
            PaperStrategySleeveStorage,
            "finalize_pending_sleeve",
            fail_once,
        )

        with pytest.raises(AssistantRemoteError) as first:
            hang_candidate(
                settings,
                candidate_id="candidate-canonical-retry",
            )
        assert first.value.code == "hang_sleeve_pending"
        sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
        pending = sleeve_storage.list_pending_sleeves()
        assert len(pending) == 1
        pending_id = pending[0].sleeve_id
        assert project_book(settings)["candidates"][0]["status"] == "verified"

        receipt = hang_candidate(
            settings,
            candidate_id="candidate-canonical-retry",
        )

        assert receipt["sleeve_id"] == pending_id
        assert sleeve_storage.list_pending_sleeves() == []
        assert [item.sleeve_id for item in sleeve_storage.list_sleeves()] == [pending_id]
        canonical = account_repository.load()
        assert canonical is not None
        assert canonical.sleeve_cash[pending_id] == 10_000.0
        allocations = [entry for entry in canonical.ledger if entry.kind == "sleeve_cash_allocated"]
        assert len(allocations) == 1


@pytest.mark.pg
def test_hang_retry_repairs_book_binding_without_second_allocation(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    base_url = os.environ.get("QS_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    with isolated_test_database_url(base_url, purpose="f3book") as database_url:
        database = db.Database(database_url, connect_timeout=1)
        db.run_migrations(database)
        settings = _canonical_hang_settings(tmp_path, database_url)
        account_repository = build_paper_account_repository(
            tmp_path / "api_runs",
            settings=settings,
        )
        account_repository.reset(initial_cash=1_000_000.0)
        _record_strong_hang_candidate(
            settings,
            tmp_path,
            candidate_id="candidate-book-retry",
        )
        original_save_book = remote_module.save_book
        calls = 0

        def fail_once(settings_arg, book):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated book replace failure")
            return original_save_book(settings_arg, book)

        monkeypatch.setattr(remote_module, "save_book", fail_once)

        with pytest.raises(AssistantRemoteError) as first:
            hang_candidate(settings, candidate_id="candidate-book-retry")
        assert first.value.code == "hang_book_persist_failed"
        sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
        first_sleeves = sleeve_storage.list_sleeves()
        assert len(first_sleeves) == 1
        original_sleeve_id = first_sleeves[0].sleeve_id
        assert first_sleeves[0].status.value == "paused"
        assert first_sleeves[0].metadata["official_observation"] is False
        assert project_book(settings)["candidates"][0]["status"] == "verified"
        now = datetime(2026, 8, 20, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        assert (
            plan_d34_paper_cycle(
                now=now,
                sleeve_storage=sleeve_storage,
            )["sleeves_checked"]
            == 0
        )

        receipt = hang_candidate(settings, candidate_id="candidate-book-retry")

        assert receipt["sleeve_id"] == original_sleeve_id
        assert project_book(settings)["candidates"][0]["status"] == "hung"
        recovered = sleeve_storage.load_sleeve(original_sleeve_id)
        assert recovered.status.value == "running"
        assert recovered.metadata.get("fossil") is not True
        assert recovered.metadata.get("official_observation") is not False
        canonical = account_repository.load()
        assert canonical is not None
        assert canonical.sleeve_cash[original_sleeve_id] == 10_000.0
        assert canonical.sleeve_cash["manual"] == 990_000.0
        assert sum(entry.kind == "sleeve_cash_allocated" for entry in canonical.ledger) == 1
        assert [item.sleeve_id for item in sleeve_storage.list_sleeves()] == [original_sleeve_id]


def test_book_failure_sleeve_is_inactive_until_same_sleeve_recovery(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id="candidate-inactive-book-failure",
    )
    original_save_book = remote_module.save_book
    calls = 0

    def fail_once(settings_arg, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated book replace failure")
        return original_save_book(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", fail_once)

    with pytest.raises(AssistantRemoteError) as first:
        hang_candidate(settings, candidate_id="candidate-inactive-book-failure")
    assert first.value.code == "hang_book_persist_failed"

    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeves = storage.list_sleeves()
    assert len(sleeves) == 1
    original_sleeve_id = sleeves[0].sleeve_id
    now = datetime(2026, 8, 20, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    planned = plan_d34_paper_cycle(now=now, sleeve_storage=storage)
    assert planned["sleeves_checked"] == 0

    class NoCallRunner:
        def generate_signal_once(self, *_args, **_kwargs):
            raise AssertionError("inactive unbound sleeve reached signal generation")

        def process_pending_executions_once(self, *_args, **_kwargs):
            raise AssertionError("inactive unbound sleeve reached execution processing")

    cycle = run_d34_paper_cycle(
        now=now,
        sleeve_storage=storage,
        runner=NoCallRunner(),
    )
    assert cycle == {
        "sleeves_checked": 0,
        "signals_generated": 0,
        "executions_created": 0,
        "executions_processed": 0,
        "executions_filled": 0,
        "executions_blocked": 0,
        "executions_missed_window": 0,
        "sleeves_failed": 0,
        "sleeve_errors": [],
    }

    recovered = hang_candidate(
        settings,
        candidate_id="candidate-inactive-book-failure",
    )
    assert recovered["sleeve_id"] == original_sleeve_id
    assert [item.sleeve_id for item in storage.list_sleeves()] == [original_sleeve_id]
    assert (
        plan_d34_paper_cycle(
            now=now,
            sleeve_storage=storage,
        )["sleeves_checked"]
        == 1
    )


def test_generic_resume_rejects_book_binding_pending_remote_hang(
    tmp_path,
    monkeypatch,
) -> None:
    from fastapi.testclient import TestClient

    from quant_system.api.server import create_app
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = "candidate-generic-resume-blocked"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    original_save_book = remote_module.save_book
    calls = 0

    def fail_book_once(settings_arg, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated book replace failure")
        return original_save_book(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", fail_book_once)
    with pytest.raises(AssistantRemoteError) as first:
        hang_candidate(settings, candidate_id=candidate_id)
    assert first.value.code == "hang_book_persist_failed"

    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    orphan = storage.list_sleeves()[0]
    assert orphan.status.value == "paused"
    assert orphan.metadata["hang_activation_state"] == "book_binding_pending"
    projected_orphan = project_book(settings)["candidates"][0]
    assert projected_orphan["activation_eligibility"] == {
        "eligible": True,
        "reason": "recovery_available",
    }
    service = PaperStrategySleeveService(storage)

    with pytest.raises(ValueError, match="remote_hang_binding_pending"):
        service.resume_sleeve(orphan)

    client = TestClient(
        create_app(
            settings=settings,
            output_dir=tmp_path,
            bind_address="127.0.0.1",
        )
    )
    response = client.post(f"/api/paper/strategy-sleeves/{orphan.sleeve_id}/resume")
    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "invalid_strategy_sleeve_state",
        "message": "remote_hang_binding_pending",
    }

    persisted = storage.load_sleeve(orphan.sleeve_id)
    assert persisted.status.value == "paused"
    now = datetime(2026, 8, 21, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    planned = plan_d34_paper_cycle(now=now, sleeve_storage=storage)
    assert planned["sleeves_checked"] == 0

    class NoCallRunner:
        def generate_signal_once(self, *_args, **_kwargs):
            raise AssertionError("pending remote-hang reached signal generation")

        def process_pending_executions_once(self, *_args, **_kwargs):
            raise AssertionError("pending remote-hang reached execution processing")

    cycle = run_d34_paper_cycle(
        now=now,
        sleeve_storage=storage,
        runner=NoCallRunner(),
    )
    assert cycle == {
        "sleeves_checked": 0,
        "signals_generated": 0,
        "executions_created": 0,
        "executions_processed": 0,
        "executions_filled": 0,
        "executions_blocked": 0,
        "executions_missed_window": 0,
        "sleeves_failed": 0,
        "sleeve_errors": [],
    }

    recovered = hang_candidate(settings, candidate_id=candidate_id)
    assert recovered["sleeve_id"] == orphan.sleeve_id
    assert storage.load_sleeve(orphan.sleeve_id).status.value == "running"
    assert len(storage.list_sleeves()) == 1


def test_book_bound_activation_failure_recovers_original_sleeve(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    candidate_id = "candidate-activation-recovery"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    original_save_sleeve = PaperStrategySleeveStorage.save_sleeve
    calls = 0

    def fail_activation_once(storage, sleeve):
        nonlocal calls
        if sleeve.metadata.get("hang_activation_state") == "active":
            calls += 1
            if calls == 1:
                raise OSError("simulated activation persistence failure")
        return original_save_sleeve(storage, sleeve)

    monkeypatch.setattr(
        PaperStrategySleeveStorage,
        "save_sleeve",
        fail_activation_once,
    )

    with pytest.raises(AssistantRemoteError) as first:
        hang_candidate(settings, candidate_id=candidate_id)
    assert first.value.code == "hang_sleeve_activation_failed"
    book_after_first = project_book(settings)
    candidate_after_first = book_after_first["candidates"][0]
    assert candidate_after_first["status"] == "hung"
    original_sleeve_id = candidate_after_first["sleeve_id"]
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    assert storage.load_sleeve(original_sleeve_id).status.value == "paused"

    receipt = hang_candidate(settings, candidate_id=candidate_id)

    assert receipt["sleeve_id"] == original_sleeve_id
    assert receipt["already_hung"] is True
    recovered = storage.load_sleeve(original_sleeve_id)
    assert recovered.status.value == "running"
    assert recovered.metadata["hang_activation_state"] == "active"
    assert len(storage.list_sleeves()) == 1


@pytest.mark.parametrize("legacy_marker", ["bare", "not_book_bound"])
def test_legacy_running_orphan_stays_cycle_inactive_when_recovery_book_save_fails(
    tmp_path,
    monkeypatch,
    legacy_marker,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = "candidate-legacy-running-orphan"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    original_save_book = remote_module.save_book
    calls = 0

    def fail_initial_book_once(settings_arg, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated initial book replace failure")
        return original_save_book(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", fail_initial_book_once)
    with pytest.raises(AssistantRemoteError) as first:
        hang_candidate(settings, candidate_id=candidate_id)
    assert first.value.code == "hang_book_persist_failed"

    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    orphan = storage.list_sleeves()[0]
    orphan.status = remote_module.StrategySleeveStatus.RUNNING
    legacy_metadata = dict(orphan.metadata)
    legacy_metadata.pop("hang_activation_state", None)
    legacy_metadata.pop("official_observation", None)
    if legacy_marker == "not_book_bound":
        legacy_metadata["fossil"] = True
        legacy_metadata["fossil_reason"] = "not_book_bound"
        legacy_metadata["official_observation"] = False
    else:
        legacy_metadata.pop("fossil", None)
        legacy_metadata.pop("fossil_reason", None)
    orphan.metadata = legacy_metadata
    storage.save_sleeve(orphan)

    def fail_recovery_book(settings_arg, book):
        raise OSError("simulated recovery book replace failure")

    monkeypatch.setattr(remote_module, "save_book", fail_recovery_book)
    with pytest.raises(AssistantRemoteError) as retry:
        hang_candidate(settings, candidate_id=candidate_id)
    assert retry.value.code == "hang_book_persist_failed"

    persisted = storage.load_sleeve(orphan.sleeve_id)
    assert persisted.status.value == "paused"
    now = datetime(2026, 8, 20, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert (
        plan_d34_paper_cycle(
            now=now,
            sleeve_storage=storage,
        )["sleeves_checked"]
        == 0
    )


@pytest.mark.parametrize(
    ("dirty_kind", "expected_code"),
    [
        ("signal", "existing_hang_activity_present"),
        ("allocation", "existing_hang_allocation_invalid"),
    ],
)
def test_legacy_running_dirty_orphan_is_paused_before_recovery_rejection(
    tmp_path,
    monkeypatch,
    dirty_kind,
    expected_code,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = f"candidate-legacy-dirty-{dirty_kind}"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    original_save_book = remote_module.save_book
    calls = 0

    def fail_initial_book_once(settings_arg, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated initial book replace failure")
        return original_save_book(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", fail_initial_book_once)
    with pytest.raises(AssistantRemoteError) as first:
        hang_candidate(settings, candidate_id=candidate_id)
    assert first.value.code == "hang_book_persist_failed"

    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    orphan = storage.list_sleeves()[0]
    orphan.status = remote_module.StrategySleeveStatus.RUNNING
    legacy_metadata = dict(orphan.metadata)
    legacy_metadata.pop("hang_activation_state", None)
    legacy_metadata["fossil"] = True
    legacy_metadata["fossil_reason"] = "not_book_bound"
    legacy_metadata["official_observation"] = False
    orphan.metadata = legacy_metadata
    if dirty_kind == "allocation":
        orphan.initial_allocated_cash = 12_345.0
    storage.save_sleeve(orphan)
    if dirty_kind == "signal":
        storage.append_signal(
            StrategySignal.create(
                sleeve=orphan,
                signal_date="2026-08-20",
                data_provider="futu",
                status=SignalStatus.DATA_UNAVAILABLE,
            )
        )

    with pytest.raises(AssistantRemoteError) as retry:
        hang_candidate(settings, candidate_id=candidate_id)
    assert retry.value.code == expected_code

    persisted = storage.load_sleeve(orphan.sleeve_id)
    assert persisted.status.value == "paused"
    assert persisted.metadata["official_observation"] is False
    now = datetime(2026, 8, 20, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert (
        plan_d34_paper_cycle(
            now=now,
            sleeve_storage=storage,
        )["sleeves_checked"]
        == 0
    )


def test_nonrecoverable_preview_fossil_stays_rejected_across_retries(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = "candidate-preview-repeat-rejection"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    receipt = hang_candidate(settings, candidate_id=candidate_id)
    book = remote_module.load_book(settings)
    book["candidates"][0]["status"] = "verified"
    book["candidates"][0]["sleeve_id"] = None
    remote_module.save_book(settings, book)
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = storage.load_sleeve(receipt["sleeve_id"])
    sleeve.metadata["fossil"] = True
    sleeve.metadata["official_observation"] = False
    sleeve.metadata["fossil_reason"] = "preview_seed"
    storage.save_sleeve(sleeve)

    codes: list[str] = []
    for _attempt in range(2):
        with pytest.raises(AssistantRemoteError) as blocked:
            hang_candidate(settings, candidate_id=candidate_id)
        codes.append(blocked.value.code)

    assert codes == [
        "existing_hang_lineage_invalid",
        "existing_hang_lineage_invalid",
    ]
    persisted = storage.load_sleeve(sleeve.sleeve_id)
    assert persisted.status.value == "paused"
    assert persisted.metadata["fossil_reason"] == "preview_seed"
    assert persisted.metadata["official_observation"] is False
    assert persisted.metadata.get("hang_activation_state") != "book_binding_pending"
    now = datetime(2026, 8, 20, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert (
        plan_d34_paper_cycle(
            now=now,
            sleeve_storage=storage,
        )["sleeves_checked"]
        == 0
    )


def test_hang_recovery_rejects_orphan_with_persisted_signal(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = "candidate-dirty-signal-recovery"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    original_save_book = remote_module.save_book
    calls = 0

    def fail_once(settings_arg, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated book replace failure")
        return original_save_book(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", fail_once)
    with pytest.raises(AssistantRemoteError) as first:
        hang_candidate(settings, candidate_id=candidate_id)
    assert first.value.code == "hang_book_persist_failed"

    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    orphan = storage.list_sleeves()[0]
    storage.append_signal(
        StrategySignal.create(
            sleeve=orphan,
            signal_date="2026-08-20",
            data_provider="futu",
            status=SignalStatus.DATA_UNAVAILABLE,
            warnings=["simulated persisted activity"],
        )
    )

    with pytest.raises(AssistantRemoteError) as retry:
        hang_candidate(settings, candidate_id=candidate_id)
    assert retry.value.code == "existing_hang_activity_present"
    assert project_book(settings)["candidates"][0]["status"] == "verified"
    assert storage.load_sleeve(orphan.sleeve_id).status.value == "paused"


@pytest.mark.parametrize(
    "activity_kind",
    ["execution", "fill", "lot", "journal"],
)
def test_hang_recovery_rejects_every_persisted_orphan_activity(
    tmp_path,
    monkeypatch,
    activity_kind,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = f"candidate-dirty-{activity_kind}-recovery"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    original_save_book = remote_module.save_book
    calls = 0

    def fail_once(settings_arg, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated book replace failure")
        return original_save_book(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", fail_once)
    with pytest.raises(AssistantRemoteError) as first:
        hang_candidate(settings, candidate_id=candidate_id)
    assert first.value.code == "hang_book_persist_failed"

    api_runs_dir = tmp_path / "api_runs"
    storage = PaperStrategySleeveStorage(api_runs_dir)
    orphan = storage.list_sleeves()[0]
    if activity_kind == "execution":
        storage.append_execution(
            StrategyExecutionPlan(
                execution_id="strategy-exec-dirty",
                sleeve_id=orphan.sleeve_id,
                account_id=orphan.account_id,
                signal_id="signal-dirty",
                strategy_config_id=orphan.strategy_config_id,
                strategy_config_version=orphan.strategy_config_version,
            )
        )
    elif activity_kind == "fill":
        account_repository = build_paper_account_repository(
            api_runs_dir,
            settings=settings,
        )
        account = account_repository.load()
        assert account is not None
        account.record_event(
            kind="fill",
            source=f"strategy:{orphan.sleeve_id}",
            note="simulated persisted fill activity",
        )
        account_repository.save(account)
    elif activity_kind == "lot":
        storage.save_sleeve_lots(
            orphan.sleeve_id,
            [
                SleeveLot.create(
                    account_id=orphan.account_id,
                    sleeve_id=orphan.sleeve_id,
                    symbol="SPY",
                    quantity=1.0,
                    avg_cost=100.0,
                    source=f"strategy:{orphan.sleeve_id}",
                )
            ],
        )
    else:
        storage.save_execution_journal_pending(
            sleeve_id=orphan.sleeve_id,
            execution_id="strategy-exec-dirty",
            payload={"state": "simulated persisted journal activity"},
        )

    with pytest.raises(AssistantRemoteError) as retry:
        hang_candidate(settings, candidate_id=candidate_id)
    assert retry.value.code == "existing_hang_activity_present"
    assert project_book(settings)["candidates"][0]["status"] == "verified"
    assert storage.load_sleeve(orphan.sleeve_id).status.value == "paused"


def test_hang_recovery_rejects_nonstandard_initial_allocation(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = "candidate-invalid-initial-allocation"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    original_save_book = remote_module.save_book
    calls = 0

    def fail_once(settings_arg, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated book replace failure")
        return original_save_book(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", fail_once)
    with pytest.raises(AssistantRemoteError) as first:
        hang_candidate(settings, candidate_id=candidate_id)
    assert first.value.code == "hang_book_persist_failed"

    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    orphan = storage.list_sleeves()[0]
    orphan.initial_allocated_cash = 12_345.0
    storage.save_sleeve(orphan)

    with pytest.raises(AssistantRemoteError) as retry:
        hang_candidate(settings, candidate_id=candidate_id)
    assert retry.value.code == "existing_hang_allocation_invalid"
    assert project_book(settings)["candidates"][0]["status"] == "verified"
    assert len(storage.list_sleeves()) == 1


def test_hang_mutation_lock_order_is_account_then_sleeve_then_book(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = "candidate-lock-order"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    observed: list[str] = []
    original_account_lock = PaperAccountStorage.mutation_lock
    original_sleeve_lock = PaperStrategySleeveStorage.mutation_lock
    original_book_lock = remote_module._book_mutation_lock

    @contextmanager
    def account_lock(storage, **kwargs):
        observed.append("account")
        with original_account_lock(storage, **kwargs):
            yield

    @contextmanager
    def sleeve_lock(storage, **kwargs):
        observed.append("sleeve")
        with original_sleeve_lock(storage, **kwargs):
            yield

    @contextmanager
    def book_lock(settings_arg, **kwargs):
        observed.append("book")
        with original_book_lock(settings_arg, **kwargs):
            yield

    monkeypatch.setattr(PaperAccountStorage, "mutation_lock", account_lock)
    monkeypatch.setattr(PaperStrategySleeveStorage, "mutation_lock", sleeve_lock)
    monkeypatch.setattr(remote_module, "_book_mutation_lock", book_lock)

    hang_candidate(settings, candidate_id=candidate_id)

    assert observed[:3] == ["account", "sleeve", "book"]


def test_hang_insufficient_funds_returns_typed_error(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    repository = build_paper_account_repository(
        tmp_path / "api_runs",
        settings=settings,
    )
    account = repository.reset(initial_cash=15_000.0)
    account.pending_orders = [
        PendingAccountOrder(
            order_id="manual-pending",
            created_at="2026-08-27T00:00:00Z",
            symbol="AAPL",
            side="buy",
            quantity=60.0,
            limit_price=100.0,
            reserved_cash=6_000.0,
            source="manual",
        )
    ]
    repository.save(account)
    candidate_id = "candidate-insufficient-hang-cash"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )

    with pytest.raises(AssistantRemoteError) as rejected:
        hang_candidate(settings, candidate_id=candidate_id)

    assert rejected.value.code == "hang_insufficient_funds"
    persisted = repository.load()
    assert persisted is not None
    assert persisted.sleeve_cash == {"manual": 15_000.0}
    assert persisted.pending_orders[0].reserved_cash == pytest.approx(6_000.0)
    assert project_book(settings)["candidates"][0]["status"] == "verified"


@pytest.mark.parametrize("lock_kind", ["account", "sleeve", "book"])
def test_hang_lock_timeout_returns_typed_error(
    tmp_path,
    monkeypatch,
    lock_kind,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = f"candidate-{lock_kind}-lock-timeout"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )

    @contextmanager
    def timeout_lock(*_args, **_kwargs):
        raise TimeoutError("simulated lock timeout")
        yield

    if lock_kind == "account":
        monkeypatch.setattr(PaperAccountStorage, "mutation_lock", timeout_lock)
    elif lock_kind == "sleeve":
        monkeypatch.setattr(
            PaperStrategySleeveStorage,
            "mutation_lock",
            timeout_lock,
        )
    else:
        monkeypatch.setattr(remote_module, "_book_mutation_lock", timeout_lock)

    with pytest.raises(AssistantRemoteError) as rejected:
        hang_candidate(settings, candidate_id=candidate_id)
    assert rejected.value.code == "hang_lock_timeout"
    assert project_book(settings)["candidates"][0]["status"] == "verified"


@pytest.mark.parametrize(
    ("failure_kind", "expected_code"),
    [
        ("config", "hang_strategy_config_persist_failed"),
        ("pending", "hang_sleeve_persist_failed"),
    ],
)
def test_hang_expected_persistence_failure_returns_typed_error_without_account_write(
    tmp_path,
    monkeypatch,
    failure_kind,
    expected_code,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    repository = build_paper_account_repository(
        tmp_path / "api_runs",
        settings=settings,
    )
    repository.reset(initial_cash=1_000_000.0)
    candidate_id = f"candidate-{failure_kind}-persist-failure"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    before = repository.load()
    assert before is not None
    before_payload = before.model_dump(mode="json")

    def fail_persist(*_args, **_kwargs):
        raise OSError(f"simulated {failure_kind} persistence failure")

    method = "save_strategy_config" if failure_kind == "config" else "save_pending_sleeve"
    monkeypatch.setattr(PaperStrategySleeveStorage, method, fail_persist)

    with pytest.raises(AssistantRemoteError) as rejected:
        hang_candidate(settings, candidate_id=candidate_id)
    assert rejected.value.code == expected_code
    after = repository.load()
    assert after is not None
    assert after.model_dump(mode="json") == before_payload
    assert project_book(settings)["candidates"][0]["status"] == "verified"


def test_hang_recovery_metadata_persist_failure_returns_typed_error(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = "candidate-recovery-metadata-persist-failure"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )
    original_save_book = remote_module.save_book
    calls = 0

    def fail_book_once(settings_arg, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated book replace failure")
        return original_save_book(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", fail_book_once)
    with pytest.raises(AssistantRemoteError) as first:
        hang_candidate(settings, candidate_id=candidate_id)
    assert first.value.code == "hang_book_persist_failed"

    def fail_sleeve_save(*_args, **_kwargs):
        raise OSError("simulated recovery metadata persistence failure")

    monkeypatch.setattr(
        PaperStrategySleeveStorage,
        "save_sleeve",
        fail_sleeve_save,
    )
    with pytest.raises(AssistantRemoteError) as retry:
        hang_candidate(settings, candidate_id=candidate_id)
    assert retry.value.code == "hang_recovery_sleeve_outcome_unknown"


@pytest.mark.pg
def test_hang_retry_resolves_account_save_outcome_unknown_exactly_once(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )

    base_url = os.environ.get("QS_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    with isolated_test_database_url(base_url, purpose="f3unknown") as database_url:
        database = db.Database(database_url, connect_timeout=1)
        db.run_migrations(database)
        settings = _canonical_hang_settings(tmp_path, database_url)
        account_repository = build_paper_account_repository(
            tmp_path / "api_runs",
            settings=settings,
        )
        account_repository.reset(initial_cash=1_000_000.0)
        _record_strong_hang_candidate(
            settings,
            tmp_path,
            candidate_id="candidate-account-unknown",
        )
        original_save = PostgresPaperAccountRepository.save
        calls = 0

        def commit_then_fail(repository, account, **kwargs):
            nonlocal calls
            calls += 1
            result = original_save(repository, account, **kwargs)
            if calls == 1:
                raise RuntimeError("simulated response loss after commit")
            return result

        monkeypatch.setattr(
            PostgresPaperAccountRepository,
            "save",
            commit_then_fail,
        )

        with pytest.raises(AssistantRemoteError) as first:
            hang_candidate(
                settings,
                candidate_id="candidate-account-unknown",
            )
        assert first.value.code == "hang_account_outcome_unknown"
        sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
        pending = sleeve_storage.list_pending_sleeves()
        assert len(pending) == 1
        pending_id = pending[0].sleeve_id
        canonical_after_first = account_repository.load()
        assert canonical_after_first is not None
        assert canonical_after_first.sleeve_cash[pending_id] == 10_000.0

        receipt = hang_candidate(
            settings,
            candidate_id="candidate-account-unknown",
        )

        assert receipt["sleeve_id"] == pending_id
        assert sleeve_storage.list_pending_sleeves() == []
        canonical = account_repository.load()
        assert canonical is not None
        assert canonical.sleeve_cash[pending_id] == 10_000.0
        assert canonical.sleeve_cash["manual"] == 990_000.0
        assert sum(entry.kind == "sleeve_cash_allocated" for entry in canonical.ledger) == 1


@pytest.mark.pg
def test_hang_retry_after_known_account_save_failure_allocates_once(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution.account_postgres_repository import (
        PostgresPaperAccountRepository,
    )

    base_url = os.environ.get("QS_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    with isolated_test_database_url(base_url, purpose="f3save") as database_url:
        database = db.Database(database_url, connect_timeout=1)
        db.run_migrations(database)
        settings = _canonical_hang_settings(tmp_path, database_url)
        account_repository = build_paper_account_repository(
            tmp_path / "api_runs",
            settings=settings,
        )
        account_repository.reset(initial_cash=1_000_000.0)
        _record_strong_hang_candidate(
            settings,
            tmp_path,
            candidate_id="candidate-save-retry",
        )
        original_save = PostgresPaperAccountRepository.save
        calls = 0

        def fail_before_commit(repository, account, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("simulated save failure before commit")
            return original_save(repository, account, **kwargs)

        monkeypatch.setattr(
            PostgresPaperAccountRepository,
            "save",
            fail_before_commit,
        )

        with pytest.raises(AssistantRemoteError) as first:
            hang_candidate(settings, candidate_id="candidate-save-retry")
        assert first.value.code == "hang_account_persist_failed"
        sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
        assert sleeve_storage.list_pending_sleeves() == []
        assert sleeve_storage.list_sleeves() == []
        unchanged = account_repository.load()
        assert unchanged is not None
        assert unchanged.sleeve_cash == {"manual": 1_000_000.0}
        assert not any(entry.kind == "sleeve_cash_allocated" for entry in unchanged.ledger)
        assert project_book(settings)["candidates"][0]["status"] == "verified"

        receipt = hang_candidate(settings, candidate_id="candidate-save-retry")

        canonical = account_repository.load()
        assert canonical is not None
        assert canonical.sleeve_cash[receipt["sleeve_id"]] == 10_000.0
        assert canonical.sleeve_cash["manual"] == 990_000.0
        assert sum(entry.kind == "sleeve_cash_allocated" for entry in canonical.ledger) == 1


@pytest.mark.pg
def test_hang_canonical_missing_account_fails_without_file_fallback(
    tmp_path,
) -> None:
    base_url = os.environ.get("QS_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    with isolated_test_database_url(base_url, purpose="f3missing") as database_url:
        database = db.Database(database_url, connect_timeout=1)
        db.run_migrations(database)
        settings = _canonical_hang_settings(tmp_path, database_url)
        _record_strong_hang_candidate(
            settings,
            tmp_path,
            candidate_id="candidate-missing-account",
        )

        with pytest.raises(AssistantRemoteError) as missing:
            hang_candidate(
                settings,
                candidate_id="candidate-missing-account",
            )

        assert missing.value.code == "paper_account_bootstrap_required"
        assert PaperAccountStorage(tmp_path / "api_runs").account_path.exists() is False
        sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
        assert sleeve_storage.list_pending_sleeves() == []
        assert sleeve_storage.list_sleeves() == []
        assert project_book(settings)["candidates"][0]["status"] == "verified"


@pytest.mark.pg
def test_canonical_hang_rejects_persisted_partition_gap_without_any_write(
    tmp_path,
) -> None:
    base_url = os.environ.get("QS_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    with isolated_test_database_url(base_url, purpose="f3rawgap") as database_url:
        database = db.Database(database_url, connect_timeout=1)
        db.run_migrations(database)
        settings = _canonical_hang_settings(tmp_path, database_url)
        repository = build_paper_account_repository(
            tmp_path / "api_runs",
            settings=settings,
        )
        repository.reset(initial_cash=1_000_000.0)
        candidate_id = "candidate-canonical-raw-gap"
        _record_strong_hang_candidate(
            settings,
            tmp_path,
            candidate_id=candidate_id,
        )
        with database.connect() as conn:
            row = conn.execute(
                """
                SELECT raw
                FROM quant_system.paper_accounts
                WHERE account_id = 'default'
                """
            ).fetchone()
            assert row is not None
            raw = copy.deepcopy(row[0])
            if isinstance(raw, str):
                raw = json.loads(raw)
            raw["sleeve_cash"]["legacy-gap"] = 10_000.0
            conn.execute(
                """
                UPDATE quant_system.paper_accounts
                SET raw = %s::jsonb
                WHERE account_id = 'default'
                """,
                (json.dumps(raw),),
            )

        before = _canonical_hang_evidence(database, tmp_path)
        assert before["partition_sum"] == 1_010_000.0
        with pytest.raises(AssistantRemoteError) as rejected:
            hang_candidate(settings, candidate_id=candidate_id)
        assert rejected.value.code == "paper_account_partition_invalid"
        assert _canonical_hang_evidence(database, tmp_path) == before
        assert project_book(settings)["candidates"][0]["status"] == "verified"


@pytest.mark.pg
@pytest.mark.parametrize(
    "raw_event_present",
    [False, True],
    ids=["missing-raw-and-materialized", "missing-materialized-only"],
)
def test_canonical_hang_rejects_missing_allocation_event_without_any_write(
    tmp_path,
    raw_event_present,
) -> None:
    base_url = os.environ.get("QS_TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    with isolated_test_database_url(base_url, purpose="f3rawled") as database_url:
        database = db.Database(database_url, connect_timeout=1)
        db.run_migrations(database)
        settings = _canonical_hang_settings(tmp_path, database_url)
        repository = build_paper_account_repository(
            tmp_path / "api_runs",
            settings=settings,
        )
        repository.reset(initial_cash=1_000_000.0)
        candidate_id = "candidate-canonical-ledger-gap"
        _record_strong_hang_candidate(
            settings,
            tmp_path,
            candidate_id=candidate_id,
        )
        with database.connect() as conn:
            row = conn.execute(
                """
                SELECT raw
                FROM quant_system.paper_accounts
                WHERE account_id = 'default'
                """
            ).fetchone()
            assert row is not None
            raw = copy.deepcopy(row[0])
            if isinstance(raw, str):
                raw = json.loads(raw)
            raw["sleeve_cash"]["manual"] = 990_000.0
            raw["sleeve_cash"]["legacy-no-event"] = 10_000.0
            if raw_event_present:
                event = copy.deepcopy(raw["ledger"][-1])
                event["entry_id"] = "ledger-raw-only-allocation"
                event["kind"] = "sleeve_cash_allocated"
                event["source"] = "strategy:legacy-no-event"
                event["note"] = "raw-only allocation evidence"
                raw["ledger"].append(event)
            conn.execute(
                """
                UPDATE quant_system.paper_accounts
                SET raw = %s::jsonb
                WHERE account_id = 'default'
                """,
                (json.dumps(raw),),
            )

        before = _canonical_hang_evidence(database, tmp_path)
        assert before["partition_sum"] == 1_000_000.0
        with pytest.raises(AssistantRemoteError) as rejected:
            hang_candidate(settings, candidate_id=candidate_id)
        assert rejected.value.code == "paper_account_allocation_ledger_invalid"
        assert _canonical_hang_evidence(database, tmp_path) == before
        assert project_book(settings)["candidates"][0]["status"] == "verified"


def test_hang_reads_candidate_strategy_and_top_n(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    record = _record_current_candidate(
        settings,
        candidate_id="candidate-reversion",
        daily_returns=_strong_returns(),
        turnover_period=1.0,
        objective="mean reversion hang",
        source="preview_seed",
        source_digest=digest,
        source_path=str(path),
        factor_id="d34_oracle",
        universe=["SPY", "QQQ", "IWM", "DIA"],
        comparison_digest="b" * 64,
        operator="mean_reversion",
        strategy_id="mean_reversion_top_n",
        top_n=3,
    )
    assert record["strategy_id"] == "mean_reversion_top_n"
    assert record["top_n"] == 3
    hung = hang_candidate(settings, candidate_id="candidate-reversion")
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = storage.load_sleeve(hung["sleeve_id"])
    config = storage.load_strategy_config(sleeve.strategy_config_id)
    assert hung["strategy_id"] == "mean_reversion_top_n"
    assert hung["top_n"] == 3
    assert config.strategy_id == "mean_reversion_top_n"
    assert config.top_n == 3
    assert config.name == "隔离测试因子"
    assert sleeve.metadata["display_name_zh"] == "隔离测试因子"
    again = hang_candidate(settings, candidate_id="candidate-reversion")
    assert again["already_hung"] is True
    assert again["strategy_id"] == "mean_reversion_top_n"
    assert again["top_n"] == 3
    assert resolve_hang_sleeve_strategy(
        {"operator": "mean_reversion"}, universe=["SPY", "QQQ"]
    ) == ("cross_sectional_top_n", 1)


def test_d34_mean_reversion_artifact_hangs_as_cross_sectional(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.d34.research_driver import ResearchProposal, render_factor_source
    from tests.current_capital_fixtures import d34_candidate_kwargs

    settings = _settings(tmp_path, monkeypatch)
    source, digest = render_factor_source(
        proposal=ResearchProposal(
            title="Twenty day reversal",
            thesis="Names that fell should bounce; score is already inverted.",
            operator="mean_reversion",
            short_window=1,
            long_window=20,
            rationale="Catalog mean-reversion negates pct_change.",
        ),
        factor_id="d34_mean_reversion",
    )
    job_root = tmp_path / "_runtime" / "d34" / "jobs" / "job-mean-rev"
    research_dir = job_root / "research" / "research-mean-rev"
    research_dir.mkdir(parents=True)
    path = research_dir / "candidate_factor.py"
    path.write_text(source, encoding="utf-8")
    replay_dir = job_root / "platform-replay" / "replay-1"
    replay_dir.mkdir(parents=True)
    returns = _strong_returns()
    (replay_dir / "receipt.json").write_text(
        json.dumps({"daily_returns": returns, "metrics": {"turnover": 0.1}}),
        encoding="utf-8",
    )
    original = d34_candidate_kwargs(
        settings, candidate_id="artifact-mean-rev", source_path=path,
        source_digest=digest, factor_id="d34_mean_reversion",
        universe=["SPY", "QQQ", "NVDA", "AAPL"], daily_returns=returns,
        return_dates=_xnys_return_dates(len(returns)), turnover_period=0.1,
    )
    record = record_verified_from_dual_engine_artifact(
        settings,
        artifact_id="artifact-mean-rev",
        source_path=Path(original["source_path"]),
        source_digest=digest,
        comparison_digest=original["comparison_digest"],
        universe=["SPY", "QQQ", "NVDA", "AAPL"],
        objective="dual-engine mean reversion",
        top_n=1,
        operator="mean_reversion",
        daily_returns=returns,
        turnover_period=0.1,
        return_dates=_xnys_return_dates(len(returns)),
        evidence_ref=original["evidence_ref"],
    )
    assert record["strategy_id"] == "cross_sectional_top_n"
    assert record["top_n"] == 1
    assert record["operator"] == "mean_reversion"
    hung = hang_candidate(settings, candidate_id=record["candidate_id"])
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = storage.load_sleeve(hung["sleeve_id"])
    config = storage.load_strategy_config(sleeve.strategy_config_id)
    assert hung["strategy_id"] == "cross_sectional_top_n"
    assert hung["top_n"] == 1
    assert config.strategy_id == "cross_sectional_top_n"
    assert config.top_n == 1


def test_dual_engine_artifact_backfill_is_verified_and_not_hung(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)

    record = record_verified_from_dual_engine_artifact(
        settings,
        artifact_id="artifact-test-1",
        source_path=path,
        source_digest=digest,
        comparison_digest="c" * 64,
        universe=["SPY", "QQQ"],
        objective="dual-engine accepted fixture",
        job_key="request:2026-08-15:fixture",
        daily_returns=_strong_returns(),
        turnover_period=0.2,
        return_dates=_xnys_return_dates(len(_strong_returns())),
        evidence_ref=CandidateEvidenceRef(
            job_id="job-backfill-12345678",
            run_id="attempt-backfill-12345678",
            manifest_digest="a" * 64,
            qlib_raw_receipt_digest="b" * 64,
            platform_raw_receipt_digest="c" * 64,
        ),
    )

    assert record["status"] == "verified"
    assert record["sleeve_id"] is None
    assert record["source_digest"] == digest
    assert record["factor_id"] == "d34_oracle"
    assert record["artifact_id"] == "artifact-test-1"
    assert record["job_key"] == "request:2026-08-15:fixture"
    book = project_book(settings)
    assert book["verified_count"] == 1
    assert book["hung_count"] == 0


def test_research_operation_is_stable_and_material_mismatch_writes_nothing(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    enqueued: list[object] = []

    class Jobs:
        def enqueue(self, command):
            enqueued.append(command)
            return {
                "job_id": "job-chat-research-1",
                "job_key": command.job_key,
            }

    material = {
        "note": "Research the supplied twenty-day reversal formula",
        "formula": "Ref($close, 20) / $close - 1",
        "universe": ["SPY", "QQQ"],
    }
    material_digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    operation_id = _research_operation_id("platform-session-1", "hermes-session-1", material_digest)
    kwargs = {
        "jobs": Jobs(),
        "operation_id": operation_id,
        "material_digest": material_digest,
        "command_id": "command-chat-1",
        "platform_session_id": "platform-session-1",
        "hermes_session_id": "hermes-session-1",
        "hermes_run_id": "hermes-run-1",
        **material,
    }

    first = intake_research_operation(settings, **kwargs)
    second = intake_research_operation(settings, **kwargs)

    assert first == second
    assert first["status"] == "queued"
    assert first["job_id"] == "job-chat-research-1"
    assert len(enqueued) == 1
    assert enqueued[0].input_document["formula"] == material["formula"]
    assert len(project_book(settings)["requests"]) == 1
    projection = project_research_request(settings, operation_id=operation_id)
    assert projection == first
    running_receipt = project_terminal_research_results(
        settings,
        jobs=type(
            "RunningJobs",
            (),
            {
                "list": lambda *_args, **_kwargs: [
                    {
                        "job_id": "job-chat-research-1",
                        "job_key": first["job_key"],
                        "state": "running",
                    }
                ]
            },
        )(),
    )
    assert running_receipt["status_updates"] == 1
    running = project_research_request(settings, operation_id=operation_id)
    assert running is not None
    assert running["status"] == "running"
    assert running["terminal"] is False
    assert running["evidence"] is None
    before = _tree_hash(tmp_path)

    with pytest.raises(AssistantRemoteError) as mismatch:
        intake_research_operation(
            settings,
            **{
                **kwargs,
                "universe": ["QQQ", "SPY"],
            },
        )

    assert mismatch.value.code == "research_material_digest_mismatch"
    assert len(enqueued) == 1
    assert _tree_hash(tmp_path) == before

    unsupported = {**material, "formula": "Buy an options spread when news is positive"}
    unsupported_digest = digest_document(unsupported)
    with pytest.raises(AssistantRemoteError, match="research_formula_unsupported"):
        intake_research_operation(
            settings,
            **{
                **kwargs,
                **unsupported,
                "material_digest": unsupported_digest,
                "operation_id": _research_operation_id(
                    "platform-session-1", "hermes-session-1", unsupported_digest
                ),
            },
        )
    assert len(enqueued) == 1
    assert _tree_hash(tmp_path) == before


@pytest.mark.parametrize("recovered", [False, True])
@pytest.mark.parametrize("activation_error", [None, "hang_insufficient_funds", "activation_write"])
def test_chat_research_auto_activates_once_or_preserves_verified_candidate(
    tmp_path,
    monkeypatch,
    recovered,
    activation_error,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    job_id = "job-chat-accepted"
    command_id = "command-chat-accepted"
    material = {
        "note": "Research the supplied twenty-day reversal formula",
        "formula": "Ref($close, 20) / $close - 1",
        "universe": ["SPY", "QQQ"],
    }
    material_digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    operation_id = _research_operation_id(
        "platform-session-accepted", "hermes-session-accepted", material_digest
    )
    commands: list[object] = []

    class Jobs:
        def enqueue(self, command):
            commands.append(command)
            return {"job_id": job_id, "job_key": command.job_key}

    queued = intake_research_operation(
        settings,
        jobs=Jobs(),
        operation_id=operation_id,
        material_digest=material_digest,
        command_id=command_id,
        platform_session_id="platform-session-accepted",
        hermes_session_id="hermes-session-accepted",
        hermes_run_id="hermes-run-accepted",
        **material,
    )
    digest, job_root = _write_accepted_preauth_job(
        tmp_path,
        job_id=job_id,
        job_key=queued["job_key"],
    )
    request_document = json.loads((job_root / "research_request.json").read_text(encoding="utf-8"))
    request_document["job_id"] = job_id
    request_document["objective"] = load_book(settings)["requests"][0]["objective"]
    (job_root / "research_request.json").write_text(
        json.dumps(request_document),
        encoding="utf-8",
    )
    registry = _bind_chat_research_evidence(
        job_root=job_root,
        request=load_book(settings)["requests"][0],
        input_document=commands[0].input_document,
    )
    normal_cycle = (job_root / "cycle_receipt.json").read_bytes()
    if not recovered:
        (job_root / "evidence_manifest.json").unlink()
        evil = job_root / "platform-replay" / "evil" / "receipt.json"
        evil.parent.mkdir(parents=True, exist_ok=True)
        evil.write_text(
            json.dumps(
                {
                    "daily_returns": [-0.9] * len(_strong_returns()),
                    "return_dates": [
                        f"2026-02-{index + 1:02d}" for index in range(len(_strong_returns()))
                    ],
                    "metrics": {"turnover": 999.0},
                }
            ),
            encoding="utf-8",
        )
    if recovered:
        (job_root / "cycle_receipt.json").write_text(
            json.dumps(
                {
                    "phase": "needs_recovery",
                    "job_id": job_id,
                    "code": "artifact_registry_unavailable",
                }
            ),
            encoding="utf-8",
        )
        unknown = reconcile_research_result(
            settings,
            job_id=job_id,
            registry=registry,
        )
        assert unknown is not None
        assert unknown["outcome"] == "outcome_unknown"
        assert project_book(settings)["candidates"] == []
        (job_root / "cycle_receipt.json").write_bytes(normal_cycle)
    _write_accepted_preauth_job(
        tmp_path,
        job_id="job-unrelated-accepted",
        job_key="unrelated-job-key",
    )

    with monkeypatch.context() as activation_patch:
        if activation_error == "activation_write":
            save_sleeve = PaperStrategySleeveStorage.save_sleeve
            failed = False

            def fail_activation_once(storage, sleeve):
                nonlocal failed
                if sleeve.status.value == "running" and not failed:
                    failed = True
                    raise OSError("activation disk write interrupted")
                return save_sleeve(storage, sleeve)

            activation_patch.setattr(
                PaperStrategySleeveStorage, "save_sleeve", fail_activation_once,
            )
        elif activation_error:
            def reject_activation(*_args, **_kwargs):
                raise AssistantRemoteError(activation_error)

            activation_patch.setattr(remote_module, "hang_candidate", reject_activation)
        projected = project_terminal_research_results(settings, registry=registry)
        first = project_research_request(settings, operation_id=operation_id)
        projected_again = project_terminal_research_results(settings, registry=registry)
        second = project_research_request(settings, operation_id=operation_id)

    if activation_error == "activation_write":
        assert first["outcome"] == "outcome_unknown"
        assert first["result_reply"]["code"] == "hang_sleeve_activation_failed"
        assert projected_again["requests_checked"] == 1
        assert second["result_reply"]["code"] == "paper_running"
        assert (
            project_terminal_research_results(settings, registry=registry)["requests_checked"] == 0
        )
        first = second
        activation_error = None
    else:
        assert projected_again["requests_checked"] == 0
    assert first == second
    assert first is not None
    assert projected["requests_projected"] == 1
    assert (job_root / "evidence_manifest.json").is_file()
    assert first["status"] == "candidate_ready"
    assert first["terminal"] is True
    assert first["outcome"] == "verified_candidate"
    assert first["source_digest"] == digest
    assert first["result_reply"]["status"] == "candidate_ready"
    assert first["result_reply"]["code"] == (
        f"paper_activation_failed:{activation_error}" if activation_error else "paper_running"
    )
    if activation_error:
        assert activation_error in first["result_reply"]["message"]
    else:
        assert "$10,000" in first["result_reply"]["message"]
    assert first["result_reply"]["display_name_zh"] == "隔离测试因子"
    assert first["result_reply"]["summary_zh"].startswith("标的范围：")
    assert first["result_reply"]["provenance"]["candidate_id"] == first["candidate_id"]
    assert first["evidence"]["comparison"]["accepted"] is True
    assert first["evidence"]["cost_model"] == {
        "commission_bps": 1.0,
        "slippage_bps": 5.0,
    }
    assert first["evidence"]["dsr"]["passed"] is True
    evidence_projection = project_research_evidence(
        settings,
        operation_id=operation_id,
        manifest_digest=first["evidence"]["manifest_digest"],
    )
    assert evidence_projection is not None
    assert evidence_projection["candidate_id"] == first["candidate_id"]
    assert project_research_request(settings, operation_id=operation_id) == first
    book = project_book(settings)
    assert book["verified_count"] == (1 if activation_error else 0)
    assert book["hung_count"] == (0 if activation_error else 1)
    assert len(book["candidates"]) == 1
    assert (book["candidates"][0]["sleeve_id"] is None) == bool(activation_error)
    assert book["candidates"][0]["performance"]["daily_returns"] == _strong_returns()
    assert book["candidates"][0]["performance"]["turnover_period"] == 0.2

    before_hang = PaperStrategySleeveStorage(tmp_path / "api_runs").list_sleeves()
    hung = hang_candidate(settings, candidate_id=first["candidate_id"])
    replayed = hang_candidate(settings, candidate_id=first["candidate_id"])
    sleeves = PaperStrategySleeveStorage(tmp_path / "api_runs").list_sleeves()

    assert len(before_hang) == (0 if activation_error else 1)
    assert hung["already_hung"] is (not activation_error)
    assert replayed["already_hung"] is True
    assert replayed["sleeve_id"] == hung["sleeve_id"]
    assert len(sleeves) == 1
    assert sleeves[0].sleeve_id == hung["sleeve_id"]
    assert sleeves[0].initial_allocated_cash == 10_000.0
    assert sleeves[0].status.value == "running"
    account = PaperAccountStorage(tmp_path / "api_runs").load()
    assert sum(entry.kind == "sleeve_cash_allocated" for entry in account.ledger) == 1
    assert project_book(settings)["hung_count"] == 1


@pytest.mark.parametrize(
    ("returns_kind", "turnover_period", "expected_code"),
    [
        ("zero", 0.2, "dsr_performance_required"),
        ("strong", 1_000_000.0, "cost_sensitivity_failed"),
        ("correlated", 0.2, "correlated_duplicate"),
    ],
)
def test_chat_research_admission_gates_fail_before_candidate_write(
    tmp_path: Path,
    monkeypatch,
    returns_kind: str,
    turnover_period: float,
    expected_code: str,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    daily_returns = [0.0] * 240 if returns_kind == "zero" else _strong_returns()
    if returns_kind == "correlated":
        source_path, _source_digest = _write_fixture_factor(tmp_path)
        peer_path = tmp_path / "hung-peer-factor.py"
        peer_path.write_text(
            source_path.read_text(encoding="utf-8") + "\n# distinct hung peer\n",
            encoding="utf-8",
        )
        peer_digest = hashlib.sha256(peer_path.read_bytes()).hexdigest()
        _record_current_candidate(
            settings,
            candidate_id="existing-hung-peer",
            objective="Existing comparable hung factor",
            source="d34_artifact",
            source_digest=peer_digest,
            source_path=str(peer_path),
            factor_id="d34_oracle",
            universe=["SPY", "QQQ"],
            comparison_digest=(
                "250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1"
            ),
            daily_returns=_strong_returns(),
            turnover_period=0.2,
            return_dates=_xnys_return_dates(len(_strong_returns())),
        )
        hang_candidate(settings, candidate_id="existing-hung-peer")
    job_id = "job-chat-gate-rejected"
    material = {
        "note": "Research the supplied twenty-day reversal formula",
        "formula": "Ref($close, 20) / $close - 1",
        "universe": ["SPY", "QQQ"],
    }
    material_digest = digest_document(material)
    operation_id = _research_operation_id(
        "platform-session-gate",
        "hermes-session-gate",
        material_digest,
    )
    commands: list[object] = []

    class Jobs:
        def enqueue(self, command):
            commands.append(command)
            return {"job_id": job_id, "job_key": command.job_key}

    queued = intake_research_operation(
        settings,
        jobs=Jobs(),
        operation_id=operation_id,
        material_digest=material_digest,
        command_id="command-gate",
        platform_session_id="platform-session-gate",
        hermes_session_id="hermes-session-gate",
        hermes_run_id="hermes-run-gate",
        **material,
    )
    _digest_value, job_root = _write_accepted_preauth_job(
        tmp_path,
        job_id=job_id,
        job_key=queued["job_key"],
    )
    registry = _bind_chat_research_evidence(
        job_root=job_root,
        request=load_book(settings)["requests"][0],
        input_document=commands[0].input_document,
        daily_returns=daily_returns,
        turnover_period=turnover_period,
    )

    projected = reconcile_research_result(settings, job_id=job_id, registry=registry)

    assert projected is not None
    assert projected["outcome"] == "outcome_unknown"
    assert projected["result_reply"]["code"] == expected_code
    candidates = project_book(settings)["candidates"]
    assert all(item.get("status") != "verified" for item in candidates)
    assert len(candidates) == (1 if returns_kind == "correlated" else 0)


def test_research_operation_response_loss_replay_converges_on_one_job(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    commands: dict[str, dict[str, str]] = {}
    enqueue_calls = 0

    class Jobs:
        def enqueue(self, command):
            nonlocal enqueue_calls
            enqueue_calls += 1
            return commands.setdefault(
                command.job_key,
                {"job_id": "job-response-loss", "job_key": command.job_key},
            )

    material = {
        "note": "Research the supplied twenty-day reversal formula",
        "formula": "Ref($close, 20) / $close - 1",
        "universe": ["SPY", "QQQ"],
    }
    material_digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    command_id = "command-response-loss"
    kwargs = {
        "jobs": Jobs(),
        "operation_id": _research_operation_id(
            "platform-session-response-loss",
            "hermes-session-response-loss",
            material_digest,
        ),
        "material_digest": material_digest,
        "command_id": command_id,
        "platform_session_id": "platform-session-response-loss",
        "hermes_session_id": "hermes-session-response-loss",
        "hermes_run_id": "hermes-run-response-loss",
        **material,
    }
    original_save = remote_module.save_book
    failed = False

    def lose_first_response(settings_arg, book):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("simulated response loss after durable enqueue")
        return original_save(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", lose_first_response)
    with pytest.raises(OSError, match="simulated response loss"):
        intake_research_operation(settings, **kwargs)

    replay = intake_research_operation(settings, **kwargs)

    assert replay["job_id"] == "job-response-loss"
    assert enqueue_calls == 2
    assert len(commands) == 1
    assert len(project_book(settings)["requests"]) == 1


@pytest.mark.parametrize(
    ("job_state", "outcome_code", "expected_status"),
    [
        ("outcome_unknown", "lease_expired", "outcome_unknown"),
        ("rejected", "d34_preflight_llm_failed", "failed"),
    ],
)
def test_terminal_job_authority_without_receipt_projects_typed_zero_candidate(
    tmp_path: Path,
    monkeypatch,
    job_state: str,
    outcome_code: str,
    expected_status: str,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    command = None

    class Jobs:
        def enqueue(self, value):
            nonlocal command
            command = value
            return {"job_id": "job-authority-terminal", "job_key": value.job_key}

        def list(self, **_kwargs):
            assert command is not None
            return [
                {
                    "job_id": "job-authority-terminal",
                    "job_key": command.job_key,
                    "input_digest": command.input_digest,
                    "state": job_state,
                    "outcome_code": outcome_code,
                }
            ]

    material = {
        "note": "Research the supplied twenty-day reversal formula",
        "formula": "Ref($close, 20) / $close - 1",
        "universe": ["SPY", "QQQ"],
    }
    material_digest = digest_document(material)
    operation_id = _research_operation_id(
        "platform-session-authority",
        "hermes-session-authority",
        material_digest,
    )
    jobs = Jobs()
    intake_research_operation(
        settings,
        jobs=jobs,
        operation_id=operation_id,
        material_digest=material_digest,
        command_id="command-authority",
        platform_session_id="platform-session-authority",
        hermes_session_id="hermes-session-authority",
        hermes_run_id="hermes-run-authority",
        **material,
    )

    first = project_terminal_research_results(settings, jobs=jobs)
    book_path = tmp_path / "assistant_remote" / "book.json"
    after_first = book_path.read_bytes()
    projected = project_research_request(settings, operation_id=operation_id)
    second = project_terminal_research_results(settings, jobs=jobs)

    assert first["requests_projected"] == 1
    assert second["requests_projected"] == (1 if job_state == "outcome_unknown" else 0)
    assert book_path.read_bytes() == after_first
    assert projected is not None
    assert projected["status"] == expected_status
    assert projected["outcome"] == expected_status
    assert projected["result_reply"]["code"] == outcome_code
    assert projected["evidence"]["manifest_digest"]
    assert project_book(settings)["candidates"] == []


@pytest.mark.parametrize(
    ("phase_document", "status", "outcome"),
    [
        (
            {"phase": "failed", "failed_phase": "snapshot", "code": "snapshot_failed"},
            "failed",
            "failed",
        ),
        (
            {"phase": "failed", "failed_phase": "research", "code": "research_lost"},
            "outcome_unknown",
            "outcome_unknown",
        ),
        (
            {"phase": "needs_recovery", "code": "registry_outcome_unknown"},
            "outcome_unknown",
            "outcome_unknown",
        ),
        (
            {
                "phase": "candidate_ready",
                "contract": "invalid.contract/v1",
                "comparison_accepted": True,
                "code": "accepted_receipt_invalid",
            },
            "outcome_unknown",
            "outcome_unknown",
        ),
    ],
)
def test_reconcile_research_result_failure_never_creates_candidate(
    tmp_path,
    monkeypatch,
    phase_document,
    status,
    outcome,
) -> None:
    phase_document = {
        **phase_document,
        "error": "SECRET_SENTINEL must remain inside the worker receipt",
    }
    settings = _settings(tmp_path, monkeypatch)
    job_id = "job-chat-failure"
    command_id = "command-chat-failure"
    material = {
        "note": "Research the supplied twenty-day reversal formula",
        "formula": "Ref($close, 20) / $close - 1",
        "universe": ["SPY", "QQQ"],
    }
    material_digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    operation_id = _research_operation_id(
        "platform-session-failure", "hermes-session-failure", material_digest
    )

    class Jobs:
        def enqueue(self, command):
            return {"job_id": job_id, "job_key": command.job_key}

    intake_research_operation(
        settings,
        jobs=Jobs(),
        operation_id=operation_id,
        material_digest=material_digest,
        command_id=command_id,
        platform_session_id="platform-session-failure",
        hermes_session_id="hermes-session-failure",
        hermes_run_id="hermes-run-failure",
        **material,
    )
    job_root = tmp_path / "_runtime" / "d34" / "jobs" / job_id
    job_root.mkdir(parents=True)
    (job_root / "cycle_receipt.json").write_text(
        json.dumps({"job_id": job_id, **phase_document}),
        encoding="utf-8",
    )

    projection = reconcile_research_result(settings, job_id=job_id)

    assert projection is not None
    assert projection["status"] == status
    assert projection["terminal"] is True
    assert projection["outcome"] == outcome
    assert projection["result_reply"]["status"] == status
    assert projection["result_reply"]["code"] == phase_document["code"]
    assert "candidate_id" not in projection
    assert "source_digest" not in projection
    projected_book = project_book(settings)
    assert projected_book["candidates"] == []
    assert "SECRET_SENTINEL" not in json.dumps(projection)
    assert "SECRET_SENTINEL" not in json.dumps(projected_book)


def test_project_book_overlays_hung_momentum_correction_without_rewriting_objective(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    book_path = tmp_path / "assistant_remote" / "book.json"
    book_path.parent.mkdir(parents=True)
    objective = "Discover and falsify one daily cross-sectional momentum variant."
    book_path.write_text(
        json.dumps(
            {
                "contract": "hqa.assistant_remote_book/v1",
                "candidates": [
                    {
                        "candidate_id": "artifact-d489583fb04bdc04",
                        "objective": objective,
                        "status": "hung",
                        "source_digest": "a" * 64,
                        "fossil": False,
                    }
                ],
                "requests": [],
            }
        ),
        encoding="utf-8",
    )

    book = project_book(settings)
    hung = book["candidates"][0]
    assert hung["objective"] == objective
    assert hung["display_name_zh"] == "21 日横截面动量策略"
    assert "模拟运行中" in hung["summary_zh"]
    assert "主人已知情" in hung["description_note"]
    assert "普通 21 日动量" in hung["description_note"]


def test_project_book_reads_digest_bound_generated_factor_zh_name(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    record = record_verified_candidate(
        settings,
        candidate_id="candidate-zh-presentation",
        objective="Model supplied English objective.",
        source="d34_artifact",
        source_digest=digest,
        source_path=str(path),
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
    )

    assert record["display_name_zh"] == "隔离测试因子"
    assert record["summary_zh"] == "标的范围：SPY、QQQ；研究验证已完成。"

    projected = project_book(settings)["candidates"][0]

    assert projected["display_name_zh"] == "隔离测试因子"
    assert projected["summary_zh"] == "标的范围：SPY、QQQ；研究验证已完成。"


def _write_frozen_definition(tmp_path: Path, payload: dict) -> tuple[Path, str]:
    directory = tmp_path / "strategy_library" / ("strategy-" + "a" * 24)
    directory.mkdir(parents=True)
    path = directory / "definition.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _definition_candidate_item(path: Path, digest: str, **overrides) -> dict:
    item = {
        "candidate_id": "strategy-" + "b" * 24,
        "source": "strategy_definition",
        "source_path": str(path),
        "source_digest": digest,
        "factor_id": "definition_" + "a" * 24,
        "universe": ["AAA", "BBB"],
        "status": "verified",
        "display_name_zh": "横截面选股研究因子",
    }
    item.update(overrides)
    return item


def test_strategy_definition_candidate_shows_frozen_definition_title(tmp_path) -> None:
    from quant_system.execution import assistant_remote

    path, digest = _write_frozen_definition(
        tmp_path, {"title": "周频反转精选 / baseline", "symbols": ["AAA", "BBB"]}
    )
    item = _definition_candidate_item(path, digest)

    name, summary = assistant_remote._candidate_presentation_zh(item)

    # The frozen definition.json title outranks the generic stored display name,
    # and is transformed by the same rule the strategy directory uses.
    assert name == "周频反转精选 · 原组合"
    assert summary == "标的范围：AAA、BBB；研究验证已完成。"


def test_definition_title_must_match_frozen_digest_or_fall_back(tmp_path) -> None:
    from quant_system.execution import assistant_remote

    path, _ = _write_frozen_definition(tmp_path, {"title": "被篡改的标题"})
    stale = "c" * 64
    item = _definition_candidate_item(path, stale, definition_digest=stale)

    name, _ = assistant_remote._candidate_presentation_zh(item)

    assert name == "策略定义 " + stale[:12]


def test_definition_without_title_uses_deterministic_digest_label(tmp_path) -> None:
    from quant_system.execution import assistant_remote

    path, digest = _write_frozen_definition(tmp_path, {"symbols": ["AAA", "BBB"]})
    item = _definition_candidate_item(path, digest, definition_digest="d" * 64)

    name, _ = assistant_remote._candidate_presentation_zh(item)

    assert name == "策略定义 " + "d" * 12


def test_non_definition_source_keeps_stored_name(tmp_path) -> None:
    from quant_system.execution import assistant_remote

    # A digest-bound d34 artifact whose file happens to be JSON must never pick
    # up a definition title: only source == "strategy_definition" reads it.
    path, digest = _write_frozen_definition(tmp_path, {"title": "不该出现"})
    item = _definition_candidate_item(
        path, digest, source="d34_artifact", display_name_zh="隔离测试因子"
    )

    name, _ = assistant_remote._candidate_presentation_zh(item)

    assert name == "隔离测试因子"


def test_registered_definition_candidate_projects_frozen_title(tmp_path, monkeypatch) -> None:
    from quant_system.research import strategy_library
    from quant_system.research.strategy_definition import StrategyDefinition

    settings = _settings(tmp_path, monkeypatch)
    definition = StrategyDefinition(
        kind="formula",
        title="周频五日反转 / augmented",
        symbols=("AAA", "BBB"),
        benchmark_symbol="SPY",
        history_start="2015-01-01",
        rebalance="weekly",
        top_n=1,
        formula={"expression": "-Mean($close/Ref($close,1)-1,5)"},
    )
    entry = strategy_library._save_definition(settings, definition, {})
    directory = tmp_path / "strategy_library" / entry["strategy_id"]

    record = record_verified_candidate(
        settings,
        candidate_id="strategy-" + "e" * 24,
        objective="Model supplied English objective.",
        source="strategy_definition",
        source_digest=entry["source_sha256"],
        source_path=str(directory / "definition.json"),
        factor_id="definition_" + definition.content_digest[:24],
        universe=list(definition.symbols),
    )

    assert record["display_name_zh"] == "周频五日反转 · 加入新因子"

    projected = project_book(settings)["candidates"][0]

    assert projected["display_name_zh"] == "周频五日反转 · 加入新因子"
    assert projected["summary_zh"] == "标的范围：AAA、BBB；研究验证已完成。"


def test_project_book_projects_current_activation_eligibility_without_writing(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    _record_current_candidate(
        settings,
        candidate_id="candidate-activation-ready",
        objective="strong candidate",
        source="d34_artifact",
        source_digest=digest,
        source_path=str(path),
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        daily_returns=_strong_returns(),
        turnover_period=0.2,
    )
    _record_current_candidate(
        settings,
        candidate_id=READ_ONLY_DSR_CANDIDATE_ID,
        objective="research review only",
        source="d34_artifact",
        source_digest=digest,
        source_path=str(path),
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        daily_returns=_strong_returns(),
        turnover_period=1_000_000.0,
    )
    stored_before = load_book(settings)

    projected = {
        item["candidate_id"]: item for item in project_book(settings)["candidates"]
    }
    from quant_system.research.capital_evidence import current_candidate_quality

    ready = next(row for row in stored_before["candidates"]
                 if row["candidate_id"] == "candidate-activation-ready")
    current = current_candidate_quality(settings, ready, stored_before["candidates"])
    assert current["eligible"] is True

    assert projected["candidate-activation-ready"]["activation_eligibility"] == {
        "eligible": True,
        "reason": "preflight_on_enable",
        "quality_tier": "T2",
        "quality_family_digest": current["family_digest"],
    }
    assert len(projected["candidate-activation-ready"]["activation_eligibility"]
               ["quality_family_digest"]) == 64
    assert projected[READ_ONLY_DSR_CANDIDATE_ID]["status"] == "verified"
    assert projected[READ_ONLY_DSR_CANDIDATE_ID]["activation_eligibility"] == {
        "eligible": False,
        "reason": "new_capital_quality_failed:cost_sensitivity_failed",
    }
    assert load_book(settings) == stored_before


def _write_store_sleeve(
    tmp_path: Path,
    sleeve_id: str,
    *,
    metadata: dict,
    status: str = "running",
) -> None:
    from quant_system.execution.paper_strategy_sleeves import (
        StrategySleeve,
        StrategySleeveMode,
    )

    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    storage.save_sleeve(
        StrategySleeve(
            sleeve_id=sleeve_id,
            strategy_config_id=f"strategy-config-{sleeve_id[-6:]}",
            strategy_config_version=1,
            mode=StrategySleeveMode.ALLOCATED,
            status=status,
            initial_allocated_cash=10_000.0,
            cash=10_000.0,
            metadata=metadata,
        )
    )


_STRONG_RETURNS: dict[int, list[float]] = {}


def _strong_returns(n: int = 240) -> list[float]:
    import random

    if n not in _STRONG_RETURNS:
        rng = random.Random(11)
        _STRONG_RETURNS[n] = [rng.gauss(0.0016, 0.010) for _ in range(n)]
    return _STRONG_RETURNS[n]


def _xnys_return_dates(n: int) -> list[str]:
    values: list[str] = []
    candidate = date(2025, 1, 2)
    while len(values) < n:
        if is_us_market_session(candidate):
            values.append(f"{candidate.isoformat()}T00:00:00+00:00")
        candidate += timedelta(days=1)
    return values


def _write_replay_receipt(
    job_dir: Path,
    returns: list[float],
    *,
    turnover: float | None = None,
    dir_name: str = "replay-fixture",
    return_dates: list[str] | None = None,
) -> None:
    replay_dir = job_dir / "platform-replay" / dir_name
    replay_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "daily_returns": returns,
        "terminal_nav": 1.5,
    }
    if turnover is not None:
        payload["metrics"] = {"turnover": turnover}
    if return_dates is not None:
        payload["return_dates"] = return_dates
    (replay_dir / "receipt.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _admit_replay_candidate(
    settings,
    tmp_path: Path,
    *,
    candidate_id: str,
    returns: list[float],
    return_dates: list[str] | None,
) -> dict:
    from tests.current_capital_fixtures import d34_candidate_kwargs

    job_dir = tmp_path / "_runtime" / "d34" / "jobs" / f"job-{candidate_id}"
    research_dir = job_dir / "research" / f"research-{candidate_id}"
    research_dir.mkdir(parents=True)
    path, _ = _write_fixture_factor(tmp_path)
    factor_source = path.read_text(encoding="utf-8") + f"\n# candidate {candidate_id}\n"
    digest = hashlib.sha256(factor_source.encode("utf-8")).hexdigest()
    factor_copy = research_dir / "candidate_factor.py"
    factor_copy.write_text(factor_source, encoding="utf-8")
    _write_replay_receipt(job_dir, returns, turnover=1.0, return_dates=return_dates)
    original = d34_candidate_kwargs(
        settings, candidate_id=candidate_id, source_path=factor_copy, source_digest=digest,
        factor_id="d34_oracle", universe=["SPY", "QQQ"], daily_returns=returns,
        return_dates=return_dates, turnover_period=1.0,
    )
    return record_verified_from_dual_engine_artifact(
        settings,
        artifact_id=f"artifact-{candidate_id}",
        source_path=Path(original["source_path"]),
        source_digest=digest,
        comparison_digest=original["comparison_digest"],
        universe=["SPY", "QQQ"],
        objective=candidate_id,
        daily_returns=returns,
        turnover_period=1.0,
        return_dates=original["return_dates"],
        evidence_ref=original["evidence_ref"],
    )


def _window_dates(days: int, *, offset: int = 0) -> list[str]:
    values = _xnys_return_dates(days + offset)
    return values[offset : offset + days]


def test_hang_rejects_date_aligned_twin_from_replay_receipts(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    # Both requests must satisfy the current126-session funding floor before
    # this test can reach its intended date-aligned correlation decision.
    returns = _strong_returns(260)
    dates = _window_dates(260)
    original = _admit_replay_candidate(
        settings,
        tmp_path,
        candidate_id="cand-dated-original",
        returns=returns,
        return_dates=dates,
    )
    twin = _admit_replay_candidate(
        settings,
        tmp_path,
        candidate_id="cand-dated-twin",
        returns=[value * 1.001 for value in returns],
        return_dates=dates,
    )
    hang_candidate(settings, candidate_id=original["candidate_id"])

    with pytest.raises(AssistantRemoteError) as exc:
        hang_candidate(settings, candidate_id=twin["candidate_id"])
    assert exc.value.code == "new_capital_quality_failed:concentration_raw_failed,unfunded_tier"


def test_hang_allows_same_sequence_over_a_shifted_window(tmp_path, monkeypatch) -> None:
    """Positional pairing would call this a twin; the calendar says otherwise.

    The twin replays the identical return sequence 40 days later. Position i
    of one lines up with position i of the other (corr ~ 1.0, false reject),
    but on any shared calendar day the two candidates hold unrelated draws.
    """
    settings = _settings(tmp_path, monkeypatch)
    returns = _strong_returns(260)
    first = _admit_replay_candidate(
        settings,
        tmp_path,
        candidate_id="cand-window-a",
        returns=returns,
        return_dates=_window_dates(260),
    )
    second = _admit_replay_candidate(
        settings,
        tmp_path,
        candidate_id="cand-window-b",
        returns=returns,
        return_dates=_window_dates(260, offset=40),
    )
    hang_candidate(settings, candidate_id=first["candidate_id"])

    hung = hang_candidate(settings, candidate_id=second["candidate_id"])

    assert hung["status"] == "hung"
    assert hung["max_hung_correlation"] is not None
    assert hung["max_hung_correlation"] < 0.7


def test_hang_stamps_null_correlation_when_no_hung_peer_is_comparable(
    tmp_path, monkeypatch
) -> None:
    """A hung peer with too little overlap is recorded as null, not -1.0."""
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    # 15 periods of high signal-to-noise: DSR passes, but the series is too
    # short for returns_correlation (n < 20), so no correlation is measurable.
    short_strong = [0.02, 0.005] * 7 + [0.02]
    record_verified_candidate(
        settings,
        candidate_id="candidate-short-peer",
        objective="short but real",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=short_strong,
    )
    _record_current_candidate(
        settings,
        candidate_id="candidate-lonely",
        objective="first comparable",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=_strong_returns(),
        turnover_period=1.0,
    )
    # Short series cannot certify 2× cost; it stays verified, not hung.
    hung = hang_candidate(settings, candidate_id="candidate-lonely")

    assert hung["status"] == "hung"
    assert hung["max_hung_correlation"] is None
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = storage.load_sleeve(hung["sleeve_id"])
    assert sleeve.metadata["max_hung_correlation"] is None


def test_hang_requires_certified_performance(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    _record_current_candidate(
        settings,
        candidate_id="candidate-noperf",
        objective="no performance attached",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=_strong_returns(),
        turnover_period=1.0,
    )
    from quant_system.execution import assistant_remote as remote
    from quant_system.research.capital_evidence import current_candidate_quality

    book = remote.load_book(settings)
    book["candidates"][0]["performance"] = None
    remote.save_book(settings, book)
    diagnostic = current_candidate_quality(settings, book["candidates"][0], book["candidates"])
    assert diagnostic["evidence_reason"] == "candidate_original_performance_mismatch"

    with pytest.raises(AssistantRemoteError) as exc:
        hang_candidate(settings, candidate_id="candidate-noperf")
    assert exc.value.code == "new_capital_quality_failed:quality_evidence_unavailable"


def test_hang_rejects_curve_fit_survivor_of_many_trials(tmp_path, monkeypatch) -> None:
    from quant_system.research.evaluation_service import _hash
    from quant_system.research.trials import ResearchTrial, TrialsLedger

    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    _record_current_candidate(
        settings,
        candidate_id="candidate-curvefit",
        objective="strong on paper after many tries",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=_strong_returns(),
        turnover_period=1.0,
    )
    ledger = TrialsLedger(Path(settings.data.data_dir) / "trials")
    import random as _random

    rng = _random.Random(5)
    for index, extra in enumerate([0.30, -0.10, 0.25, 0.05, -0.20] * 12):
        returns = [rng.gauss(extra / 240, 0.010) for _ in range(240)]
        row = ResearchTrial.record(
                kind="platform_backtest",
                subject=f"probe-{index}",
                universe=["SPY", "QQQ"],
                daily_returns=returns,
                source=f"probe-{index}",
                window_start=_xnys_return_dates(240)[0][:10],
                window_end=_xnys_return_dates(240)[-1][:10],
                metadata={"run_id": f"ARTIFICIAL-probe-{index}"},
            )
        contract = {"schema": "research_family_compatibility/v1",
                    "return_definition": "net_total_return",
                    "benchmark": {"symbol": None, "method": "none"}, "frequency": "daily",
                    "cost_definition": {"model": "qlib_combined_bps", "one_way_bps": 6.0,
                                        "min_cost": 0.0, "cash_interest": 0.0},
                    "market_data_contract": {"provider": "futu", "price_adjustment": "qfq",
                                             "currency": "USD", "bar": "1d"}}
        nav, curve = 10000.0, []
        for day, value in zip(_xnys_return_dates(240), returns, strict=True):
            nav *= 1 + value
            curve.append({"date": day[:10], "equity": nav})
        raw = row.model_dump(mode="json")
        payload = {"schema": "research_family_curve/v1", "run_id": row.metadata["run_id"],
                   "trial_identity": {key: raw[key] for key in
                        ("kind", "subject", "universe_digest", "window_start", "window_end",
                         "n_periods")}, "input_identity": {"kind": "ARTIFICIAL_STATISTIC_ONLY"},
                   "curve": curve, "evaluation_initial_cash": 10000.0,
                   "family_contract": contract}
        original = tmp_path / "artificial-statistic-originals" / f"probe-{index}.json"
        original.parent.mkdir(exist_ok=True)
        original.write_text(json.dumps(payload))
        row = row.model_copy(update={"metadata": {**row.metadata,
            "family_evidence_path": str(original.relative_to(tmp_path)),
            "family_evidence_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            "equity_curve_digest": _hash(curve), "family_contract_digest": _hash(contract)}})
        ledger.append(row)

    with pytest.raises(AssistantRemoteError) as exc:
        hang_candidate(settings, candidate_id="candidate-curvefit")
    assert exc.value.code == "new_capital_quality_failed:dsr_failed,unfunded_tier"


def test_hang_allows_strong_candidate_on_clean_ledger(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    _record_current_candidate(
        settings,
        candidate_id="candidate-strong-dsr",
        objective="genuinely strong",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=_strong_returns(),
        turnover_period=1.0,
    )

    hung = hang_candidate(settings, candidate_id="candidate-strong-dsr")

    assert hung["status"] == "hung"
    assert hung["dsr"]["passed"] is True
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = storage.load_sleeve(hung["sleeve_id"])
    assert sleeve.metadata["dsr_value"] == hung["dsr"]["value"]


def test_hang_rejects_correlated_duplicate_of_hung_factor(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    base = _strong_returns()
    twin = [value * 1.001 + 1e-6 for value in base]  # near-identical factor
    path, digest = _write_fixture_factor(tmp_path)
    _record_current_candidate(
        settings,
        candidate_id="candidate-original",
        objective="first momentum",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=base,
        turnover_period=1.0,
    )
    _record_current_candidate(
        settings,
        candidate_id="candidate-twin",
        objective="same momentum in a new jacket",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=twin,
        turnover_period=1.0,
    )
    hang_candidate(settings, candidate_id="candidate-original")

    with pytest.raises(AssistantRemoteError) as exc:
        hang_candidate(settings, candidate_id="candidate-twin")
    assert exc.value.code == "new_capital_quality_failed:concentration_raw_failed,unfunded_tier"


def test_hang_allows_uncorrelated_factor(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    base = _strong_returns()
    import random as _random

    rng = _random.Random(23)
    shuffled = base[:]
    rng.shuffle(shuffled)  # same distribution, ~zero correlation
    path, digest = _write_fixture_factor(tmp_path)
    _record_current_candidate(
        settings,
        candidate_id="candidate-alpha",
        objective="first",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=base,
        turnover_period=1.0,
    )
    _record_current_candidate(
        settings,
        candidate_id="candidate-beta",
        objective="different signal",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=shuffled,
        turnover_period=1.0,
    )
    hang_candidate(settings, candidate_id="candidate-alpha")
    hung = hang_candidate(settings, candidate_id="candidate-beta")

    assert hung["status"] == "hung"
    assert hung["max_hung_correlation"] < 0.7


def test_concurrent_correlated_hangs_recheck_book_inside_account_lock(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    for candidate_id in ("candidate-concurrent-alpha", "candidate-concurrent-beta"):
        _record_current_candidate(
            settings,
            candidate_id=candidate_id,
            objective="same factor concurrent hang",
            source="d34_artifact",
            source_path=str(path),
            source_digest=digest,
            factor_id="d34_oracle",
            universe=["SPY", "QQQ"],
            comparison_digest="f" * 64,
            daily_returns=_strong_returns(),
            turnover_period=1.0,
        )
    from quant_system.execution.account_storage import PaperAccountStorage

    barrier = threading.Barrier(2)
    original_lock = PaperAccountStorage.mutation_lock

    @contextmanager
    def synchronized_lock(storage, **kwargs):
        barrier.wait(timeout=5)
        with original_lock(storage, **kwargs):
            yield

    monkeypatch.setattr(PaperAccountStorage, "mutation_lock", synchronized_lock)

    def run(candidate_id: str):
        try:
            return ("ok", hang_candidate(settings, candidate_id=candidate_id))
        except AssistantRemoteError as exc:
            return ("error", exc.code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                run,
                ("candidate-concurrent-alpha", "candidate-concurrent-beta"),
            )
        )

    assert sum(status == "ok" for status, _payload in results) == 1
    assert [payload for status, payload in results if status == "error"] == [
        "new_capital_quality_failed:concentration_raw_failed,unfunded_tier"
    ]
    account = PaperAccountStorage(tmp_path / "api_runs").load()
    assert account is not None
    assert sum(entry.kind == "sleeve_cash_allocated" for entry in account.ledger) == 1
    assert len(PaperStrategySleeveStorage(tmp_path / "api_runs").list_sleeves()) == 1


def test_hang_recovery_does_not_launder_non_book_bound_fossil(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id="candidate-preview-fossil",
    )
    receipt = hang_candidate(settings, candidate_id="candidate-preview-fossil")
    book = remote_module.load_book(settings)
    book["candidates"][0]["status"] = "verified"
    book["candidates"][0]["sleeve_id"] = None
    remote_module.save_book(settings, book)
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = sleeve_storage.load_sleeve(receipt["sleeve_id"])
    sleeve.metadata["fossil"] = True
    sleeve.metadata["official_observation"] = False
    sleeve.metadata["fossil_reason"] = "preview_seed"
    sleeve_storage.save_sleeve(sleeve)

    with pytest.raises(AssistantRemoteError) as blocked:
        hang_candidate(settings, candidate_id="candidate-preview-fossil")

    assert blocked.value.code == "existing_hang_lineage_invalid"
    unchanged = sleeve_storage.load_sleeve(receipt["sleeve_id"])
    assert unchanged.metadata["fossil_reason"] == "preview_seed"
    assert unchanged.metadata["official_observation"] is False


def test_existing_hang_recovery_converges_before_mutable_correlation_gate(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import assistant_remote as remote_module

    settings = _settings(tmp_path, monkeypatch)
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id="candidate-recovery-b",
    )
    original_save_book = remote_module.save_book
    calls = 0

    def fail_b_book_once(settings_arg, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated B book failure")
        return original_save_book(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", fail_b_book_once)
    with pytest.raises(AssistantRemoteError) as first:
        hang_candidate(settings, candidate_id="candidate-recovery-b")
    assert first.value.code == "hang_book_persist_failed"
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    b_sleeve_id = sleeve_storage.list_sleeves()[0].sleeve_id

    path, digest = _write_fixture_factor(tmp_path)
    _record_current_candidate(
        settings,
        candidate_id="candidate-later-a",
        objective="later correlated factor",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="a" * 64,
        daily_returns=_strong_returns(),
        turnover_period=1.0,
    )

    with pytest.raises(AssistantRemoteError) as blocked_a:
        hang_candidate(settings, candidate_id="candidate-later-a")
    assert blocked_a.value.code == "hang_recovery_required"

    recovered = hang_candidate(settings, candidate_id="candidate-recovery-b")

    assert recovered["sleeve_id"] == b_sleeve_id
    book = project_book(settings)
    b_candidate = next(
        item for item in book["candidates"] if item["candidate_id"] == "candidate-recovery-b"
    )
    assert b_candidate["status"] == "hung"
    with pytest.raises(AssistantRemoteError) as duplicate_a:
        hang_candidate(settings, candidate_id="candidate-later-a")
    assert duplicate_a.value.code == (
        "new_capital_quality_failed:concentration_raw_failed,unfunded_tier"
    )


def test_hang_rejects_edge_that_dies_at_double_costs(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    import random as _random

    rng = _random.Random(41)
    returns = [rng.gauss(0.0004 / 252, 1e-5) for _ in range(240)]  # tiny daily edge
    path, digest = _write_fixture_factor(tmp_path)
    _record_current_candidate(
        settings,
        candidate_id="candidate-churny",
        objective="high turnover, tiny edge",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=returns,
        turnover_period=30.0,  # 30x per window -> huge annual drag
    )

    with pytest.raises(AssistantRemoteError) as exc:
        hang_candidate(settings, candidate_id="candidate-churny")
    assert exc.value.code == (
        "new_capital_quality_failed:cost_sensitivity_failed,dsr_failed,unfunded_tier"
    )


def test_hang_rejects_when_turnover_is_unmeasured(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path, monkeypatch)
    path, digest = _write_fixture_factor(tmp_path)
    _record_current_candidate(
        settings,
        candidate_id="candidate-unmeasured-cost",
        objective="strong edge, no turnover on record",
        source="d34_artifact",
        source_path=str(path),
        source_digest=digest,
        factor_id="d34_oracle",
        universe=["SPY", "QQQ"],
        comparison_digest="250f39dbae3531ea858543197ec3e204f4ecdca706221a839c219708e4c956c1",
        daily_returns=_strong_returns(),
    )

    with pytest.raises(AssistantRemoteError) as exc:
        hang_candidate(settings, candidate_id="candidate-unmeasured-cost")
    assert exc.value.code == (
        "new_capital_quality_failed:cost_evidence_invalid,cost_sensitivity_failed"
    )


def test_fresh_hang_marks_dsr_and_cost_stamps_as_certified(tmp_path, monkeypatch) -> None:
    from quant_system.execution.assistant_remote import load_book

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = "candidate-stamp-fresh"
    _record_strong_hang_candidate(settings, tmp_path, candidate_id=candidate_id)
    hang_candidate(settings, candidate_id=candidate_id)
    book = load_book(settings)
    candidate = next(item for item in book["candidates"] if item["candidate_id"] == candidate_id)
    assert candidate["dsr"]["recertified_at_hang"] is True
    assert candidate["cost_sensitivity"]["recertified_at_hang"] is True


def test_recovered_hang_reuses_stamps_and_marks_them_not_recertified(tmp_path, monkeypatch) -> None:
    """Owner decision 2026-08-21: already-hung sleeves get no new gates, but a
    recovered hang must label that its DSR/cost stamps were reused, not
    re-certified against current trial history."""
    from quant_system.execution import assistant_remote as remote_module
    from quant_system.execution.assistant_remote import load_book

    settings = _settings(tmp_path, monkeypatch)
    candidate_id = "candidate-stamp-recovered"
    _record_strong_hang_candidate(settings, tmp_path, candidate_id=candidate_id)
    original_save_book = remote_module.save_book
    calls = 0

    def fail_book_once(settings_arg, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated book replace failure")
        return original_save_book(settings_arg, book)

    monkeypatch.setattr(remote_module, "save_book", fail_book_once)
    with pytest.raises(AssistantRemoteError):
        hang_candidate(settings, candidate_id=candidate_id)
    monkeypatch.setattr(remote_module, "save_book", original_save_book)
    recovered = hang_candidate(settings, candidate_id=candidate_id)
    assert recovered["status"] == "hung"
    book = load_book(settings)
    candidate = next(item for item in book["candidates"] if item["candidate_id"] == candidate_id)
    assert candidate["dsr"]["recertified_at_hang"] is False
    # the first hang crashed before the book save, so no cost stamp had ever
    # been persisted — recovery must complete it freshly, labelled as such
    assert candidate["cost_sensitivity"]["recertified_at_hang"] is True


def _write_accepted_preauth_job(
    tmp_path: Path,
    *,
    job_id: str,
    job_key: str | None,
    with_replay: bool = True,
) -> tuple[str, Path]:
    """Accepted dual-engine job fixture with a queue lineage key."""
    path, digest = _write_fixture_factor(tmp_path)
    job_root = tmp_path / "_runtime" / "d34" / "jobs" / job_id
    research_dir = job_root / "research" / "research-fixture"
    research_dir.mkdir(parents=True)
    (research_dir / "candidate_factor.py").write_bytes(path.read_bytes())
    rel = f"jobs/{job_id}/research/research-fixture/candidate_factor.py"
    (job_root / "cycle_receipt.json").write_text(
        json.dumps(
            {
                "contract": "hqa.d34_job_outcome/v1",
                "phase": "candidate_ready",
                "comparison_accepted": True,
                "artifact_id": f"artifact-preauth-{job_id}",
                "candidate_code_digest": digest,
                "comparison_digest": "d" * 64,
                "factor_path": rel,
                "job_id": job_id,
            }
        ),
        encoding="utf-8",
    )
    request_doc: dict[str, object] = {
        "objective": "preauthorized hang fixture",
        "universe": ["SPY", "QQQ"],
        "top_k": 1,
    }
    if job_key:
        request_doc["job_key"] = job_key
    (job_root / "research_request.json").write_text(json.dumps(request_doc), encoding="utf-8")
    if with_replay:
        _write_replay_receipt(job_root, _strong_returns(), turnover=0.2)
    return digest, job_root


def _bind_chat_research_evidence(
    *,
    job_root: Path,
    request: dict[str, object],
    input_document: dict[str, object],
    daily_returns: list[float] | None = None,
    turnover_period: float = 0.2,
):
    cycle_path = job_root / "cycle_receipt.json"
    cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
    research_request_path = job_root / "research_request.json"
    research_request = json.loads(research_request_path.read_text(encoding="utf-8"))
    factor_path = next((job_root / "research").rglob("candidate_factor.py"))
    candidate_digest = hashlib.sha256(factor_path.read_bytes()).hexdigest()
    daily_returns = daily_returns if daily_returns is not None else _strong_returns()
    return_dates = _xnys_return_dates(len(daily_returns))
    run_id = "attempt-chat-fixture-12345678"
    research_request.update(
        {
            "contract": "hqa.d34_research_request/v2",
            "job_id": request["job_id"],
            "run_id": run_id,
            "resource_envelope_id": input_document["resource_envelope_id"],
            "resource_policy_digest": input_document["resource_policy_digest"],
            "job_key": request["job_key"],
            "objective": request["objective"],
            "universe": request["universe"],
            "calendar": return_dates,
        }
    )
    research_request_path.write_text(json.dumps(research_request), encoding="utf-8")
    from types import SimpleNamespace

    from tests.current_capital_fixtures import prepare_bound_chat_specimen

    specimen = prepare_bound_chat_specimen(
        SimpleNamespace(data=SimpleNamespace(data_dir=job_root.parents[3])),
        job_root=job_root, request_doc=research_request, factor_path=factor_path,
        daily_returns=daily_returns, return_dates=return_dates, turnover_period=turnover_period,
    )
    research_request = specimen["request"]
    qlib_engine, platform_engine = specimen["qlib_engine"], specimen["platform_engine"]
    qlib_raw_path, platform_raw_path = specimen["qlib_raw_path"], specimen["platform_raw_path"]
    qlib_path, platform_path = specimen["qlib_bound_path"], specimen["platform_bound_path"]
    comparison = specimen["comparison"]
    cycle["comparison_digest"] = comparison["comparison_digest"]
    cycle_path.write_text(json.dumps(cycle))
    qlib_receipt_digest = qlib_engine["receipt_digest"]
    platform_receipt_digest = platform_engine["receipt_digest"]
    comparison_digest = str(cycle["comparison_digest"])
    outcome_document = {
        "contract": "hqa.d34_job_outcome/v1",
        "candidate_code_digest": candidate_digest,
        "qlib_receipt_digest": qlib_receipt_digest,
        "platform_receipt_digest": platform_receipt_digest,
        "comparison_digest": comparison_digest,
        "comparison_accepted": True,
    }
    recovery = {
        "contract": "hqa.d34_terminal_recovery/v1",
        "job_id": request["job_id"],
        "lease_id": "lease-chat-fixture-12345678",
        "run_id": run_id,
        "resource_envelope_id": input_document["resource_envelope_id"],
        "resource_policy_digest": input_document["resource_policy_digest"],
        "workspace_id": "default",
        "universe": request["universe"],
        "factor_id": specimen["candidate_kwargs"]["factor_id"],
        "factor_path": (
            f"/workspace/d34/{factor_path.relative_to(job_root.parent.parent).as_posix()}"
        ),
        "candidate_code_digest": candidate_digest,
        "qlib_config_digest": specimen["qlib_config_digest"],
        "rdagent_commit": "3" * 40,
        "qlib_commit": "4" * 40,
        "docker_image_digest": "sha256:" + "9" * 64,
        "qlib_receipt": qlib_engine,
        "platform_receipt": platform_engine,
        "qlib_raw_receipt_path": (
            f"/workspace/d34/{qlib_raw_path.relative_to(job_root.parent.parent).as_posix()}"
        ),
        "platform_raw_receipt_path": (
            f"/workspace/d34/{platform_raw_path.relative_to(job_root.parent.parent).as_posix()}"
        ),
        "comparison": {
            "accepted": True,
            "comparison_digest": comparison_digest,
            "daily_return_correlation": comparison["daily_return_correlation"],
            "terminal_nav_difference_bps": comparison["terminal_nav_difference_bps"],
            "max_symbol_weight_difference_bps": comparison["max_symbol_weight_difference_bps"],
        },
        "outcome_document": outcome_document,
        "budget_spent_usd": "1.250000",
        "provider_receipt_digest": "7" * 64,
    }
    recovery_digest = digest_document(recovery)
    (job_root / "terminal_recovery.json").write_text(
        json.dumps({**recovery, "recovery_digest": recovery_digest}),
        encoding="utf-8",
    )
    input_digest = digest_document(input_document)
    input_receipt = {
        "contract": "hqa.d34_job_input_receipt/v1",
        "job_id": request["job_id"],
        "input_digest": input_digest,
        "input_document": input_document,
    }
    (job_root / "job_input.json").write_text(
        json.dumps({**input_receipt, "receipt_digest": digest_document(input_receipt)}),
        encoding="utf-8",
    )
    manifest = {
        "contract": "hqa.d34_research_evidence/v1",
        "job_id": request["job_id"],
        "run_id": run_id,
        "job_key": request["job_key"],
        "operation_id": request["operation_id"],
        "material_digest": request["material_digest"],
        "job_input_digest": input_digest,
        "research_request_digest": digest_document(research_request),
        "cycle_receipt_digest": digest_document(cycle),
        "terminal_recovery_digest": recovery_digest,
        "artifact_id": cycle["artifact_id"],
        "artifact_version": 1,
        "candidate_code_path": factor_path.relative_to(job_root).as_posix(),
        "candidate_code_digest": candidate_digest,
        "qlib_receipt_path": qlib_path.relative_to(job_root).as_posix(),
        "qlib_receipt_file_digest": hashlib.sha256(qlib_path.read_bytes()).hexdigest(),
        "qlib_receipt_digest": qlib_receipt_digest,
        "qlib_raw_receipt_path": qlib_raw_path.relative_to(job_root).as_posix(),
        "qlib_raw_receipt_file_digest": hashlib.sha256(qlib_raw_path.read_bytes()).hexdigest(),
        "platform_receipt_path": platform_path.relative_to(job_root).as_posix(),
        "platform_receipt_file_digest": hashlib.sha256(platform_path.read_bytes()).hexdigest(),
        "platform_receipt_digest": platform_receipt_digest,
        "platform_raw_receipt_path": platform_raw_path.relative_to(job_root).as_posix(),
        "platform_raw_receipt_file_digest": hashlib.sha256(
            platform_raw_path.read_bytes()
        ).hexdigest(),
        "comparison_digest": comparison_digest,
        "comparison": {
            "accepted": True,
            "daily_return_correlation": comparison["daily_return_correlation"],
            "terminal_nav_difference_bps": comparison["terminal_nav_difference_bps"],
            "max_symbol_weight_difference_bps": comparison["max_symbol_weight_difference_bps"],
        },
        "cost_model": {"commission_bps": 1.0, "slippage_bps": 5.0},
    }
    manifest_digest = digest_document(manifest)
    evidence_document = {**manifest, "manifest_digest": manifest_digest}
    (job_root / "evidence_manifest.json").write_text(
        json.dumps(evidence_document),
        encoding="utf-8",
    )
    terminal_bundle = {
        "contract": "hqa.d34_terminal_bundle/v1",
        "job_id": request["job_id"],
        "cycle_receipt": cycle,
        "evidence_manifest": evidence_document,
    }
    (job_root / "terminal_bundle.json").write_text(
        json.dumps({**terminal_bundle, "bundle_digest": digest_document(terminal_bundle)}),
        encoding="utf-8",
    )

    class Registry:
        def get_artifact_for_job(
            self,
            *,
            workspace_id: str,
            job_id: str,
            artifact_id: str,
        ):
            assert (workspace_id, job_id, artifact_id) == (
                "default",
                request["job_id"],
                cycle["artifact_id"],
            )
            return {
                "artifact_id": artifact_id,
                "version": 1,
                "status": "qualified",
                "qualification_scope": "paper_only",
                "resource_envelope_id": input_document["resource_envelope_id"],
                "candidate_code_digest": candidate_digest,
                "qlib_receipt_digest": qlib_receipt_digest,
                "platform_receipt_digest": platform_receipt_digest,
                "comparison_digest": comparison_digest,
                "comparison": {"accepted": True},
            }

    return Registry()

def _write_chat_failure_evidence(
    *,
    job_root: Path,
    request: dict[str, object],
    input_document: dict[str, object],
) -> str:
    job_root.mkdir(parents=True, exist_ok=True)
    cycle = {
        "phase": "failed",
        "failed_phase": "research",
        "job_id": request["job_id"],
        "code": "research_failed",
        "error": "Research failed without a candidate.",
    }
    (job_root / "cycle_receipt.json").write_text(json.dumps(cycle), encoding="utf-8")
    input_digest = digest_document(input_document)
    input_receipt = {
        "contract": "hqa.d34_job_input_receipt/v1",
        "job_id": request["job_id"],
        "input_digest": input_digest,
        "input_document": input_document,
    }
    (job_root / "job_input.json").write_text(
        json.dumps({**input_receipt, "receipt_digest": digest_document(input_receipt)}),
        encoding="utf-8",
    )
    manifest = {
        "contract": "hqa.d34_research_evidence/v1",
        "job_id": request["job_id"],
        "job_key": request["job_key"],
        "operation_id": request["operation_id"],
        "material_digest": request["material_digest"],
        "job_input_digest": input_digest,
        "cycle_receipt_digest": digest_document(cycle),
        "terminal_status": "failed",
        "failed_phase": "research",
        "failure_code": "research_failed",
        "preflight_receipt_digest": "9" * 64,
    }
    manifest_digest = digest_document(manifest)
    evidence_document = {**manifest, "manifest_digest": manifest_digest}
    (job_root / "evidence_manifest.json").write_text(
        json.dumps(evidence_document),
        encoding="utf-8",
    )
    terminal_bundle = {
        "contract": "hqa.d34_terminal_bundle/v1",
        "job_id": request["job_id"],
        "cycle_receipt": cycle,
        "evidence_manifest": evidence_document,
    }
    (job_root / "terminal_bundle.json").write_text(
        json.dumps({**terminal_bundle, "bundle_digest": digest_document(terminal_bundle)}),
        encoding="utf-8",
    )
    return manifest_digest


def test_failed_chat_research_projects_content_addressed_evidence_without_candidate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    job_id = "job-chat-failed-evidence"
    material = {
        "note": "Research the supplied twenty-day reversal formula",
        "formula": "Ref($close, 20) / $close - 1",
        "universe": ["SPY", "QQQ"],
    }
    material_digest = digest_document(material)
    operation_id = _research_operation_id(
        "platform-session-failed",
        "hermes-session-failed",
        material_digest,
    )
    commands: list[object] = []

    class Jobs:
        def enqueue(self, command):
            commands.append(command)
            return {"job_id": job_id, "job_key": command.job_key}

    intake_research_operation(
        settings,
        jobs=Jobs(),
        operation_id=operation_id,
        material_digest=material_digest,
        command_id="command-failed",
        platform_session_id="platform-session-failed",
        hermes_session_id="hermes-session-failed",
        hermes_run_id="hermes-run-failed",
        **material,
    )
    request = load_book(settings)["requests"][0]
    manifest_digest = _write_chat_failure_evidence(
        job_root=tmp_path / "_runtime" / "d34" / "jobs" / job_id,
        request=request,
        input_document=commands[0].input_document,
    )

    projected = project_terminal_research_results(settings)
    result = project_research_request(settings, operation_id=operation_id)

    assert projected["requests_projected"] == 1
    assert result is not None
    assert result["outcome"] == "outcome_unknown"
    assert "candidate_id" not in result
    assert result["evidence"]["manifest_digest"] == manifest_digest
    assert result["evidence"]["failed_phase"] == "research"
    assert project_book(settings)["candidates"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        "factor_bytes",
        "research_request_job",
        "engine_receipt_inner_digest",
        "registry_job",
    ],
)
def test_chat_projector_rejects_swapped_or_tampered_job_evidence(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    settings = _settings(tmp_path, monkeypatch)
    job_id = "job-evidence-tamper"
    material = {
        "note": "Research the supplied twenty-day reversal formula",
        "formula": "Ref($close, 20) / $close - 1",
        "universe": ["SPY", "QQQ"],
    }
    material_digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    operation_id = _research_operation_id(
        "platform-session-tamper",
        "hermes-session-tamper",
        material_digest,
    )
    commands: list[object] = []

    class Jobs:
        def enqueue(self, command):
            commands.append(command)
            return {"job_id": job_id, "job_key": command.job_key}

    queued = intake_research_operation(
        settings,
        jobs=Jobs(),
        operation_id=operation_id,
        material_digest=material_digest,
        command_id="command-tamper",
        platform_session_id="platform-session-tamper",
        hermes_session_id="hermes-session-tamper",
        hermes_run_id="hermes-run-tamper",
        **material,
    )
    _digest_value, job_root = _write_accepted_preauth_job(
        tmp_path,
        job_id=job_id,
        job_key=queued["job_key"],
    )
    request_document = json.loads((job_root / "research_request.json").read_text(encoding="utf-8"))
    request_document.update(
        {
            "job_id": job_id,
            "objective": load_book(settings)["requests"][0]["objective"],
            "universe": ["SPY", "QQQ"],
        }
    )
    (job_root / "research_request.json").write_text(json.dumps(request_document), encoding="utf-8")
    registry = _bind_chat_research_evidence(
        job_root=job_root,
        request=load_book(settings)["requests"][0],
        input_document=commands[0].input_document,
    )

    if mutation == "factor_bytes":
        next((job_root / "research").rglob("candidate_factor.py")).write_text(
            "tampered = True\n", encoding="utf-8"
        )
    elif mutation == "research_request_job":
        request_document["job_id"] = "job-other"
        (job_root / "research_request.json").write_text(
            json.dumps(request_document), encoding="utf-8"
        )
    elif mutation == "engine_receipt_inner_digest":
        manifest = json.loads((job_root / "evidence_manifest.json").read_text())
        platform_path = job_root / manifest["platform_receipt_path"]
        platform_document = json.loads(platform_path.read_text(encoding="utf-8"))
        platform_document["engine_receipt"]["daily_returns"][0] = 0.99
        unsigned_platform = dict(platform_document)
        unsigned_platform.pop("receipt_digest")
        platform_document["receipt_digest"] = digest_document(unsigned_platform)
        platform_path.write_text(json.dumps(platform_document), encoding="utf-8")
        recovery_path = job_root / "terminal_recovery.json"
        recovery_document = json.loads(recovery_path.read_text(encoding="utf-8"))
        recovery_document["platform_receipt"]["daily_returns"][0] = 0.99
        unsigned_recovery = dict(recovery_document)
        unsigned_recovery.pop("recovery_digest")
        recovery_document["recovery_digest"] = digest_document(unsigned_recovery)
        recovery_path.write_text(json.dumps(recovery_document), encoding="utf-8")
        manifest_path = job_root / "evidence_manifest.json"
        manifest_document = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_document["platform_receipt_file_digest"] = hashlib.sha256(
            platform_path.read_bytes()
        ).hexdigest()
        manifest_document["terminal_recovery_digest"] = recovery_document["recovery_digest"]
        unsigned_manifest = dict(manifest_document)
        unsigned_manifest.pop("manifest_digest")
        manifest_document["manifest_digest"] = digest_document(unsigned_manifest)
        manifest_path.write_text(json.dumps(manifest_document), encoding="utf-8")
        bundle_path = job_root / "terminal_bundle.json"
        bundle_document = json.loads(bundle_path.read_text(encoding="utf-8"))
        bundle_document["evidence_manifest"] = manifest_document
        unsigned_bundle = dict(bundle_document)
        unsigned_bundle.pop("bundle_digest")
        bundle_document["bundle_digest"] = digest_document(unsigned_bundle)
        bundle_path.write_text(json.dumps(bundle_document), encoding="utf-8")
    else:
        registry = type(
            "WrongJobRegistry",
            (),
            {"get_artifact_for_job": lambda *_args, **_kwargs: None},
        )()

    projected = reconcile_research_result(
        settings,
        job_id=job_id,
        registry=registry,
    )

    assert projected is not None
    assert projected["outcome"] == "outcome_unknown"
    assert project_book(settings)["candidates"] == []


def test_cli_research_and_request_use_stable_operation_projection(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    from quant_system import assistant_remote_cli

    settings = _settings(tmp_path, monkeypatch)
    enqueued: list[object] = []

    class Jobs:
        def enqueue(self, command):
            enqueued.append(command)
            return {"job_id": "job-cli-chat", "job_key": command.job_key}

    material = {
        "note": "Research the supplied twenty-day reversal formula",
        "formula": "Ref($close, 20) / $close - 1",
        "universe": ["SPY", "QQQ"],
    }
    material_digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    operation_id = _research_operation_id(
        "platform-session-cli-chat", "hermes-session-cli-chat", material_digest
    )
    monkeypatch.setattr(assistant_remote_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(assistant_remote_cli, "PostgresJobAuthority", lambda _settings: Jobs())

    monkeypatch.setattr(
        assistant_remote_cli.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "operation_id": operation_id,
                    "material_digest": material_digest,
                    "command_id": "command-cli-chat",
                    "platform_session_id": "platform-session-cli-chat",
                    "hermes_session_id": "hermes-session-cli-chat",
                    "hermes_run_id": "hermes-run-cli-chat",
                    **material,
                }
            )
        ),
    )
    assert assistant_remote_cli.main(["research"]) == 0
    raw_research = capsys.readouterr().out
    research = json.loads(raw_research)
    assert research["status"] == "queued"
    assert research["operation_id"] == operation_id
    assert len(enqueued) == 1
    assert material["note"] not in raw_research
    assert material["formula"] not in raw_research

    assert assistant_remote_cli.main(["request", "--operation-id", operation_id]) == 0
    projection = json.loads(capsys.readouterr().out)
    assert projection == research
    assert len(enqueued) == 1


def test_cli_research_stdin_rejects_duplicate_nonfinite_and_extra_without_echo(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    from quant_system import assistant_remote_cli

    settings = _settings(tmp_path, monkeypatch)
    commands: list[object] = []

    class Jobs:
        def enqueue(self, command):
            commands.append(command)
            return {"job_id": "job-forbidden", "job_key": command.job_key}

    note = "Private research body must not be echoed"
    formula = "Ref($close, 20) / $close - 1"
    payload = {
        "operation_id": "a" * 64,
        "material_digest": "b" * 64,
        "command_id": "command-private",
        "platform_session_id": "platform-private",
        "hermes_session_id": "hermes-private",
        "hermes_run_id": "run-private",
        "note": note,
        "formula": formula,
        "universe": ["SPY", "QQQ"],
    }
    valid = json.dumps(payload, separators=(",", ":"))
    invalid = [
        (
            valid[:-1] + ',"operation_id":"' + "c" * 64 + '"}',
            "research_input_duplicate_key",
        ),
        (
            valid.replace('"material_digest":"' + "b" * 64 + '"', '"material_digest":NaN'),
            "research_input_nonfinite",
        ),
        (
            json.dumps({**payload, "unexpected": True}),
            "research_input_fields_invalid",
        ),
    ]
    monkeypatch.setattr(assistant_remote_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(assistant_remote_cli, "PostgresJobAuthority", lambda _settings: Jobs())
    for raw, code in invalid:
        monkeypatch.setattr(assistant_remote_cli.sys, "stdin", io.StringIO(raw))
        assert assistant_remote_cli.main(["research"]) == 2
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"ok": False, "code": code}
        assert captured.err == ""
        assert note not in captured.out
        assert formula not in captured.out
    assert commands == []
