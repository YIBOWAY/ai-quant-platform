from __future__ import annotations

from pathlib import Path

MIGRATION = Path("scripts/sql/027_agent_v02_candidate_ttl_window.sql")


def test_candidate_ttl_migration_is_bounded_replay_safe_and_non_authorizing() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    compact = " ".join(sql.split()).lower()

    assert "begin;" in compact
    assert "commit;" in compact
    assert "quant_system:hermes_schema_runtime_gate" in compact
    assert "quant_system:027_agent_v02_candidate_ttl_window" in compact
    assert "requires migration 016" in compact
    assert "schema version 1" in compact
    assert "drop constraint if exists ck_agent_v02_candidate_ttl" in compact
    assert "add constraint ck_agent_v02_candidate_ttl" in compact
    assert "expires_at > opened_at" in compact
    assert "expires_at <= opened_at + interval '2 hours'" in compact
    assert "30 minutes" not in compact
    assert "public_cutover" not in compact
    assert "release_authorized" not in compact
    assert "live_trading" not in compact
