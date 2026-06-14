from __future__ import annotations

from quant_system.storage import database as db


def test_database_health_failure_uses_cooldown(monkeypatch) -> None:
    calls = 0
    connect_timeouts: list[int] = []

    def fail_connect(*_args, **kwargs):
        nonlocal calls
        calls += 1
        connect_timeouts.append(kwargs["connect_timeout"])
        raise OSError("database is down")

    monkeypatch.setattr(db.psycopg, "connect", fail_connect)
    database = db.Database(
        "postgresql://quant:quantpass@127.0.0.1:5432/quantplatform",
        connect_timeout=5,
        failure_cooldown_seconds=60,
    )

    assert database.healthy() is False
    assert database.healthy() is False
    assert calls == 1
    assert connect_timeouts == [1]
