"""Sealed orchestration tests; stubs here do not constitute market qualification."""

import hashlib
import json
from pathlib import Path

import pytest

from quant_system.research import admission_qualification_flow as flow
from quant_system.research import admission_window as window
from tests import test_admission_qualification_flow as old_flow
from tests import test_admission_v2 as core


@pytest.fixture
def context(tmp_path, monkeypatch):
    from quant_system.research import admission_consumer_checks as consumer

    # Explicit artificial ledger for orchestration tests, never a market result.
    monkeypatch.setattr(consumer, "LEDGER_SHA", hashlib.sha256(b"sealed-test-ledger\n").hexdigest())
    return old_flow.context.__wrapped__(tmp_path)


def auto_recipes(settings):
    path = old_flow.recipes(settings)
    value = json.loads(path.read_text())
    namespace = flow._root(settings) / "windows"
    ledger = Path(settings.data.data_dir) / "sealed-calibration.jsonl"
    ledger.write_bytes(b"sealed-test-ledger\n")
    value["recipes"]["data"] = {"dataset": window.DATASET, "source_root": str(namespace)}
    value["recipes"]["consumer"].update(
        control_version=window.CONTROL_VERSION, random_root=str(namespace),
        calibration_ledger_path=str(ledger),
    )
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path, value


@pytest.mark.parametrize("change", ["outside", "symlink", "version", "random_root"])
def test_dynamic_owner_recipe_cannot_redirect_or_misbind_production(context, tmp_path, change):
    path, value = auto_recipes(context["settings"])
    if change == "outside":
        value["recipes"]["data"]["source_root"] = str(tmp_path / "outside")
    elif change == "symlink":
        namespace = Path(value["recipes"]["data"]["source_root"])
        (tmp_path / "elsewhere").mkdir()
        namespace.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    elif change == "version":
        value["recipes"]["consumer"]["control_version"] = "futu24-saved-intake-20260924"
    else:
        value["recipes"]["consumer"]["random_root"] = str(tmp_path / "different")
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="qualification_window_recipe"):
        flow.read_recipes(context["settings"])


def test_dynamic_scope_is_not_a_preapproved_funding_scope(context):
    from quant_system.research.admission_activation import _owner_scope

    auto_recipes(context["settings"])
    with pytest.raises(ValueError, match="activation_window_scope_requires_frozen_stage"):
        _owner_scope(context["settings"])


def programs(monkeypatch, *, fail=None):
    calls = []
    monkeypatch.setattr(window, "window_identity", lambda *a: {
        "window_id": "futu24-window-" + "b" * 64,
        "context": {"end": "2026-09-25"},
    })

    def freeze(settings, *, validation_path, output):
        calls.append("freeze")
        output = Path(output)
        output.mkdir(parents=True)
        core.write(output / "input-manifest.json", {"test_fixture": True})
        return {"manifest_path": str(output / "input-manifest.json"),
                "manifest_sha256": flow._sha(output / "input-manifest.json"),
                "window_id": "futu24-window-" + "b" * 64,
                "context": {"end": "2026-09-25"}}

    monkeypatch.setattr(window, "freeze_window", freeze)
    monkeypatch.setattr(window, "read_window", lambda *a: (None, {
        "window_id": "futu24-window-" + "b" * 64,
        "context": {"end": "2026-09-25"},
    }))

    def produce(path, digest, family_ledger, output):
        assert Path(family_ledger).name == "sealed-calibration.jsonl"
        assert Path(family_ledger).read_bytes() == b"sealed-test-ledger\n"
        calls.append("produce_controls")
        Path(output).mkdir(parents=True)
        core.write(Path(output) / "summary.json", {"test_fixture": True})
        core.write(Path(output) / "artifact-manifest.json", {"test_fixture": True})
        return {"n_variants": 500, "successful": 500}

    monkeypatch.setattr(window, "produce_controls", produce)
    from quant_system.research import admission_qualifier as qualifier

    monkeypatch.setattr(qualifier, "inspect_data_binding", lambda *a: {"input_digest": "a" * 64})

    def register(settings, *, kind, evidence, **kwargs):
        calls.append(kind)
        if kind == "data":
            assert evidence["window_manifest_sha256"]
            assert Path(evidence["source_root"]).name.startswith("input")
        if kind == "consumer":
            assert "calibration_ledger_path" not in evidence
            assert evidence["window_manifest_sha256"]
            assert Path(evidence["window_manifest"]).name == "input-manifest.json"
            assert Path(evidence["random_root"]).name == "controls"
        return {"descriptor": {"path": "/sealed/" + kind},
                "verification": {"status": "not_evaluated" if kind == fail else "passed",
                                 "reason": "sealed-rejection" if kind == fail else None}}

    monkeypatch.setattr(qualifier, "register_qualification", register)
    return calls


@pytest.mark.parametrize("failure", ["data", "review"])
def test_failed_cheap_checks_never_generate_controls(context, monkeypatch, failure):
    auto_recipes(context["settings"])
    calls = programs(monkeypatch, fail=failure)
    result = flow.ensure_qualifications(context["settings"],
        validation_path=context["validation_path"], protocol=context["protocol"])
    assert result["status"] == "not_evaluated"
    assert "produce_controls" not in calls
    assert calls == (["freeze", "data"] if failure == "data" else ["freeze", "data", "review"])
    assert result["capital_authorized"] is False


