"""Bounded read projection over real saved-job readers; no market or engine claims."""

import io
import json

import pytest

from quant_system.config.settings import DataSettings, Settings
from quant_system.research import external_intake as service
from quant_system.research import external_intake_cli as cli


def test_compact_show_keeps_identity_and_unknown_diagnostics_without_writes(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, data=DataSettings(data_dir=tmp_path))
    job_id = "intake-" + "a" * 24
    proposal = {"proposal_id": "artificial-large-archive"}
    job = {
        "job_id": job_id,
        "proposal_id": proposal["proposal_id"],
        "proposal": proposal,
        "payload_sha256": service._sha(proposal),
        "plans": [],
        "plans_sha256": service._sha([]),
        "created_at": "2026-09-25T00:00:00Z",
        "updated_at": "2026-09-25T00:01:00Z",
        "status": "failed",
        "error": "artificial_missing_receipt",
        "results": [
            {
                "variant": "formula",
                "status": "validation_failed",
                "phase": "done",
                "validation_sha256": "b" * 64,
                "qualification_flow": {"artificial_large_record": "PRIVATE_BODY" * 300000},
            }
        ],
    }
    path = tmp_path / "research_intake/jobs" / (job_id + ".json")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(job))
    before = path.read_bytes()
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    full, compact = io.StringIO(), io.StringIO()
    assert cli.main(["show", job_id], stdout=full) == 1
    assert cli.main(["show", job_id, "--compact"], stdout=compact) == 1
    original, projected = json.loads(full.getvalue()), json.loads(compact.getvalue())
    assert len(full.getvalue().encode()) > 2 * 1024 * 1024
    assert len(compact.getvalue().encode()) < 8192
    assert projected["projection"] == "compact_intake_job/v1"
    for field in (
        "contract",
        "action",
        "ok",
        "job_id",
        "proposal_id",
        "payload_sha256",
        "status",
        "outcome",
        "updated_at",
        "error",
    ):
        assert projected[field] == original[field]
    assert projected["results"][0]["diagnostics"] == original["results"][0]["diagnostics"]
    assert projected["results"][0]["diagnostics"]["status"] == "unavailable"
    assert "PRIVATE_BODY" not in compact.getvalue()
    assert path.read_bytes() == before
    assert list(tmp_path.rglob("*.json")) == [path]


@pytest.mark.parametrize(
    "diagnostic",
    [
        {"status": "available", "binding": "archived_validation_sha256_not_revalidation"},
        {"status": "unavailable", "reason": "bound_validation_diagnostics_unavailable"},
        {},
    ],
)
def test_compaction_does_not_infer_or_upgrade_receipt_availability(diagnostic):
    original = {
        "status": "failed",
        "results": [
            {
                "validation_sha256": "c" * 64,
                "diagnostics": diagnostic,
            }
        ],
    }
    projected = cli._compact_show(original)
    assert projected["results"][0]["diagnostics"] == diagnostic
    assert projected["results"][0]["validation_sha256"] == "c" * 64
    assert projected["status"] == "failed"


def test_compact_flag_is_not_a_reconcile_or_run_once_action():
    for action in (["run-once", "--compact"], ["reconcile", "intake-" + "a" * 24, "--compact"]):
        stream = io.StringIO()
        assert cli.main(action, stdout=stream) == 2
        assert json.loads(stream.getvalue())["error"] == "intake_cli_arguments_invalid"
