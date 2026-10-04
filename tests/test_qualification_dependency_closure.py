"""Artificial files exercise real stage closure, warm cache and source hashing.

Only the existing qualification-program infrastructure boundary is sealed. No
statistic, financial core, cache, file verifier or source-hashing function is
replaced; these tests do not claim real F/500/PG executions or funding.
"""

from __future__ import annotations

import copy
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from quant_system.research import admission_activation as activation
from quant_system.research import admission_consumer_checks as checks
from quant_system.research import admission_v2 as admission
from quant_system.research import admission_window as window
from tests import test_admission_v2 as core
from tests.test_admission_window_activation import frozen, scope_for


def plain_dependencies(root):
    root.mkdir(parents=True)
    files = {}
    for kind in ("control", "semantic", "test", "execution"):
        path = root / (kind + ".json")
        path.write_text(json.dumps({"ARTIFICIAL_QUALIFIER_INFRASTRUCTURE_ONLY": kind}))
        files[kind] = {"path": str(path), "sha256": admission.file_sha(path)}
    details = {
        "current_control_rule": checks.CURRENT_CONTROL_RULE,
        "calibration": {"input_files": {files["control"]["path"]: files["control"]["sha256"]}},
        "semantic_calibration": {
            "status": "passed",
            "input_files": {files["semantic"]["path"]: files["semantic"]["sha256"]},
            "scope": "ARTIFICIAL dependency descriptor, no F execution",
        },
        "test_execution_evidence": {
            **files["execution"],
            "files": {files["test"]["path"]: files["test"]["sha256"]},
        },
    }
    return details, files


@pytest.fixture
def collected_stage(tmp_path, monkeypatch):
    original = frozen.__wrapped__(tmp_path, monkeypatch)
    settings = original[0]
    scope = scope_for(original)
    details, files = plain_dependencies(tmp_path / "ARTIFICIAL-stage-leaves")
    details["window_id"] = scope["window"]["window_id"]
    fresh = {"qualifications": {}}
    for kind in ("data", "review", "consumer"):
        path = tmp_path / (kind + "-registration.json")
        path.write_text(json.dumps({"ARTIFICIAL_REGISTRATION_DESCRIPTOR": kind}))
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
    base = activation._window_files(settings, scope, full=False)
    leaves, aliases = activation._qualified_window_files(settings, scope, fresh)
    return settings, scope, fresh, files, {"files": {**base, **leaves}, "file_aliases": aliases}


@pytest.mark.parametrize("change", ["modify", "remove"])
def test_actual_stage_closure_binds_semantic_files_and_checks_them_each_time(
    collected_stage, change
):
    settings, scope, fresh, files, review = collected_stage
    path = Path(files["semantic"]["path"])
    assert review["files"].get(str(path)) == files["semantic"]["sha256"]
    activation._verify_review_files(review)
    if change == "modify":
        path.write_text("ARTIFICIAL changed F leaf")
    else:
        path.unlink()
    with pytest.raises((OSError, ValueError)):
        activation._verify_review_files(review)
    with pytest.raises((OSError, ValueError)):
        activation._qualified_window_files(settings, scope, fresh)


@pytest.mark.parametrize("fault", ["missing", "empty", "failed"])
def test_current_stage_cannot_omit_or_downgrade_semantic_dependencies(collected_stage, fault):
    settings, scope, fresh, _, _ = collected_stage
    details = fresh["qualifications"]["consumer"]["registration"]["details"]
    if fault == "missing":
        details.pop("semantic_calibration")
    elif fault == "empty":
        details["semantic_calibration"]["input_files"] = {}
    else:
        details["semantic_calibration"]["status"] = "not_evaluated"
    with pytest.raises((OSError, ValueError)):
        activation._qualified_window_files(settings, scope, fresh)


