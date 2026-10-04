"""Artificial owner inputs and explicitly sealed expensive qualification programs.

No market data, real calibration, production owner or money is used here.
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from quant_system.research import admission_activation as activation
from quant_system.research import admission_v2 as admission
from quant_system.research import admission_window as window
from tests.test_admission_auto_window_flow import auto_recipes
from tests.test_admission_window import artificial_source


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    from quant_system.research import admission_consumer_checks as consumer

    # Only the historical ledger capability is sealed, not window verification.
    monkeypatch.setattr(consumer, "LEDGER_SHA", hashlib.sha256(b"sealed-test-ledger\n").hexdigest())
    settings, validation, job_path = artificial_source.__wrapped__(tmp_path)
    recipe_path, recipe = auto_recipes(settings)
    identity = window.window_identity(settings, validation)
    output = Path(recipe["recipes"]["data"]["source_root"]) / identity["window_id"] / "input"
    value = window.freeze_window(settings, validation_path=validation, output=output)
    return settings, validation, job_path, recipe_path, value


def test_explicit_verified_auto_window_has_a_bounded_scope(frozen):
    settings, validation, _, _, value = frozen
    scope = activation._owner_scope(
        settings,
        window_manifest=value["manifest_path"],
        window_manifest_sha256=value["manifest_sha256"],
    )
    original = json.loads(validation.read_text())
    assert scope["window"]["window_id"] == value["window_id"]
    assert scope["window"]["prices_sha256"] == original["evaluation"]["prices_sha256"]
    assert scope["window"]["calendar_digest"] == original["evaluation_calendar_digest"]
    assert scope["window"]["code_digest"] == admission.code_identity()["digest"]
    assert scope["future_inputs_qualified"] is False
    assert admission.AUTHORITATIVE_ENABLED is False


def scope_for(frozen):
    settings, _, _, _, value = frozen
    return activation._owner_scope(
        settings,
        window_manifest=value["manifest_path"],
        window_manifest_sha256=value["manifest_sha256"],
    )


def binding_for(scope):
    return {
        "schema": activation.SCHEMA,
        "state_digest": "a" * 64,
        "stage_sha256": "b" * 64,
        "code_digest": admission.code_identity()["digest"],
        "supported_scope": scope,
    }


@pytest.mark.parametrize("changed", ["missing", "prices", "calendar", "context"])
def test_actual_input_cannot_borrow_scope_on_same_date(frozen, changed):
    scope = scope_for(frozen)
    context = copy.deepcopy(scope["context"])
    source = {k: scope["window"][k] for k in ("prices_sha256", "calendar_digest")}
    if changed == "missing":
        source = None
    elif changed == "context":
        context["top_n"] = 4
    else:
        source["prices_sha256" if changed == "prices" else "calendar_digest"] = "0" * 64
    with pytest.raises(
        ValueError, match="activation_(window_input_mismatch|input_outside_frozen_scope)"
    ):
        activation.require_context(binding_for(scope), context, source_binding=source)


@pytest.mark.parametrize("changed", ["missing", "sha", "owner", "enabled"])
def test_scope_requires_current_owner_recipe_and_real_manifest(frozen, tmp_path, changed):
    settings, _, _, recipe_path, value = frozen
    args = {
        "window_manifest": value["manifest_path"],
        "window_manifest_sha256": value["manifest_sha256"],
    }
    if changed == "missing":
        args = {}
    elif changed == "sha":
        args["window_manifest_sha256"] = "0" * 64
    elif changed == "owner":
        from types import SimpleNamespace

        other = tmp_path / "other"
        other.mkdir()
        settings = SimpleNamespace(data=SimpleNamespace(data_dir=other))
        auto_recipes(settings)
    else:
        recipe = json.loads(recipe_path.read_text())
        recipe["enabled"] = False
        recipe_path.write_text(json.dumps(recipe))
    with pytest.raises(ValueError):
        activation._owner_scope(settings, **args)


@pytest.fixture
def qualified_phase(frozen, monkeypatch):
    """Seal only costly qualifier/gate programs; real input, stage, files and CAS run.

    These artificial fixed-program outputs make no claim that a market
    population or PostgreSQL test suite passed. Production uses real producers.
    """
    from quant_system.research import admission_qualification_flow as flow
    from quant_system.research.admission_qualifier import inspect_data_binding

    settings, validation, job_path, _, value = frozen
    owner = settings.data.data_dir
    (owner / "trials").mkdir()
    (owner / "trials/trials.jsonl").write_text("")
    saved = validation.parent / "admission-v2-artificial.json"
    saved.write_text(json.dumps({"fixture": "ARTIFICIAL SAVED GATE ONLY"}))
    job = json.loads(job_path.read_text())
    job.update(
        status="failed",
        results=[
            {
                "variant": "formula",
                "validation_sha256": admission.file_sha(validation),
                "admission_v2": {"path": str(saved)},
            }
        ],
    )
    job_path.write_text(json.dumps(job))
    history = owner / "history.json"
    history.write_text(json.dumps({"validation_references": []}))
    monkeypatch.setattr(activation, "HISTORY_SHA", admission.file_sha(history))
    control = Path(value["manifest_path"]).parent.parent / "controls"
    control.mkdir()
    control_file = control / "artificial-engine-check.json"
    control_file.write_text('{"fixture":"NO MARKET CALIBRATION"}')
    pg_file = control / "artificial-pg-check.json"
    pg_file.write_text('{"fixture":"NO DATABASE EXECUTION"}')
    pg_envelope = control / "artificial-pg-envelope.json"
    pg_envelope.write_text('{"fixture":"SEALED EXECUTION ENVELOPE"}')
    descriptors = {}
    for kind in ("data", "review", "consumer"):
        path = control / (kind + "-registration.json")
        path.write_text(json.dumps({"fixture": "SEALED TEST PROGRAM", "kind": kind}))
        descriptors[kind] = {"path": str(path), "sha256": admission.file_sha(path)}
    scope = scope_for(frozen)
    details = {
        "data": {
            "provenance": {
                "manifest_sha256": value["manifest_sha256"],
                "window_id": value["window_id"],
                "prices_sha256": scope["window"]["prices_sha256"],
            }
        },
        "review": {},
        "consumer": {
            "window_id": value["window_id"],
            "control_version": window.CONTROL_VERSION,
            "calibration_digest": "c" * 64,
            "historical_control_population": {},
            "calibration": {"input_files": {str(control_file): admission.file_sha(control_file)}},
            "test_execution_evidence": {
                "files": {str(pg_file): admission.file_sha(pg_file)},
                "path": str(pg_envelope),
                "sha256": admission.file_sha(pg_envelope),
            },
        },
    }
    calls = []

    def evaluate(settings, **kwargs):
        calls.append(kwargs["validation_path"])
        facts = inspect_data_binding(settings, kwargs["validation_path"])
        return {
            "status": "recorded",
            "validated_tier": "T0",
            "source_binding": facts["binding"],
            "qualifications": {
                kind: {
                    "status": "passed",
                    "descriptor": descriptors[kind],
                    "registration": {"details": copy.deepcopy(details[kind])},
                }
                for kind in descriptors
            },
            "gate": {
                "family": {"trusted": True, "family_digest": "f" * 64, "n_trials": 0},
                "dsr": {"path": "data_driven", "reason": None},
                "concentration": {"raw_unavailable_sleeves": []},
            },
            "residual_calibration": {"status": "not_applicable"},
        }

    monkeypatch.setattr(flow, "ensure_qualifications", lambda *a, **k: {"status": "registered"})
    monkeypatch.setattr(admission, "evaluate_validation", evaluate)
    monkeypatch.setattr(
        admission,
        "read_bound_receipt",
        lambda *a, **k: {"gate": {"tier_recommendation": {"tier": "T0"}}},
    )
    activation._WARM.clear()
    yield {
        "frozen": frozen,
        "settings": settings,
        "scope": scope,
        "history": history,
        "control_file": control_file,
        "pg_envelope": pg_envelope,
        "calls": calls,
        "details": details,
        "descriptors": descriptors,
    }
    activation._WARM.clear()


def activate_phase(phase):
    value = phase["frozen"][-1]
    return activation.review_and_activate(
        phase["settings"],
        historical_inventory=phase["history"],
        window_manifest=value["manifest_path"],
        window_manifest_sha256=value["manifest_sha256"],
    )


def protocol_and_input(phase):
    binding = activation.protocol_binding(phase["settings"])
    protocol = admission.freeze_protocol(
        "intake-" + "b" * 24, "d" * 64, mode="authoritative", activation=binding
    )
    source = {k: phase["scope"]["window"][k] for k in ("prices_sha256", "calendar_digest")}
    return protocol, source


def test_t0_stage_can_close_without_warming_or_authorizing_funds(qualified_phase):
    p = qualified_phase
    result = activate_phase(p)
    assert result["status"] == "activated", result
    assert result["capital_authorized"] is False
    assert result["review"]["rows"][0]["current_qualified_tier"] == "T0"
    assert admission.authority_configured(p["settings"]) is False
    protocol, source = protocol_and_input(p)
    with pytest.raises(ValueError, match="preflight_required"):
        activation.verify_for_funding(
            p["settings"],
            protocol,
            p["scope"]["context"],
            source_binding=source,
            allow_execution=False,
        )


def test_same_window_plans_bind_but_other_window_stays_parallel_without_pandas(
    qualified_phase, monkeypatch
):
    p = qualified_phase
    assert activate_phase(p)["status"] == "activated"
    plans = json.loads(p["frozen"][2].read_text())["plans"]
    plans[0]["origin"].update(start="2018-01-01", end="2026-09-25")
    monkeypatch.setattr(
        window, "read_window", lambda *a, **k: pytest.fail("full window in routing")
    )
    assert activation.protocol_binding(p["settings"], plans=plans) is not None
    plans[0]["origin"]["end"] = "2026-09-28"
    assert activation.protocol_binding(p["settings"], plans=plans) is None
    plans[0]["origin"]["end"] = "2026-09-25"
    plans[0]["payload"]["selection"] = "bottom"
    assert activation.protocol_binding(p["settings"], plans=plans) is None


def test_warm_preflight_checks_all_control_files_without_reexecuting(qualified_phase, monkeypatch):
    p = qualified_phase
    assert activate_phase(p)["status"] == "activated"
    protocol, source = protocol_and_input(p)
    activation.verify_for_funding(
        p["settings"], protocol, p["scope"]["context"], source_binding=source, allow_execution=True
    )
    before = len(p["calls"])
    monkeypatch.setattr(
        window, "read_window", lambda *a, **k: pytest.fail("full window in funds lock")
    )
    activation.verify_for_funding(
        p["settings"], protocol, p["scope"]["context"], source_binding=source, allow_execution=False
    )
    assert len(p["calls"]) == before
    p["control_file"].write_text("changed control bytes")
    with pytest.raises(ValueError, match="activation_stage_inputs_changed"):
        activation.verify_for_funding(
            p["settings"],
            protocol,
            p["scope"]["context"],
            source_binding=source,
            allow_execution=False,
        )


def test_window_qualifier_mismatch_blocks_stage(qualified_phase):
    p = qualified_phase
    p["details"]["consumer"]["window_id"] = "futu24-window-" + "a" * 64
    result = activate_phase(p)
    assert result["status"] == "blocked"
    assert result["reasons"] == ["activation_window_qualification_mismatch"]
    assert not (activation._root(p["settings"]) / "activation.json").exists()


def test_existing_stage_cannot_silently_rotate_and_identical_retry_is_immutable(qualified_phase):
    p = qualified_phase
    first = activate_phase(p)
    assert first["status"] == "activated"
    path = activation._root(p["settings"]) / "activation.json"
    before = path.read_bytes()
    same = activate_phase(p)
    assert same["state_digest"] == first["state_digest"]
    assert path.read_bytes() == before
    # A distinct seed manifest reference is a distinct frozen stage, even when
    # its price/context identity is identical. No silent authority replacement.
    import shutil

    original = Path(p["frozen"][-1]["manifest_path"])
    other = original.parent.with_name("input-attempt-0002")
    shutil.copytree(original.parent, other)
    changed = activation.review_and_activate(
        p["settings"],
        historical_inventory=p["history"],
        window_manifest=other / original.name,
        window_manifest_sha256=admission.file_sha(other / original.name),
    )
    assert changed["status"] == "blocked"
    assert changed["reasons"] == ["activation_existing_window_change_forbidden"]
    assert path.read_bytes() == before


def test_review_only_has_no_activation_or_funding_authority(qualified_phase):
    p = qualified_phase
    value = p["frozen"][-1]
    result = activation.review_and_activate(
        p["settings"],
        historical_inventory=p["history"],
        activate=False,
        window_manifest=value["manifest_path"],
        window_manifest_sha256=value["manifest_sha256"],
    )
    assert result["status"] == "ready"
    assert Path(result["stage"]["path"]).is_file()
    assert activation.protocol_binding(p["settings"]) is None
    assert result["capital_authorized"] is False


def test_unknown_parallel_job_cannot_be_excluded_to_close_stage(qualified_phase):
    p = qualified_phase
    job_path = p["frozen"][2]
    job = json.loads(job_path.read_text())
    job["status"] = "running"
    job_path.write_text(json.dumps(job))
    result = activate_phase(p)
    assert result["status"] == "blocked"
    assert result["reasons"] == ["activation_stage_scope_unknown"]
    assert not (activation._root(p["settings"]) / "activation.json").exists()


def test_changed_window_audit_between_review_and_publish_is_rejected(qualified_phase, monkeypatch):
    p = qualified_phase
    evaluate = admission.evaluate_validation
    audit = Path(p["frozen"][-1]["manifest_path"]).with_name("source-audit.json")

    def change(settings, **kwargs):
        result = evaluate(settings, **kwargs)
        audit.write_text(audit.read_text() + "\n")
        return result

    monkeypatch.setattr(admission, "evaluate_validation", change)
    result = activate_phase(p)
    assert result["status"] == "blocked"
    assert result["reasons"] == ["activation_stage_inputs_changed"]
    assert not (activation._root(p["settings"]) / "activation.json").exists()


def test_resigned_stage_cannot_omit_control_files_from_cold_proof(qualified_phase):
    p = qualified_phase
    assert activate_phase(p)["status"] == "activated"
    state_path = activation._root(p["settings"]) / "activation.json"
    state = json.loads(state_path.read_text())
    stage_path = Path(state["stage"]["path"])
    stage = json.loads(stage_path.read_text())
    del stage["review"]["files"][str(p["control_file"])]
    stage = activation._seal({k: v for k, v in stage.items() if k != "digest"})
    stage_path.write_text(json.dumps(stage))
    state["stage"]["sha256"] = admission.file_sha(stage_path)
    state = activation._seal({k: v for k, v in state.items() if k != "digest"})
    state_path.write_text(json.dumps(state))
    protocol, source = protocol_and_input(p)
    with pytest.raises(ValueError, match="activation_stage_file_manifest_mismatch"):
        activation.verify_for_funding(
            p["settings"],
            protocol,
            p["scope"]["context"],
            source_binding=source,
            allow_execution=True,
        )


def test_consumer_execution_envelope_is_part_of_warm_file_closure(qualified_phase):
    p = qualified_phase
    assert activate_phase(p)["status"] == "activated"
    protocol, source = protocol_and_input(p)
    activation.verify_for_funding(
        p["settings"], protocol, p["scope"]["context"], source_binding=source, allow_execution=True
    )
    p["pg_envelope"].write_text("changed outer execution receipt")
    with pytest.raises(ValueError, match="activation_stage_inputs_changed"):
        activation.verify_for_funding(
            p["settings"],
            protocol,
            p["scope"]["context"],
            source_binding=source,
            allow_execution=False,
        )


@pytest.fixture
def historical_alias_phase(qualified_phase, tmp_path, monkeypatch):
    """Real historical snapshot layout, with artificial archive bytes and sealed ledger pin."""
    from quant_system.research.admission_consumer_checks import LEDGER_SHA

    p = qualified_phase
    source = tmp_path / "original-archives"
    source.mkdir()
    target = source / "platform-result.json"
    target.write_text('{"fixture":"ARTIFICIAL HISTORICAL ARCHIVE"}')
    snapshot = tmp_path / "historical-family-snapshot"
    alias = snapshot / "strategy_library/artificial/validations/old/platform-result.json"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(target)
    provenance = snapshot / "snapshot-provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "schema": "fixed_family_source_aliases/v1",
                "original_ledger_sha256": LEDGER_SHA,
                "files": {
                    str(alias.relative_to(snapshot)): {
                        "original_path": str(target),
                        "sha256": admission.file_sha(target),
                    }
                },
            }
        )
    )
    # Seal the immutable historical document identity to this artificial file;
    # no mutation test updates this expected pin after changing the document.
    monkeypatch.setattr(
        activation,
        "_HISTORICAL_ALIAS_PROVENANCE_SHA",
        admission.file_sha(provenance),
        raising=False,
    )
    recipe_path = p["frozen"][3]
    recipe = json.loads(recipe_path.read_text())
    recipe["recipes"]["consumer"]["data_root"] = str(snapshot)
    recipe_path.write_text(json.dumps(recipe))
    descriptor = p["descriptors"]["consumer"]
    path = Path(descriptor["path"])
    registration = json.loads(path.read_text())
    registration["evidence"] = {"data_root": str(snapshot)}
    path.write_text(json.dumps(registration))
    descriptor["sha256"] = admission.file_sha(path)
    p["details"]["consumer"]["calibration"]["input_files"][str(alias)] = admission.file_sha(target)
    p["details"]["consumer"]["historical_control_population"]["original_ledger_sha256"] = LEDGER_SHA
    p.update(alias=alias, alias_target=target, alias_provenance=provenance, alias_snapshot=snapshot)
    return p


def test_verified_historical_snapshot_aliases_are_bound_not_discarded(historical_alias_phase):
    p = historical_alias_phase
    result = activate_phase(p)
    assert result["status"] == "activated", result["reasons"]
    reviewed = result["review"]
    assert all(
        str(path) in reviewed["files"]
        for path in (p["alias"], p["alias_target"], p["alias_provenance"])
    )
    relation = reviewed["file_aliases"][str(p["alias"])]
    assert relation["target_path"] == str(p["alias_target"])
    assert relation["link_text"] == str(p["alias_target"])
    assert relation["sha256"] == admission.file_sha(p["alias_target"])


@pytest.mark.parametrize(
    "change",
    [
        "missing_provenance",
        "ledger",
        "provenance_target",
        "provenance_sha",
        "extra_alias",
        "target_bytes",
        "same_bytes_redirect",
        "parent_symlink",
    ],
)
def test_unbound_or_changed_historical_aliases_never_close_stage(historical_alias_phase, change):
    p = historical_alias_phase
    provenance = p["alias_provenance"]
    value = json.loads(provenance.read_text())
    relative = next(iter(value["files"]))
    if change == "missing_provenance":
        provenance.unlink()
    elif change == "ledger":
        value["original_ledger_sha256"] = "0" * 64
        provenance.write_text(json.dumps(value))
    elif change in {"provenance_target", "same_bytes_redirect"}:
        other = p["alias_target"].with_name("same-content-copy.json")
        other.write_bytes(p["alias_target"].read_bytes())
        if change == "provenance_target":
            value["files"][relative]["original_path"] = str(other)
            provenance.write_text(json.dumps(value))
        else:
            p["alias"].unlink()
            p["alias"].symlink_to(other)
    elif change == "provenance_sha":
        value["files"][relative]["sha256"] = "0" * 64
        provenance.write_text(json.dumps(value))
    elif change == "extra_alias":
        value["files"]["unverified-extra.json"] = dict(value["files"][relative])
        provenance.write_text(json.dumps(value))
    elif change == "target_bytes":
        p["alias_target"].write_text("changed original archive bytes")
    else:
        parent = p["alias"].parent
        moved = parent.with_name("moved-parent")
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
    result = activate_phase(p)
    assert result["status"] == "blocked"
    assert not (activation._root(p["settings"]) / "activation.json").exists()


@pytest.mark.parametrize("change", ["retarget_same_bytes", "target_bytes", "provenance_bytes"])
def test_alias_relation_and_both_bytes_remain_bound_after_warming(historical_alias_phase, change):
    p = historical_alias_phase
    assert activate_phase(p)["status"] == "activated"
    protocol, source = protocol_and_input(p)
    activation.verify_for_funding(
        p["settings"], protocol, p["scope"]["context"], source_binding=source, allow_execution=True
    )
    if change == "retarget_same_bytes":
        target = p["alias_target"].with_name("identical-copy.json")
        target.write_bytes(p["alias_target"].read_bytes())
        p["alias"].unlink()
        p["alias"].symlink_to(target)
        expected = "activation_stage_alias_changed"
    elif change == "target_bytes":
        p["alias_target"].write_text("changed content")
        expected = "activation_stage_inputs_changed"
    else:
        p["alias_provenance"].write_text(p["alias_provenance"].read_text() + "\n")
        expected = "activation_stage_inputs_changed"
    with pytest.raises(ValueError, match=expected):
        activation.verify_for_funding(
            p["settings"],
            protocol,
            p["scope"]["context"],
            source_binding=source,
            allow_execution=False,
        )


def test_alias_retarget_between_review_and_publish_is_rejected(historical_alias_phase, monkeypatch):
    p = historical_alias_phase
    close = activation._current_population

    def change(settings):
        result = close(settings)
        target = p["alias_target"].with_name("same-bytes-after-review.json")
        target.write_bytes(p["alias_target"].read_bytes())
        p["alias"].unlink()
        p["alias"].symlink_to(target)
        return result

    monkeypatch.setattr(activation, "_current_population", change)
    result = activate_phase(p)
    assert result["status"] == "blocked"
    assert result["reasons"] == ["activation_stage_alias_changed"]
    assert not (activation._root(p["settings"]) / "activation.json").exists()


def test_non_calibration_symlinks_stay_forbidden(qualified_phase):
    p = qualified_phase
    descriptor = p["descriptors"]["review"]
    path = Path(descriptor["path"])
    target = path.with_name("review-copy.json")
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    result = activate_phase(p)
    assert result["status"] == "blocked"
    assert result["reasons"] == ["activation_window_file_invalid"]


def test_coherent_alias_and_provenance_redirect_cannot_redefine_original_target(
    historical_alias_phase,
):
    p = historical_alias_phase
    other = p["alias_target"].with_name("same-bytes-new-claimed-original.json")
    other.write_bytes(p["alias_target"].read_bytes())
    p["alias"].unlink()
    p["alias"].symlink_to(other)
    provenance = json.loads(p["alias_provenance"].read_text())
    relative = next(iter(provenance["files"]))
    provenance["files"][relative]["original_path"] = str(other)
    p["alias_provenance"].write_text(json.dumps(provenance))
    result = activate_phase(p)
    assert result["status"] == "blocked"
    assert result["reasons"] == ["activation_calibration_alias_provenance_changed"]
    assert not (activation._root(p["settings"]) / "activation.json").exists()
