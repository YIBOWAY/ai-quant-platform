from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from quant_system.config.settings import (
    LocalMutationSettings,
    PaperAccountSettings,
    Settings,
)
from quant_system.hermes import candidate_admission_cli
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.effective_release_gate import (
    ReleaseEvidenceObservation,
    RuntimeIdentityObservation,
)
from quant_system.hermes.intent_payload_port import IntentPayloadPortError


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
    monkeypatch.setattr(
        candidate_admission_cli,
        "build_intent_payload_port",
        lambda value: SimpleNamespace(
            probe=lambda: calls.append(("intent_crypto", value))
        ),
    )

    runtime = candidate_admission_cli.build_candidate_cli_runtime()

    assert runtime.settings is settings
    assert runtime.database is database
    assert runtime.authority is authority
    assert runtime.evidence_authority is evidence_authority
    assert runtime.intent_crypto_probe() is None
    assert runtime.runtime_identity_probe() is runtime_observation
    assert runtime.preflight_probe() is preflight_observation
    assert runtime.final_evidence_probe() is final_observation
    assert runtime.schema_fingerprint_probe() == "schema-fingerprint"
    assert runtime.order_snapshot_probe() is zero_order_observation
    assert calls == [
        ("admission_authority", (settings, database)),
        ("evidence_authority", (settings, database)),
        ("intent_crypto", settings),
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


def test_candidate_open_crypto_preflight_runs_after_exact_runtime_binding_before_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    emissions: list[dict[str, object]] = []
    digest = "a" * 64

    class _Authority:
        @staticmethod
        def open(_request: object) -> object:
            calls.append("authority.open")
            raise AssertionError("authority.open must stay untouched")

    def crypto_probe() -> None:
        calls.append("crypto")
        raise IntentPayloadPortError(
            "key_not_found",
            "helper OSStatus -25300 private detail",
            retryable=False,
        )

    def unexpected(name: str):
        def _probe():
            calls.append(name)
            raise AssertionError(f"{name} must not run after crypto preflight failure")

        return _probe

    def runtime_identity_probe():
        calls.append("runtime_identity")
        return SimpleNamespace(
            platform_runtime_digest=digest,
            hqa_runtime_digest=digest,
            hermes_runtime_digest=digest,
        )

    def preflight_probe():
        calls.append("preflight_evidence")
        return SimpleNamespace(
            digest="b" * 64,
            platform_runtime_digest=digest,
            hqa_runtime_digest=digest,
            hermes_runtime_digest=digest,
        )

    runtime = SimpleNamespace(
        settings=Settings(
            local_mutation=LocalMutationSettings(
                enabled=True,
                composer_open=True,
            ),
            paper_account=PaperAccountSettings(
                auto_process_pending_orders_enabled=False,
                db_mode="canonical",
            ),
        ),
        authority=_Authority(),
        intent_crypto_probe=crypto_probe,
        runtime_identity_probe=runtime_identity_probe,
        preflight_probe=preflight_probe,
        schema_fingerprint_probe=unexpected("schema"),
        order_snapshot_probe=unexpected("orders"),
    )
    monkeypatch.setattr(
        candidate_admission_cli,
        "build_candidate_cli_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(candidate_admission_cli, "_emit", emissions.append)

    with pytest.raises(candidate_admission_cli.typer.Exit) as caught:
        candidate_admission_cli.open_command(
            note="bounded local candidate",
            client_action_id="candidate-open-crypto-preflight",
        )

    assert caught.value.exit_code == 1
    assert calls == ["runtime_identity", "preflight_evidence", "crypto"]
    assert emissions == [
        {
            "contract": "agent-v0.2-candidate-cli/v1",
            "error_code": "candidate_intent_crypto_preflight_failed",
            "message": "intent crypto preflight failed closed",
            "operation": "open",
        }
    ]
    assert "OSStatus" not in json.dumps(emissions)
    assert "helper" not in json.dumps(emissions)


def test_candidate_open_runtime_mismatch_never_executes_hqa_crypto_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    emissions: list[dict[str, object]] = []

    runtime = SimpleNamespace(
        settings=SimpleNamespace(),
        authority=SimpleNamespace(
            open=lambda _request: (_ for _ in ()).throw(
                AssertionError("authority.open must stay untouched")
            )
        ),
        intent_crypto_probe=lambda: (_ for _ in ()).throw(
            AssertionError("unbound HQA crypto code must not execute")
        ),
        runtime_identity_probe=lambda: (
            calls.append("runtime_identity"),
            SimpleNamespace(
                platform_runtime_digest="a" * 64,
                hqa_runtime_digest="a" * 64,
                hermes_runtime_digest="a" * 64,
            ),
        )[1],
        preflight_probe=lambda: (
            calls.append("preflight_evidence"),
            SimpleNamespace(
                digest="b" * 64,
                platform_runtime_digest="a" * 64,
                hqa_runtime_digest="c" * 64,
                hermes_runtime_digest="a" * 64,
            ),
        )[1],
        schema_fingerprint_probe=lambda: (_ for _ in ()).throw(
            AssertionError("database must stay untouched")
        ),
        order_snapshot_probe=lambda: (_ for _ in ()).throw(
            AssertionError("orders must stay untouched")
        ),
    )
    monkeypatch.setattr(
        candidate_admission_cli,
        "build_candidate_cli_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(candidate_admission_cli, "_require_safety", lambda _settings: None)
    monkeypatch.setattr(candidate_admission_cli, "_emit", emissions.append)

    with pytest.raises(candidate_admission_cli.typer.Exit):
        candidate_admission_cli.open_command(
            note="bounded local candidate",
            client_action_id="candidate-open-runtime-mismatch",
        )

    assert calls == ["runtime_identity", "preflight_evidence"]
    assert emissions[-1]["error_code"] == "candidate_cli_unavailable"


@pytest.mark.parametrize("db_mode", ["file", "mirror"])
def test_candidate_open_requires_canonical_paper_authority_before_probes(
    monkeypatch: pytest.MonkeyPatch,
    db_mode: str,
) -> None:
    calls: list[str] = []
    emissions: list[dict[str, object]] = []

    def unexpected(name: str):
        return lambda *_args, **_kwargs: (
            calls.append(name),
            pytest.fail(f"{name} must stay untouched outside canonical paper mode"),
        )[1]

    runtime = SimpleNamespace(
        settings=Settings(
            local_mutation=LocalMutationSettings(
                enabled=True,
                composer_open=True,
            ),
            paper_account=PaperAccountSettings(
                auto_process_pending_orders_enabled=False,
                db_mode=db_mode,
            ),
        ),
        authority=SimpleNamespace(open=unexpected("authority.open")),
        intent_crypto_probe=unexpected("crypto"),
        runtime_identity_probe=unexpected("runtime_identity"),
        preflight_probe=unexpected("preflight_evidence"),
        schema_fingerprint_probe=unexpected("schema"),
        order_snapshot_probe=unexpected("orders"),
    )
    monkeypatch.setattr(
        candidate_admission_cli,
        "build_candidate_cli_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(candidate_admission_cli, "_emit", emissions.append)

    with pytest.raises(candidate_admission_cli.typer.Exit) as caught:
        candidate_admission_cli.open_command(
            note="bounded local candidate",
            client_action_id=f"candidate-open-{db_mode}",
        )

    assert caught.value.exit_code == 1
    assert calls == []
    assert emissions == [
        {
            "contract": "agent-v0.2-candidate-cli/v1",
            "error_code": "canonical_paper_authority_required",
            "message": "candidate operations require canonical paper authority",
            "operation": "open",
        }
    ]
