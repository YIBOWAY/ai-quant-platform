from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from quant_system.hermes import candidate_admission_cli
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.effective_release_gate import (
    ReleaseEvidenceObservation,
    RuntimeIdentityObservation,
)


def test_build_candidate_cli_runtime_binds_all_production_probes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight_path = tmp_path / "preflight-v2.json"
    final_path = tmp_path / "final-v4.json"
    settings = SimpleNamespace(
        candidate_admission=SimpleNamespace(
            preflight_evidence_file=preflight_path,
            final_evidence_file=final_path,
        )
    )
    connection = object()

    class _Database:
        @contextmanager
        def connect(self):
            yield connection

    database = _Database()
    authority = object()
    evidence_authority = object()
    runtime_observation = object()
    preflight_observation = object()
    final_observation = object()
    zero_order_observation = object()
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(candidate_admission_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        candidate_admission_cli,
        "get_database",
        lambda value: database if value is settings else None,
    )
    monkeypatch.setattr(
        candidate_admission_cli,
        "CandidateAdmissionAuthority",
        lambda value, *, database: (
            calls.append(("admission_authority", (value, database))),
            authority,
        )[1],
    )
    monkeypatch.setattr(
        candidate_admission_cli,
        "CandidateEvidenceV3Authority",
        lambda value, *, database: (
            calls.append(("evidence_authority", (value, database))),
            evidence_authority,
        )[1],
    )
    monkeypatch.setattr(
        candidate_admission_cli,
        "runtime_identity_observation",
        lambda value: (
            calls.append(("runtime", value)),
            runtime_observation,
        )[1],
    )
    monkeypatch.setattr(
        candidate_admission_cli,
        "candidate_preflight_evidence_observation",
        lambda path: (
            calls.append(("preflight", path)),
            preflight_observation,
        )[1],
    )
    monkeypatch.setattr(
        candidate_admission_cli,
        "release_evidence_observation",
        lambda path: (
            calls.append(("final", path)),
            final_observation,
        )[1],
    )
    monkeypatch.setattr(
        candidate_admission_cli,
        "schema_fingerprint",
        lambda value: (
            calls.append(("schema", value)),
            "schema-fingerprint",
        )[1],
    )

    def _zero_orders(
        conn: object,
        *,
        owner_user_id: str,
    ) -> Any:
        calls.append(("zero_orders", (conn, owner_user_id)))
        return zero_order_observation

    monkeypatch.setattr(
        candidate_admission_cli,
        "capture_canonical_zero_order_snapshot",
        _zero_orders,
    )

    runtime = candidate_admission_cli.build_candidate_cli_runtime()

    assert runtime.settings is settings
    assert runtime.database is database
    assert runtime.authority is authority
    assert runtime.evidence_authority is evidence_authority
    assert runtime.runtime_identity_probe() is runtime_observation
    assert runtime.preflight_probe() is preflight_observation
    assert runtime.final_evidence_probe() is final_observation
    assert runtime.schema_fingerprint_probe() == "schema-fingerprint"
    assert runtime.order_snapshot_probe() is zero_order_observation
    assert calls == [
        ("admission_authority", (settings, database)),
        ("evidence_authority", (settings, database)),
        ("runtime", settings),
        ("preflight", preflight_path),
        ("final", final_path),
        ("schema", database),
        ("zero_orders", (connection, ROOT_USER_ID)),
    ]


@pytest.mark.parametrize(
    ("contract", "accepted"),
    [
        ("agent-v0.2-release-evidence/v4", True),
        ("agent-v0.2-release-evidence/v3", False),
    ],
)
def test_candidate_accept_requires_final_v4_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contract: str,
    accepted: bool,
) -> None:
    digest = "a" * 64
    evidence_digest = "b" * 64
    orders_digest = "c" * 64
    runtime_digest = "d" * 64
    final_path = tmp_path / "final.json"
    current = SimpleNamespace(
        admission_id="admission-1",
        admission_digest=digest,
        platform_runtime_digest=runtime_digest,
        hqa_runtime_digest=runtime_digest,
        hermes_runtime_digest=runtime_digest,
        database_schema_fingerprint=digest,
    )
    accepted_requests: list[object] = []

    class _Authority:
        @staticmethod
        def active(workspace_id: str):
            assert workspace_id == "workspace-root"
            return current

        @staticmethod
        def accept(request):
            accepted_requests.append(request)
            return SimpleNamespace(
                to_storage_dict=lambda: {"status": "accepted"},
            )

    runtime = SimpleNamespace(
        settings=SimpleNamespace(
            agent_v02_release=SimpleNamespace(workspace_id="workspace-root"),
            candidate_admission=SimpleNamespace(final_evidence_file=final_path),
        ),
        authority=_Authority(),
        runtime_identity_probe=lambda: RuntimeIdentityObservation(
            platform_runtime_digest=runtime_digest,
            hqa_runtime_digest=runtime_digest,
            hermes_runtime_digest=runtime_digest,
        ),
        schema_fingerprint_probe=lambda: digest,
        final_evidence_probe=lambda: ReleaseEvidenceObservation(
            digest=evidence_digest,
            platform_runtime_digest=runtime_digest,
            hqa_runtime_digest=runtime_digest,
            hermes_runtime_digest=runtime_digest,
            contract=contract,
            candidate_admission_id="admission-1",
            candidate_admission_digest=digest,
            evidence_set_id="evidence-1",
            evidence_set_digest=evidence_digest,
            final_order_snapshot_digest=orders_digest,
        ),
    )
    emissions: list[dict[str, object]] = []
    monkeypatch.setattr(
        candidate_admission_cli,
        "build_candidate_cli_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(candidate_admission_cli, "_require_safety", lambda _settings: None)
    monkeypatch.setattr(candidate_admission_cli, "file_sha256", lambda _path: evidence_digest)
    monkeypatch.setattr(candidate_admission_cli, "_emit", emissions.append)

    arguments = {
        "admission_id": "admission-1",
        "expected_admission_digest": digest,
        "evidence_set_id": "evidence-1",
        "evidence_set_digest": evidence_digest,
        "final_order_snapshot_digest": orders_digest,
        "note": "reviewed exact v4 evidence",
        "client_action_id": "accept-v4",
    }
    if accepted:
        candidate_admission_cli.accept_command(**arguments)
        assert len(accepted_requests) == 1
        assert emissions[-1]["status"] == "accepted"
    else:
        with pytest.raises(candidate_admission_cli.typer.Exit):
            candidate_admission_cli.accept_command(**arguments)
        assert accepted_requests == []
        assert emissions[-1]["error_code"] == "candidate_cli_unavailable"
