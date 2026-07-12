from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from quant_system.api.schemas.paper import PaperAccountSnapshotResponse
from quant_system.api.server import create_app
from quant_system.cli import app
from quant_system.config.settings import PaperAccountSettings, Settings, reload_settings
from quant_system.execution.account import AccountPosition, PaperAccount
from quant_system.execution.account_dual_write_repository import (
    DualWritePaperAccountRepository,
)
from quant_system.execution.account_snapshot import PaperAccountSnapshotReader
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.price_source import PricedQuote, PriceUnavailableError

runner = CliRunner()


def _file_tree_snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    return {
        str(path.relative_to(root)): (
            ("file", path.read_bytes(), path.stat().st_mtime_ns)
            if path.is_file()
            else ("dir", path.stat().st_mtime_ns)
        )
        for path in sorted(root.rglob("*"))
    }


def test_account_show_json_missing_is_snapshot_schema_and_does_not_write(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()

    def unexpected_price_lookup(*_args, **_kwargs):
        raise AssertionError("missing account must not request prices")

    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_price",
        unexpected_price_lookup,
    )
    before = _file_tree_snapshot(tmp_path / "api_runs")

    result = runner.invoke(
        app,
        [
            "paper",
            "account-show",
            "--account",
            "probe_missing",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "account": None,
        "account_exists": False,
        "account_id": "probe_missing",
    }
    assert _file_tree_snapshot(tmp_path / "api_runs") == before


def test_account_show_json_matches_snapshot_api_business_view_without_writes(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    storage = PaperAccountStorage(tmp_path / "api_runs")
    account = PaperAccount.open_new()
    account.cash = 999_000.0
    account.positions["AAPL"] = AccountPosition(
        symbol="AAPL",
        quantity=10.0,
        avg_cost=100.0,
        source_quantity={"manual": 10.0},
    )
    storage.save(
        account,
        prices={"AAPL": 100.0},
        price_metadata={"AAPL": {"kind": "last_close", "as_of": "2026-07-09T20:00:00+00:00"}},
    )

    def fixed_price(*_args, **_kwargs) -> PricedQuote:
        futu_logger = logging.getLogger("FTConsoleLog")
        handler = logging.StreamHandler(sys.stdout)
        futu_logger.addHandler(handler)
        try:
            futu_logger.warning("provider stdout noise")
        finally:
            futu_logger.removeHandler(handler)
        return PricedQuote(
            symbol="AAPL",
            price=120.0,
            price_kind="futu_snapshot",
            as_of="2026-07-10T14:30:00+00:00",
            source="test",
        )

    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_price",
        fixed_price,
    )
    before = _file_tree_snapshot(tmp_path / "api_runs")

    api_response = TestClient(create_app(output_dir=tmp_path)).get("/api/paper/account/snapshot")
    cli_result = runner.invoke(
        app,
        ["paper", "account-show", "--format", "json"],
    )

    assert api_response.status_code == 200
    assert cli_result.exit_code == 0, cli_result.output
    api_payload = api_response.json()
    cli_payload = json.loads(cli_result.output)
    PaperAccountSnapshotResponse.model_validate(cli_payload)
    assert cli_payload["account_id"] == api_payload["account_id"] == "default"
    assert cli_payload["account_exists"] is api_payload["account_exists"] is True
    cli_account = cli_payload["account"]
    api_account = api_payload["account"]
    assert cli_account["cash"] == api_account["cash"] == pytest.approx(999_000.0)
    assert cli_account["equity"] == api_account["equity"] == pytest.approx(1_000_200.0)
    assert cli_account["storage_mode"] == api_account["storage_mode"] == "file"
    assert cli_account["stale"] is api_account["stale"] is False
    assert cli_account["warnings"] == api_account["warnings"] == []
    assert cli_account["reconciliation"]["status"] == "not_applicable"
    assert api_account["reconciliation"]["status"] == "not_applicable"
    assert cli_account["positions"] == api_account["positions"]
    assert cli_account["positions"] == [
        {
            "avg_cost": 100.0,
            "last_price": 120.0,
            "market_value": 1_200.0,
            "price_as_of": "2026-07-10T14:30:00+00:00",
            "price_kind": "futu_snapshot",
            "quantity": 10.0,
            "source_breakdown": {"manual": 1.0},
            "symbol": "AAPL",
            "unrealized_pnl": 200.0,
            "weight": pytest.approx(0.0011997600479904018),
        }
    ]
    assert _file_tree_snapshot(tmp_path / "api_runs") == before


def test_snapshot_price_failure_uses_explicit_cost_basis_fallback_without_writes(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    storage = PaperAccountStorage(tmp_path / "api_runs")
    account = PaperAccount.open_new()
    account.cash = 999_000.0
    account.positions["AAPL"] = AccountPosition(
        symbol="AAPL",
        quantity=10.0,
        avg_cost=100.0,
        source_quantity={"manual": 10.0},
    )
    storage.save(account, prices={"AAPL": 100.0})

    def unavailable_price(*_args, **_kwargs):
        raise PriceUnavailableError("no current price")

    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_price",
        unavailable_price,
    )
    before = _file_tree_snapshot(tmp_path / "api_runs")

    api_response = TestClient(create_app(output_dir=tmp_path)).get("/api/paper/account/snapshot")
    cli_result = runner.invoke(app, ["paper", "account-show", "--format", "json"])
    text_result = runner.invoke(app, ["paper", "account-show"])

    assert api_response.status_code == 200
    assert cli_result.exit_code == 0, cli_result.output
    for payload in (api_response.json(), json.loads(cli_result.output)):
        account_payload = payload["account"]
        assert account_payload["equity"] == pytest.approx(1_000_000.0)
        assert account_payload["price_source"]["kind"] == "avg_cost_fallback"
        assert account_payload["positions"][0]["last_price"] == pytest.approx(100.0)
        assert account_payload["positions"][0]["price_kind"] == "avg_cost_fallback"
        assert "paper_account_price_unavailable" in account_payload["warnings"]
    assert text_result.exit_code == 0
    assert "account=default cash=999000.00" in text_result.output
    assert "warning=paper_account_price_unavailable" in text_result.output
    assert _file_tree_snapshot(tmp_path / "api_runs") == before


def test_snapshot_preserves_mixed_quote_provenance_and_naive_provider_timestamp(
    tmp_path,
) -> None:
    storage = PaperAccountStorage(tmp_path)
    account = PaperAccount.open_new()
    account.cash = 999_700.0
    account.positions["AAPL"] = AccountPosition(
        symbol="AAPL",
        quantity=1.0,
        avg_cost=100.0,
        source_quantity={"manual": 1.0},
    )
    account.positions["MSFT"] = AccountPosition(
        symbol="MSFT",
        quantity=2.0,
        avg_cost=100.0,
        source_quantity={"manual": 2.0},
    )
    storage.save(account, prices={"AAPL": 100.0, "MSFT": 100.0})

    class MixedPriceSource:
        def get_price(self, symbol):
            if symbol == "MSFT":
                raise PriceUnavailableError(symbol)
            return PricedQuote(
                symbol=symbol,
                price=120.0,
                price_kind="futu_snapshot",
                as_of="2026-07-10 11:30:00",
                source="test",
            )

    before = _file_tree_snapshot(storage.account_dir)

    snapshot = PaperAccountSnapshotReader(
        repository=storage,
        settings=Settings(),
        price_source=MixedPriceSource(),
    ).read()

    assert snapshot.account is not None
    assert snapshot.account["price_source"] == {"kind": "mixed", "as_of": None}
    positions = {row["symbol"]: row for row in snapshot.account["positions"]}
    assert positions["AAPL"]["price_kind"] == "futu_snapshot"
    assert positions["AAPL"]["price_as_of"] == "2026-07-10 11:30:00"
    assert positions["MSFT"]["price_kind"] == "avg_cost_fallback"
    assert "paper_account_price_unavailable" in snapshot.account["warnings"]
    assert _file_tree_snapshot(storage.account_dir) == before


def test_snapshot_uses_valid_backup_and_surfaces_warning_without_repair(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    storage = PaperAccountStorage(tmp_path / "api_runs")
    account = PaperAccount.open_new(initial_cash=123_456.0)
    storage.save(account)
    storage.account_backup_path.write_bytes(storage.account_path.read_bytes())
    storage.account_path.write_text("{broken-primary", encoding="utf-8")
    before = _file_tree_snapshot(storage.account_dir)

    api_response = TestClient(create_app(output_dir=tmp_path)).get("/api/paper/account/snapshot")
    cli_result = runner.invoke(app, ["paper", "account-show", "--format", "json"])

    assert api_response.status_code == 200
    assert cli_result.exit_code == 0, cli_result.output
    for payload in (api_response.json(), json.loads(cli_result.output)):
        assert payload["account_exists"] is True
        assert payload["account"]["cash"] == pytest.approx(123_456.0)
        assert "paper_account_primary_corrupt_using_backup" in payload["account"]["warnings"]
    assert _file_tree_snapshot(storage.account_dir) == before
    assert storage.account_path.read_text(encoding="utf-8") == "{broken-primary"
    assert list(storage.account_dir.glob("account.corrupt-*.json")) == []


def test_snapshot_rejects_corrupt_primary_and_backup_without_reclassifying_missing(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    storage = PaperAccountStorage(tmp_path / "api_runs")
    storage.account_dir.mkdir(parents=True)
    storage.account_path.write_text("{broken-primary", encoding="utf-8")
    storage.account_backup_path.write_text("{broken-backup", encoding="utf-8")
    before = _file_tree_snapshot(storage.account_dir)

    api_response = TestClient(create_app(output_dir=tmp_path)).get("/api/paper/account/snapshot")
    cli_result = runner.invoke(app, ["paper", "account-show", "--format", "json"])
    text_result = runner.invoke(app, ["paper", "account-show"])

    assert api_response.status_code == 503
    assert api_response.json()["detail"]["code"] == "paper_account_storage_corrupt"
    assert cli_result.exit_code == 1
    assert json.loads(cli_result.output)["error"]["code"] == ("paper_account_storage_corrupt")
    assert text_result.exit_code == 1
    assert "paper_account_storage_corrupt" in text_result.output
    assert _file_tree_snapshot(storage.account_dir) == before


def test_mirror_snapshot_propagates_file_backup_warning_without_writes(tmp_path) -> None:
    file_repository = PaperAccountStorage(tmp_path, account_id="mirror-account")
    account = PaperAccount.open_new(
        account_id="mirror-account",
        initial_cash=222_000.0,
    )
    file_repository.save(account)
    file_repository.account_backup_path.write_bytes(file_repository.account_path.read_bytes())
    file_repository.account_path.write_text("{broken-primary", encoding="utf-8")

    class InSyncPostgresRepository:
        def reconciliation(self, *, expected_account):
            assert expected_account is not None
            return {
                "status": "in_sync",
                "account_id": "mirror-account",
                "source": "file",
                "target": "postgres",
                "checked_at": "2026-07-10T00:00:00+00:00",
                "expected_summary": {},
                "actual_summary": {},
                "differences": [],
            }

    repository = DualWritePaperAccountRepository(
        file_repo=file_repository,
        postgres_repo=InSyncPostgresRepository(),
    )
    before = _file_tree_snapshot(file_repository.account_dir)

    snapshot = PaperAccountSnapshotReader(
        repository=repository,
        settings=Settings(
            paper_account=PaperAccountSettings(db_mode="mirror"),
        ),
    ).read()

    assert snapshot.account_exists is True
    assert snapshot.account is not None
    assert snapshot.account["storage_mode"] == "mirror"
    assert snapshot.account["reconciliation"]["status"] == "in_sync"
    assert "paper_account_primary_corrupt_using_backup" in snapshot.account["warnings"]
    assert _file_tree_snapshot(file_repository.account_dir) == before


def test_mirror_snapshot_database_failure_returns_file_account_with_stale_evidence(
    tmp_path,
) -> None:
    file_repository = PaperAccountStorage(tmp_path, account_id="mirror-account")
    file_repository.save(
        PaperAccount.open_new(
            account_id="mirror-account",
            initial_cash=333_000.0,
        )
    )

    class UnavailablePostgresRepository:
        def reconciliation(self, *, expected_account):
            assert expected_account is not None
            raise RuntimeError("database down")

    repository = DualWritePaperAccountRepository(
        file_repo=file_repository,
        postgres_repo=UnavailablePostgresRepository(),
    )
    before = _file_tree_snapshot(file_repository.account_dir)

    snapshot = PaperAccountSnapshotReader(
        repository=repository,
        settings=Settings(
            paper_account=PaperAccountSettings(db_mode="mirror"),
        ),
    ).read()

    assert snapshot.account_exists is True
    assert snapshot.account is not None
    assert snapshot.account["cash"] == pytest.approx(333_000.0)
    assert snapshot.account["stale"] is True
    assert snapshot.account["reconciliation"]["status"] == "unavailable"
    assert "paper_account_reconciliation_unavailable" in snapshot.account["warnings"]
    assert _file_tree_snapshot(file_repository.account_dir) == before


def test_canonical_snapshot_missing_requires_explicit_bootstrap_in_api_and_cli(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import account_repository_factory

    class MissingCanonicalRepository:
        def __init__(self, *, settings, account_id, source) -> None:
            self.settings = settings
            self.account_id = account_id
            self.source = source

        def load(self):
            return None

    monkeypatch.setattr(
        account_repository_factory,
        "PostgresPaperAccountRepository",
        MissingCanonicalRepository,
    )
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "canonical")
    reload_settings()
    settings = Settings(
        paper_account=PaperAccountSettings(db_mode="canonical"),
    )
    before = _file_tree_snapshot(tmp_path / "api_runs")

    api_response = TestClient(create_app(settings=settings, output_dir=tmp_path)).get(
        "/api/paper/account/snapshot"
    )
    cli_result = runner.invoke(app, ["paper", "account-show", "--format", "json"])
    text_result = runner.invoke(app, ["paper", "account-show"])

    assert api_response.status_code == 409
    assert api_response.json()["detail"]["code"] == "paper_account_bootstrap_required"
    assert cli_result.exit_code == 1
    assert json.loads(cli_result.output)["error"]["code"] == ("paper_account_bootstrap_required")
    assert text_result.exit_code == 1
    assert "paper_account_bootstrap_required" in text_result.output
    assert _file_tree_snapshot(tmp_path / "api_runs") == before


def test_canonical_snapshot_database_failure_is_stable_and_does_not_fall_back(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import account_repository_factory

    private_driver_error = "psycopg failed with password=do-not-leak"

    class UnavailableCanonicalRepository:
        def __init__(self, *, settings, account_id, source) -> None:
            self.settings = settings
            self.account_id = account_id
            self.source = source

        def load(self):
            raise RuntimeError(private_driver_error)

    monkeypatch.setattr(
        account_repository_factory,
        "PostgresPaperAccountRepository",
        UnavailableCanonicalRepository,
    )
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "canonical")
    reload_settings()
    settings = Settings(
        paper_account=PaperAccountSettings(db_mode="canonical"),
    )
    before = _file_tree_snapshot(tmp_path / "api_runs")

    api_response = TestClient(create_app(settings=settings, output_dir=tmp_path)).get(
        "/api/paper/account/snapshot"
    )
    cli_result = runner.invoke(app, ["paper", "account-show", "--format", "json"])
    text_result = runner.invoke(app, ["paper", "account-show"])

    assert api_response.status_code == 503
    assert api_response.json()["detail"]["code"] == ("paper_account_database_unavailable")
    assert cli_result.exit_code == 1
    cli_payload = json.loads(cli_result.output)
    assert cli_payload["error"]["code"] == "paper_account_database_unavailable"
    assert private_driver_error not in api_response.text
    assert private_driver_error not in cli_result.output
    assert text_result.exit_code == 1
    assert "paper_account_database_unavailable" in text_result.output
    assert private_driver_error not in text_result.output
    assert _file_tree_snapshot(tmp_path / "api_runs") == before


def test_canonical_snapshot_corrupt_row_is_stable_in_api_and_cli(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import account_repository_factory
    from quant_system.execution.account_repository import PaperAccountStorageCorrupt

    class CorruptCanonicalRepository:
        def __init__(self, *, settings, account_id, source) -> None:
            self.settings = settings
            self.account_id = account_id
            self.source = source

        def load(self):
            raise PaperAccountStorageCorrupt(self.account_id)

    monkeypatch.setattr(
        account_repository_factory,
        "PostgresPaperAccountRepository",
        CorruptCanonicalRepository,
    )
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "canonical")
    reload_settings()
    settings = Settings(
        paper_account=PaperAccountSettings(db_mode="canonical"),
    )

    api_response = TestClient(create_app(settings=settings, output_dir=tmp_path)).get(
        "/api/paper/account/snapshot"
    )
    json_result = runner.invoke(app, ["paper", "account-show", "--format", "json"])
    text_result = runner.invoke(app, ["paper", "account-show"])

    assert api_response.status_code == 503
    assert api_response.json()["detail"]["code"] == "paper_account_storage_corrupt"
    assert json_result.exit_code == 1
    assert json.loads(json_result.output)["error"]["code"] == ("paper_account_storage_corrupt")
    assert text_result.exit_code == 1
    assert "paper_account_storage_corrupt" in text_result.output
    assert not (tmp_path / "api_runs" / "paper_account").exists()
