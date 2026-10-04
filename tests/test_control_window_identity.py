"""Metadata transport seams and real stage collectors, with artificial files.

No control, engine, PG, qualification or stage is executed. The helper is the
same seam used by the production control summary and consumer summary builders.
"""

import copy
import json
from pathlib import Path

import pytest

from quant_system.research import admission_activation as activation
from quant_system.research import admission_consumer_checks as checks
from quant_system.research import admission_v2 as admission
from tests.test_admission_window_activation import frozen, scope_for
from tests.test_qualification_dependency_closure import plain_dependencies

AUTO = "futu24-auto-window-v1"


@pytest.fixture
def metadata_flow(tmp_path, monkeypatch):
    original = frozen.__wrapped__(tmp_path, monkeypatch)
    settings, scope = original[0], scope_for(original)
    details, _ = plain_dependencies(tmp_path / "ARTIFICIAL-window-metadata-leaves")
    # Artificial output shape of the already-verified control spec. No engine
    # verification claim is made by constructing this metadata test specimen.
    spec = {"window_id": scope["window"]["window_id"], "control_version": AUTO}
    producer_summary = {
        "schema": "current_common_quality_control/v1",
        "control_version": AUTO,
        "input_files": details["calibration"]["input_files"],
        **checks._control_window_identity(spec, AUTO),
    }
    details["calibration"] = producer_summary
    details.update(checks._control_window_identity(producer_summary, AUTO))
    fresh = {"qualifications": {}}
    for kind in ("data", "review", "consumer"):
        path = tmp_path / (kind + "-metadata-registration.json")
        path.write_text(json.dumps({"ARTIFICIAL_ONLY": kind}))
        fresh["qualifications"][kind] = {
            "descriptor": {"path": str(path), "sha256": admission.file_sha(path)},
            "registration": {"details": {}},
        }
    ref = scope["window"]
    fresh["qualifications"]["data"]["registration"]["details"] = {
        "provenance": {
            "manifest_sha256": ref["manifest"]["sha256"],
            "window_id": ref["window_id"],
            "prices_sha256": ref["prices_sha256"],
        }
    }
    fresh["qualifications"]["consumer"]["registration"]["details"] = details
    return settings, scope, spec, producer_summary, fresh


def test_verified_control_identity_reaches_consumer_and_actual_stage_collector(metadata_flow):
    settings, scope, spec, summary, fresh = metadata_flow
    consumer = fresh["qualifications"]["consumer"]["registration"]["details"]
    assert consumer["window_id"] == summary["window_id"] == spec["window_id"]
    files, aliases = activation._qualified_window_files(settings, scope, fresh)
    assert files and not aliases
    activation._verify_review_files({"files": files, "file_aliases": aliases})
    assert all(Path(path).is_file() for path in files)


@pytest.mark.parametrize("layer", ["producer_summary", "consumer_summary"])
@pytest.mark.parametrize("value", [None, "", False, 0])
def test_auto_identity_missing_in_either_transport_layer_never_borrows_data(layer, value):
    if layer == "producer_summary":
        verified_record = {"window_id": value}
    else:
        verified_record = checks._control_window_identity(
            {"window_id": "futu24-window-" + "b" * 64}, AUTO
        )
        # A serialization/transport loss after producing the summary must not
        # be repaired from a data qualification with another identity.
        verified_record["window_id"] = value
    verified_record["data_window_id"] = "futu24-window-" + "a" * 64
    with pytest.raises(ValueError, match="current_control_window_identity_missing"):
        checks._control_window_identity(verified_record, AUTO)


@pytest.mark.parametrize("layer", ["data", "control_spec", "consumer"])
def test_real_stage_rejects_mismatched_window_at_each_boundary(metadata_flow, layer):
    settings, scope, spec, summary, fresh = metadata_flow
    value = copy.deepcopy(fresh)
    consumer = value["qualifications"]["consumer"]["registration"]["details"]
    wrong = "futu24-window-" + "f" * 64
    if layer == "data":
        value["qualifications"]["data"]["registration"]["details"]["provenance"]["window_id"] = (
            wrong
        )
    elif layer == "control_spec":
        changed_spec = {**spec, "window_id": wrong}
        changed_summary = {**summary, **checks._control_window_identity(changed_spec, AUTO)}
        consumer["calibration"] = changed_summary
        consumer.update(checks._control_window_identity(changed_summary, AUTO))
    else:
        consumer["window_id"] = wrong
    with pytest.raises(ValueError, match="activation_window_qualification_mismatch"):
        activation._qualified_window_files(settings, scope, value)


def test_historical_static_summary_has_no_invented_window_identity():
    old_spec = {"context": {"start": "2018-01-02", "end": "2026-09-08"}}
    version = "futu24-original-20260920"
    summary = {"control_version": version, **checks._control_window_identity(old_spec, version)}
    consumer = {**checks._control_window_identity(summary, version)}
    assert "window_id" not in summary and "window_id" not in consumer
