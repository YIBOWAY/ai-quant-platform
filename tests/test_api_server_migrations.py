"""V1.1 stop-the-line: startup must not auto-apply migrations unless explicitly on.

``_init_run_index`` runs in a daemon thread at API startup. These tests call it
synchronously (not the thread wrapper) and monkeypatch the migration/DB seams to
assert the fail-closed default: with ``auto_migrate=False`` startup never calls
``run_migrations``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_system.api import server
from quant_system.config.settings import DatabaseSettings, Settings


def _db_enabled_settings(*, auto_migrate: bool) -> Settings:
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url="postgresql://quant:quantpass@127.0.0.1:5432/quantplatform_codex_tmp",
            auto_migrate=auto_migrate,
        )
    )


def test_startup_does_not_run_migrations_when_auto_migrate_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "quant_system.storage.database.get_database", lambda _s: object()
    )
    monkeypatch.setattr(
        "quant_system.storage.database.run_migrations",
        lambda _db: calls.append("migrated"),
    )
    monkeypatch.setattr(
        "quant_system.storage.runs_repository.sync_filesystem_to_index",
        lambda _dir, _s: calls.append("synced"),
    )

    server._init_run_index(_db_enabled_settings(auto_migrate=False), tmp_path)

    assert "migrated" not in calls
    # Backfill still runs (filesystem -> index); only the auto-migrate is gated.
    assert calls == ["synced"]


def test_startup_runs_migrations_when_auto_migrate_true(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "quant_system.storage.database.get_database", lambda _s: object()
    )
    monkeypatch.setattr(
        "quant_system.storage.database.run_migrations",
        lambda _db: calls.append("migrated"),
    )
    monkeypatch.setattr(
        "quant_system.storage.runs_repository.sync_filesystem_to_index",
        lambda _dir, _s: calls.append("synced"),
    )

    server._init_run_index(_db_enabled_settings(auto_migrate=True), tmp_path)

    assert calls == ["migrated", "synced"]


def test_startup_skips_db_work_when_database_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _forbidden(*_a: object, **_k: object) -> None:  # pragma: no cover - guard
        raise AssertionError("database seams must not be touched when disabled")

    monkeypatch.setattr("quant_system.storage.database.get_database", _forbidden)
    monkeypatch.setattr("quant_system.storage.database.run_migrations", _forbidden)

    settings = Settings(database=DatabaseSettings(enabled=False, url=None))
    server._init_run_index(settings, tmp_path)  # must be a no-op, never raises
