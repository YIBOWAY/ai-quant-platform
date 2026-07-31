from __future__ import annotations

from pathlib import Path

from quant_system.storage.database import list_migration_files

MIGRATION_028 = "028_agent_v02_candidate_paper_epoch_fence.sql"


def test_028_is_additive_and_ordered_after_candidate_ttl_window() -> None:
    names = list_migration_files()

    assert names.index("027_agent_v02_candidate_ttl_window.sql") < names.index(
        MIGRATION_028
    )


def test_028_declares_replay_safe_metadata_and_stale_candidate_rejection() -> None:
    sql = Path("scripts/sql").joinpath(MIGRATION_028).read_text(encoding="utf-8")
    compact = " ".join(sql.split())

    assert "agent_v02_candidate_paper_fence_meta" in compact
    assert "028_agent_v02_candidate_paper_epoch_fence" in compact
    assert compact.count("CREATE OR REPLACE FUNCTION") == 2
    assert compact.count("paper_authority_epoch = current_paper_authority_epoch") >= 2
    assert compact.count("candidate paper authority epoch is stale") >= 2
    assert compact.count("ENABLE ALWAYS TRIGGER") == 2
    assert "agent_v02_public_cutovers" in compact
    assert "pg_advisory_xact_lock" in compact
    assert "COMMIT;" in compact


def test_028_freezes_the_canonical_default_account_and_marker_acl() -> None:
    sql = Path("scripts/sql").joinpath(MIGRATION_028).read_text(encoding="utf-8")
    compact = " ".join(sql.split())

    assert "ck_agent_v02_default_paper_account_raw_consistency" in compact
    assert compact.count("account.account_id = 'default'") >= 2
    assert compact.count(
        "account.raw -> 'account_id' = to_jsonb(account.account_id)"
    ) >= 2
    assert compact.count(
        "account.raw -> 'kill_switch' = to_jsonb(account.kill_switch)"
    ) >= 2
    assert (
        "REVOKE ALL ON TABLE "
        "quant_system.agent_v02_candidate_paper_fence_meta "
        "FROM quant_runtime"
    ) in compact
    assert (
        "REVOKE ALL ON TABLE "
        "quant_system.agent_v02_candidate_paper_fence_meta "
        "FROM quant_readonly"
    ) in compact
