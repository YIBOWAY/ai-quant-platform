from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.config.settings import HorizonSettings, Settings
from quant_system.news import horizon_ingest, horizon_repository
from quant_system.news.horizon_ingest import ingest_horizon_inbox

FIXTURE_RUN = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "horizon_inbox"
    / "runs"
    / "20260723T120000Z-ab12"
)
RUN_ID = "20260723T120000Z-ab12"

runner = CliRunner()


class _FakeConnection:
    """Minimal capturing connection that tracks ingested provider runs."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self._ingested: set[tuple[str, str, str]] = set()
        self._lookup: tuple | None = None

    def execute(self, sql: str, params: tuple = ()) -> _FakeConnection:
        self.statements.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if "from quant_system.ai_news_provider_runs" in normalized and "select 1" in normalized:
            provider, run_id, digest, _status = params
            if (provider, run_id, digest) in self._ingested:
                self._lookup = (1,)
            else:
                self._lookup = None
        if (
            "insert into quant_system.ai_news_provider_runs" in normalized
            and params
            and len(params) >= 10
        ):
            # params: provider, run_id, generated_at, ..., content_digest, status, ...
            provider = params[0]
            run_id = params[1]
            digest = params[8]
            status = params[9]
            if status == "ingested":
                self._ingested.add((str(provider), str(run_id), str(digest)))
        return self

    def fetchone(self) -> tuple | None:
        return self._lookup

    def fetchall(self) -> list[tuple]:
        return []


class _FakeDatabase:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    @contextmanager
    def connect(self) -> Iterator[_FakeConnection]:
        yield self.connection


def _copy_fixture_inbox(tmp_path: Path) -> Path:
    dest_run = tmp_path / "runs" / RUN_ID
    shutil.copytree(FIXTURE_RUN, dest_run)
    return tmp_path


def _settings(inbox_dir: Path, *, enabled: bool = True) -> Settings:
    settings = Settings()
    settings.horizon = HorizonSettings(
        inbox_dir=str(inbox_dir),
        enabled=enabled,
    )
    return settings


def test_ingest_writes_provider_run_and_items(monkeypatch, tmp_path: Path) -> None:
    inbox = _copy_fixture_inbox(tmp_path)
    connection = _FakeConnection()
    fake_db = _FakeDatabase(connection)
    monkeypatch.setattr(horizon_repository, "get_database", lambda _settings: fake_db)
    # repository helpers used inside persist_horizon_run also call get_database
    monkeypatch.setattr(
        "quant_system.news.repository.get_database",
        lambda _settings: fake_db,
    )

    settings = _settings(inbox)
    result = ingest_horizon_inbox(settings=settings)

    assert RUN_ID in result["ingested"]
    assert result["skipped"] == []
    assert result["failed"] == []
    assert (inbox / "runs" / RUN_ID / "INGESTED").is_file()

    sql_blob = "\n".join(sql for sql, _ in connection.statements)
    assert "ai_news_items" in sql_blob
    assert "ai_news_provider_runs" in sql_blob

    result2 = ingest_horizon_inbox(settings=settings)
    assert RUN_ID in result2["skipped"]
    assert result2["ingested"] == []


def test_ingest_disabled_is_noop(monkeypatch, tmp_path: Path) -> None:
    inbox = _copy_fixture_inbox(tmp_path)
    called: list[str] = []

    def _boom(*_a, **_k):  # pragma: no cover - must not run
        called.append("db")
        raise AssertionError("disabled ingest must not touch DB")

    monkeypatch.setattr(horizon_ingest, "is_run_ingested", _boom)
    monkeypatch.setattr(horizon_ingest, "persist_horizon_run", _boom)

    result = ingest_horizon_inbox(settings=_settings(inbox, enabled=False))
    assert result == {"ingested": [], "skipped": [], "failed": []}
    assert called == []
    assert not (inbox / "runs" / RUN_ID / "INGESTED").exists()


def test_ingest_run_id_filter(monkeypatch, tmp_path: Path) -> None:
    inbox = _copy_fixture_inbox(tmp_path)
    persisted: list[str] = []

    monkeypatch.setattr(
        horizon_ingest,
        "is_run_ingested",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        horizon_ingest,
        "persist_horizon_run",
        lambda run, *, settings: persisted.append(run.run_id),
    )

    result = ingest_horizon_inbox(settings=_settings(inbox), run_id="no-such-run")
    assert result["ingested"] == []
    assert persisted == []

    result = ingest_horizon_inbox(settings=_settings(inbox), run_id=RUN_ID)
    assert result["ingested"] == [RUN_ID]
    assert persisted == [RUN_ID]


def test_ingest_failure_recorded_without_marker(monkeypatch, tmp_path: Path) -> None:
    inbox = _copy_fixture_inbox(tmp_path)
    monkeypatch.setattr(horizon_ingest, "is_run_ingested", lambda *_a, **_k: False)

    def _fail(run, *, settings):  # noqa: ARG001
        raise RuntimeError("boom")

    monkeypatch.setattr(horizon_ingest, "persist_horizon_run", _fail)

    result = ingest_horizon_inbox(settings=_settings(inbox))
    assert result["ingested"] == []
    assert result["skipped"] == []
    assert len(result["failed"]) == 1
    assert result["failed"][0]["run_id"] == RUN_ID
    assert "boom" in result["failed"][0]["error"]
    assert not (inbox / "runs" / RUN_ID / "INGESTED").exists()


def test_horizon_ingest_cli(monkeypatch, tmp_path: Path) -> None:
    inbox = _copy_fixture_inbox(tmp_path)
    captured: dict[str, object] = {}

    def _fake_ingest(*, settings, run_id=None):
        captured["inbox_dir"] = settings.horizon.inbox_dir
        captured["enabled"] = settings.horizon.enabled
        captured["run_id"] = run_id
        return {"ingested": [RUN_ID], "skipped": [], "failed": []}

    monkeypatch.setattr(
        "quant_system.news.horizon_ingest.ingest_horizon_inbox",
        _fake_ingest,
    )

    result = runner.invoke(
        app,
        [
            "news",
            "horizon-ingest",
            "--inbox",
            str(inbox),
            "--run-id",
            RUN_ID,
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ingested"] == [RUN_ID]
    assert captured["inbox_dir"] == str(inbox)
    assert captured["run_id"] == RUN_ID


def test_horizon_ingest_cli_exits_nonzero_when_failed(monkeypatch, tmp_path: Path) -> None:
    inbox = _copy_fixture_inbox(tmp_path)

    def _fake_ingest(*, settings, run_id=None):  # noqa: ARG001
        return {
            "ingested": [],
            "skipped": [],
            "failed": [{"run_id": RUN_ID, "error": "boom"}],
        }

    monkeypatch.setattr(
        "quant_system.news.horizon_ingest.ingest_horizon_inbox",
        _fake_ingest,
    )

    result = runner.invoke(
        app,
        [
            "news",
            "horizon-ingest",
            "--inbox",
            str(inbox),
        ],
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert len(payload["failed"]) == 1
