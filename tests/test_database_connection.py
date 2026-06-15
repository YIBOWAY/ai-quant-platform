from __future__ import annotations

import threading

import pytest

from quant_system.storage.database import Database, DatabaseUnavailable


class _FakeConnection:
    def execute(self, _sql: str) -> None:
        return None

    def close(self) -> None:
        return None


def test_database_allows_concurrent_successful_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    attempts = 0
    attempts_lock = threading.Lock()
    failures: list[BaseException] = []

    def fake_connect(*_args, **_kwargs) -> _FakeConnection:
        nonlocal attempts
        with attempts_lock:
            attempts += 1
            current = attempts
        if current == 1:
            first_started.set()
            assert release_first.wait(timeout=2)
        return _FakeConnection()

    monkeypatch.setattr("quant_system.storage.database.psycopg.connect", fake_connect)
    database = Database("postgresql://example", connect_timeout=1)

    def open_connection() -> None:
        try:
            with database.connect():
                pass
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    first = threading.Thread(target=open_connection)
    first.start()
    assert first_started.wait(timeout=2)

    try:
        with database.connect():
            pass
    except BaseException as exc:  # pragma: no cover - asserted below
        failures.append(exc)
    finally:
        release_first.set()
        first.join(timeout=2)

    assert attempts == 2
    assert not any(isinstance(exc, DatabaseUnavailable) for exc in failures)
    assert failures == []