@pytest.fixture
def warmed_qualification(tmp_path, monkeypatch):
    importlib.import_module("quant_system.research.admission_window")
    producer = core.sealed_producer.__wrapped__(monkeypatch)
    next(producer)
    admission._WARM_QUALIFICATIONS.clear()
    try:
        context = core.context.__wrapped__(tmp_path)
        details, files = plain_dependencies(tmp_path / "ARTIFICIAL-warm-leaves")
        module = sys.modules["quant_system.research.admission_qualifier"]
        original_verify = module.verify_registered_qualification
        calls = []

        def infrastructure(*args, **kwargs):
            calls.append(kwargs["kind"])
            result = original_verify(*args, **kwargs)
            if kwargs["kind"] == "consumer" and result["status"] == "passed":
                result["details"].update(copy.deepcopy(details))
            return result

        monkeypatch.setattr(module, "verify_registered_qualification", infrastructure)
        _, receipt = core.qualify(context)
        assert all(row["status"] == "passed" for row in receipt["qualifications"].values())
        args = (
            context["settings"],
            context["protocol"],
            receipt["source_binding"],
            receipt["qualification_refs"],
        )
        initial = admission._warm_qualifications(*args)
        assert initial == receipt["qualifications"]
        assert calls.count("consumer") > 0  # Actual cold path established the cache.
        before = len(calls)
        assert admission._qualifications(*args, allow_execution=False) == initial
        assert len(calls) == before
        yield args, files, calls, before
    finally:
        admission._WARM_QUALIFICATIONS.clear()
        producer.close()


@pytest.mark.parametrize("kind", ["semantic", "control", "test", "execution"])
@pytest.mark.parametrize("change", ["modify", "remove"])
def test_healthy_warm_cache_rechecks_each_leaf_without_rerunning_program(
    warmed_qualification, kind, change
):
    args, files, calls, cold_count = warmed_qualification
    path = Path(files[kind]["path"])
    if change == "modify":
        path.write_text("ARTIFICIAL changed dependency " + kind)
    else:
        path.unlink()
    with pytest.raises((OSError, ValueError)):
        admission._warm_qualifications(*args)
    with pytest.raises((OSError, ValueError)):
        admission._qualifications(*args, allow_execution=False)
    assert len(calls) == cold_count


def test_unchanged_dependency_files_keep_warm_check_read_only(warmed_qualification):
    args, files, calls, cold_count = warmed_qualification
    before = {row["path"]: Path(row["path"]).read_bytes() for row in files.values()}
    first = admission._warm_qualifications(*args)
    assert admission._warm_qualifications(*args) == first
    assert len(calls) == cold_count
    assert before == {row["path"]: Path(row["path"]).read_bytes() for row in files.values()}


def test_f_driver_bytes_belong_to_actual_central_and_window_source_identities(
    tmp_path, monkeypatch
):
    repository = Path(admission.__file__).parents[3]
    copied = tmp_path / "ARTIFICIAL-source-repository"
    shutil.copytree(
        repository / "src/quant_system",
        copied / "src/quant_system",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(
        repository / "scripts", copied / "scripts", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(
        repository / "docker/d34",
        copied / "docker/d34",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    monkeypatch.setattr(admission, "_ROOT", copied / "src/quant_system")
    monkeypatch.setattr(window, "ROOT", copied)
    before = admission.code_identity()
    window_before = window._producer_sources()
    driver = copied / "scripts/calibrate_admission_semantics.py"
    first_sha = admission.file_sha(driver)
    assert any(
        path.endswith("scripts/calibrate_admission_semantics.py") and digest == first_sha
        for path, digest in before["files"].items()
    )
    assert window_before["scripts/calibrate_admission_semantics.py"] == first_sha
    driver.write_text(driver.read_text() + "\n# ARTIFICIAL file-byte drift, never executed\n")
    after = admission.code_identity()
    window_after = window._producer_sources()
    assert before["digest"] != after["digest"]
    assert window_before != window_after
    assert window_after["scripts/calibrate_admission_semantics.py"] == admission.file_sha(driver)
