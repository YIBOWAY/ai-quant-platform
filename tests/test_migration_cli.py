"""V1.1 stop-the-line: the explicit ``migrate`` command is fail-closed.

Dry-run is the default (lists candidate files + schema fingerprint, never calls
``run_migrations``). Applying requires ``--apply`` AND an explicit ``--allow``
allowlist; non-interactive apply additionally requires ``--yes``.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_sql_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the migration runner at a controlled SQL dir and stub the DB."""
    (tmp_path / "001_alpha.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "002_beta.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "003_gamma.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr("quant_system.storage.database._sql_dir", lambda: tmp_path)

    @contextmanager
    def _connect():
        yield object()

    fake_db = type("FakeDB", (), {"connect": staticmethod(_connect)})()
    monkeypatch.setattr(
        "quant_system.cli._migrate_get_database", lambda _settings: fake_db
    )
    monkeypatch.setattr(
        "quant_system.cli.schema_fingerprint", lambda _db: "<fingerprint>"
    )
    return tmp_path


def test_migrate_is_dry_run_by_default_and_applies_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applied: list[object] = []
    monkeypatch.setattr(
        "quant_system.cli.run_migrations",
        lambda *a, **k: applied.append(a),
    )

    result = runner.invoke(app, ["migrate"])

    assert result.exit_code == 0, result.output
    assert "001_alpha.sql" in result.output
    assert "003_gamma.sql" in result.output
    assert "dry-run" in result.output.lower()
    assert applied == []  # dry-run must never call run_migrations


def test_migrate_refuses_apply_without_allow() -> None:
    result = runner.invoke(app, ["migrate", "--apply", "--yes"])

    assert result.exit_code == 2
    assert "allow" in result.output.lower()


def test_migrate_refuses_noninteractive_apply_without_yes() -> None:
    # CliRunner is not a TTY; apply must require an explicit --yes.
    result = runner.invoke(app, ["migrate", "--apply", "--allow", "001_alpha.sql"])

    assert result.exit_code == 2
    assert "yes" in result.output.lower()


def test_migrate_apply_filters_to_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    def _run_migrations(_db, *, only=None):
        seen.append(only)

    monkeypatch.setattr("quant_system.cli.run_migrations", _run_migrations)

    result = runner.invoke(
        app,
        ["migrate", "--apply", "--yes", "--allow", "002_beta.sql"],
    )

    assert result.exit_code == 0, result.output
    assert seen == [{"002_beta.sql"}]


def test_migrate_apply_unknown_allow_file_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.cli.run_migrations",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not apply an unknown allowlist entry")
        ),
    )

    result = runner.invoke(
        app,
        ["migrate", "--apply", "--yes", "--allow", "999_missing.sql"],
    )

    assert result.exit_code != 0
    assert "999_missing.sql" in result.output
