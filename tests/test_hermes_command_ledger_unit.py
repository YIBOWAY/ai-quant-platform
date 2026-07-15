from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.command_ledger import (
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
    HermesCommandValidationError,
    command_ledger_schema_version,
)


def test_command_ledger_has_no_file_or_memory_fallback_when_database_is_disabled() -> None:
    ledger = HermesCommandLedger(
        Settings(database=DatabaseSettings(enabled=False, url=None))
    )

    with pytest.raises(HermesCommandLedgerUnavailable):
        ledger.create_command(
            platform_session_id="platform-session-disabled",
            client_request_id="req-ledger-disabled-001",
            kind="research_chat",
            canonical_request_digest="a" * 64,
            payload_ref="platform-payload://research/disabled-001",
        )


def test_command_ledger_rejects_raw_prompt_as_payload_reference_before_database_access() -> None:
    ledger = HermesCommandLedger(
        Settings(database=DatabaseSettings(enabled=False, url=None))
    )

    with pytest.raises(HermesCommandValidationError):
        ledger.create_command(
            platform_session_id="platform-session-invalid-payload",
            client_request_id="req-ledger-invalid-payload-001",
            kind="research_chat",
            canonical_request_digest="a" * 64,
            payload_ref="Please analyze my portfolio and use this bearer token",
        )


def test_run_link_rejects_noncanonical_digest_before_database_access() -> None:
    ledger = HermesCommandLedger(
        Settings(database=DatabaseSettings(enabled=False, url=None))
    )

    with pytest.raises(HermesCommandValidationError, match="link_digest"):
        ledger.record_run_link(
            command_id=UUID("00000000-0000-0000-0000-000000000123"),
            expected_version=1,
            platform_resource_type="experiment",
            platform_resource_id="experiment-001",
            relation="output",
            hermes_session_id="hermes-session-001",
            hermes_run_id="hermes-run-001",
            link_digest="0" * 64,
            source_event_id="event-001",
            observed_at=datetime(2026, 7, 15, tzinfo=UTC),
        )


def test_schema_readiness_is_false_when_postgres_is_disabled() -> None:
    settings = Settings(database=DatabaseSettings(enabled=False, url=None))

    assert command_ledger_schema_version(settings) is None
