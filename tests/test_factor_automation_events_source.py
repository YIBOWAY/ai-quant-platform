from pathlib import Path

from quant_system.storage.database import list_migration_files

MIGRATION = "029_factor_automation_events.sql"


def test_029_is_ordered_after_candidate_paper_epoch_fence() -> None:
    names = list_migration_files()
    assert names.index("028_agent_v02_candidate_paper_epoch_fence.sql") < names.index(
        MIGRATION
    )


def test_029_is_append_only_and_owns_daily_quota() -> None:
    compact = " ".join(Path("scripts/sql", MIGRATION).read_text().split())

    assert "factor_automation_events" in compact
    assert "factor_automation_events_meta" in compact
    assert "Asia/Shanghai" in compact
    assert "promotion_committed" in compact
    assert "demote_started" in compact
    assert "promotion daily quota exceeded" in compact
    assert "demote daily quota exceeded" in compact
    assert (
        "CREATE OR REPLACE FUNCTION "
        "quant_system.reject_factor_automation_event_mutation"
    ) in compact
    assert "CREATE OR REPLACE FUNCTION quant_system.append_factor_automation_event" in compact
    assert "ENABLE ALWAYS TRIGGER" in compact
    assert "REVOKE INSERT, UPDATE, DELETE" in compact
    assert "GRANT EXECUTE ON FUNCTION" in compact
    assert "COMMIT;" in compact


def test_029_requires_paper_only_auto_lineage() -> None:
    compact = " ".join(Path("scripts/sql", MIGRATION).read_text().split())

    for field in (
        "candidate_digest",
        "manifest_digest",
        "automation_policy_digest",
        "intake_contract_digest",
        "gate1_digest",
        "gate2_digest",
        "gate3_digest",
        "commit_sha",
    ):
        assert field in compact
    assert "promotion_scope = 'paper_only'" in compact
    assert "reviewer = 'auto'" in compact