def test_dynamic_flow_produces_once_after_both_cheap_checks(context, monkeypatch):
    auto_recipes(context["settings"])
    calls = programs(monkeypatch)
    arguments = dict(validation_path=context["validation_path"], protocol=context["protocol"])
    result = flow.ensure_qualifications(context["settings"], **arguments)
    assert result["status"] == "registered"
    assert calls == ["freeze", "data", "review", "produce_controls", "consumer"]
    assert result["window"]["context"]["end"] == "2026-09-25"
    assert result["control_variants_generated"] == 500
    assert result["backtests_run"] is None  # no false zero for cold engine audit
    assert result["new_trials"] == 0  # these are calibration controls, not alpha hypotheses
    assert flow.ensure_qualifications(context["settings"], **arguments)["cached"] is True
    assert calls == ["freeze", "data", "review", "produce_controls", "consumer"]
    assert not (context["settings"].data.data_dir / "api_runs").exists()


def test_partial_window_directory_is_preserved_and_not_reused_as_complete(context, monkeypatch):
    auto_recipes(context["settings"])
    calls = programs(monkeypatch)
    root = flow._root(context["settings"]) / "windows" / ("futu24-window-" + "b" * 64)
    incomplete = root / "input"
    incomplete.mkdir(parents=True)
    (incomplete / "partial.txt").write_text("retained failure evidence")
    result = flow.ensure_qualifications(context["settings"],
        validation_path=context["validation_path"], protocol=context["protocol"])
    assert result["status"] == "not_evaluated"
    assert result["reason"] == "qualification_window_input_incomplete"
    assert (incomplete / "partial.txt").read_text() == "retained failure evidence"
    assert calls == []


def test_data_context_cannot_borrow_a_dynamic_window_for_other_rules():
    from quant_system.research.admission_qualifier import require_supported_data_context

    context = window.window_context("2026-09-25")
    for field, invalid in [("top_n", 6), ("rebalance", "weekly"), ("slippage_bps", 0)]:
        with pytest.raises(ValueError, match="qualification_calibration_context_mismatch"):
            require_supported_data_context(window.DATASET, {**context, field: invalid})


def test_new_window_module_is_in_the_admission_identity():
    from quant_system.research.admission_v2 import code_identity

    assert "research/admission_window.py" in code_identity()["files"]


def test_dated_control_cannot_smuggle_an_unverified_window_manifest():
    from quant_system.research.admission_consumer_checks import _control_spec

    with pytest.raises(ValueError, match="consumer_evidence_schema_invalid"):
        _control_spec({"random_root": "/unused", "data_root": "/unused",
                       "peer_snapshot_path": "/unused",
                       "control_version": "futu24-saved-intake-20260924",
                       "window_manifest": "/unverified", "window_manifest_sha256": "a" * 64})


def test_transient_interrupted_input_uses_new_slot_and_retains_failed_bytes(context, monkeypatch):
    auto_recipes(context["settings"])
    calls = programs(monkeypatch)
    original = window.freeze_window
    failed = []

    def interrupt_once(settings, *, validation_path, output):
        if not failed:
            output.mkdir()
            (output / "partial.txt").write_text("original interrupted bytes")
            failed.append(output)
            raise OSError("sealed transient disk failure")
        return original(settings, validation_path=validation_path, output=output)

    monkeypatch.setattr(window, "freeze_window", interrupt_once)
    now = [1000.0]
    monkeypatch.setattr(flow.time, "time", lambda: now[0])
    kwargs = dict(validation_path=context["validation_path"], protocol=context["protocol"])
    first = flow.ensure_qualifications(context["settings"], **kwargs)
    assert first["retryable"] is True and first["status"] == "not_evaluated"
    assert calls == []
    now[0] = 1031
    second = flow.ensure_qualifications(context["settings"], **kwargs)
    assert second["status"] == "registered"
    assert Path(second["window"]["manifest_path"]).parent.name == "input-attempt-0002"
    assert (failed[0] / "partial.txt").read_text() == "original interrupted bytes"
    assert (failed[0].parent / "production-history/input/0001.json").is_file()


def test_completed_window_artifact_cannot_be_replaced_by_a_fresh_slot(tmp_path):
    root = tmp_path / "window"
    root.mkdir()
    directory = flow._window_slot(root, "input", "input-manifest.json")
    directory.mkdir()
    manifest = directory / "input-manifest.json"
    manifest.write_text("original")
    flow._window_completed(root, "input", manifest)
    manifest.write_text("changed")
    with pytest.raises(ValueError, match="qualification_window_completed_artifact_changed"):
        flow._window_slot(root, "input", "input-manifest.json")
    assert not (root / "input-attempt-0002").exists()


@pytest.mark.parametrize("change", ["missing", "absent_file", "symlink", "different_population"])
def test_dynamic_calibration_ledger_is_explicit_and_pinned(context, tmp_path, change):
    path, value = auto_recipes(context["settings"])
    recipe = value["recipes"]["consumer"]
    ledger = Path(recipe["calibration_ledger_path"])
    if change == "missing":
        del recipe["calibration_ledger_path"]
    elif change == "absent_file":
        recipe["calibration_ledger_path"] = str(tmp_path / "missing.jsonl")
    elif change == "symlink":
        link = tmp_path / "linked.jsonl"
        link.symlink_to(ledger)
        recipe["calibration_ledger_path"] = str(link)
    else:
        ledger.write_bytes(b"a different or incomplete population\n")
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="qualification_window_calibration_ledger_invalid"):
        flow.read_recipes(context["settings"])


def test_dated_recipe_cannot_accept_dynamic_calibration_path(context):
    path = old_flow.recipes(context["settings"])
    value = json.loads(path.read_text())
    value["recipes"]["consumer"]["calibration_ledger_path"] = "/unverified/ledger.jsonl"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="qualification_consumer_recipe_invalid"):
        flow.read_recipes(context["settings"])
