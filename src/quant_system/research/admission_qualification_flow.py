"""Idempotent owner-configured qualification production, never funding authority.

The owner file selects only fixed verifier input recipes, not commands or checks.
The model proposal cannot configure this flow. An attempt cache can suppress
repeated work but can never authenticate a pass: admission still invokes the
fixed registered verifier. Failed attempts are retained under immutable keys.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from quant_system.research.evaluation_service import _hash

SCHEMA = "admission_qualification_recipes/v1"
RETRY_DELAYS_SECONDS = (30, 120, 600, 1800)


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _sha(path):
    from quant_system.research.admission_v2 import file_sha

    path = Path(path)
    return file_sha(path) if path.is_file() else None


def _root(settings):
    owner = Path(settings.data.data_dir).resolve()
    root = owner / "research_intake/admission_v2"
    _require(
        not root.is_symlink() and root.resolve().is_relative_to(owner),
        "qualification_flow_root_invalid",
    )
    return root


def read_recipes(settings):
    path = _root(settings) / "recipes.json"
    if not path.exists():
        return None
    _require(
        not path.is_symlink()
        and path.stat().st_uid == os.getuid()
        and path.stat().st_mode & 0o077 == 0,
        "qualification_recipes_owner_invalid",
    )
    value = json.loads(path.read_text())
    _require(
        isinstance(value, dict)
        and set(value) == {"schema", "enabled", "revision", "recipes"}
        and value["schema"] == SCHEMA
        and type(value["enabled"]) is bool
        and isinstance(value["revision"], str)
        and value["revision"],
        "qualification_recipes_schema_invalid",
    )
    recipes = value["recipes"]
    _require(
        isinstance(recipes, dict) and set(recipes) == {"review", "data", "consumer"},
        "qualification_recipes_schema_invalid",
    )
    _require(
        all(isinstance(recipe, dict) for recipe in recipes.values()),
        "qualification_recipes_schema_invalid",
    )
    _require(
        set(recipes["data"]) == {"dataset", "source_root"}, "qualification_data_recipe_invalid"
    )
    _require(set(recipes["review"]) == {"root"}, "qualification_review_recipe_invalid")
    _require(
        set(recipes["consumer"])
        <= {"random_root", "data_root", "peer_snapshot_path", "control_version",
            "calibration_ledger_path", "current_control_rule", "semantic_calibration"}
        and {"random_root", "data_root", "peer_snapshot_path"} <= set(recipes["consumer"]),
        "qualification_consumer_recipe_invalid",
    )
    _validate_window_recipe(settings, value)
    return value


def _validate_window_recipe(settings, configuration):
    """Only an owner recipe may select the fixed dynamic producer namespace."""
    from quant_system.research.admission_window import DATASET

    data, consumer = (configuration["recipes"][key] for key in ("data", "consumer"))
    if data["dataset"] != DATASET and consumer.get("control_version") != DATASET:
        _require("calibration_ledger_path" not in consumer, "qualification_consumer_recipe_invalid")
        return False
    namespace = _root(settings) / "windows"
    source = Path(data["source_root"]).absolute()
    random = Path(consumer["random_root"]).absolute()
    _require(
        data["dataset"] == consumer.get("control_version") == DATASET
        and source == random
        and source.resolve().is_relative_to(namespace.resolve())
        and not any(p.is_symlink() for p in (source, *source.parents)),
        "qualification_window_recipe_invalid",
    )
    _calibration_ledger(consumer)
    return True


def _calibration_ledger(consumer):
    """Bind the frozen calibration population independently of the archive root."""
    from quant_system.research.admission_consumer_checks import LEDGER_SHA

    value = consumer.get("calibration_ledger_path")
    _require(isinstance(value, str) and bool(value),
             "qualification_window_calibration_ledger_invalid")
    path = Path(value)
    _require(
        path.is_absolute() and path.is_file()
        and not any(p.is_symlink() for p in (path, *path.parents))
        and _sha(path) == LEDGER_SHA,
        "qualification_window_calibration_ledger_invalid",
    )
    return path


def _window_input(settings, validation_path, configuration):
    from quant_system.research.admission_window import (
        freeze_window,
        read_window,
        window_identity,
    )
    from quant_system.research.external_intake import _lock, _private_directory

    identity = window_identity(settings, validation_path)
    namespace = Path(configuration["recipes"]["data"]["source_root"])
    root = namespace / identity["window_id"]
    _private_directory(root)
    with _lock(root / "production.lock", nonblocking=True):
        directory = _window_slot(root, "input", "input-manifest.json")
        manifest = directory / "input-manifest.json"
        if directory.exists():
            _require(manifest.is_file(), "qualification_window_input_incomplete")
            expected_sha = _sha(manifest)
            _, value = read_window(manifest, expected_sha)
            _require(
                value["window_id"] == identity["window_id"], "qualification_window_key_changed"
            )
            _window_completed(root, "input", manifest)
            return {**identity, "manifest_path": str(manifest),
                    "manifest_sha256": expected_sha, "root": str(root)}
        value = freeze_window(settings, validation_path=validation_path, output=directory)
        _require(value["window_id"] == identity["window_id"], "qualification_window_key_changed")
        _window_completed(root, "input", Path(value["manifest_path"]))
        return {**value, "root": str(root)}


def _window_slot(root, kind, completion_name):
    """Resume only our bound production checkpoint, retaining partial directories."""
    from quant_system.research.external_intake import _private_directory, _write

    checkpoint = root / f"{kind}-production.json"
    if checkpoint.exists():
        _require(not checkpoint.is_symlink(), "qualification_window_checkpoint_symlink")
        state = json.loads(checkpoint.read_text())
        _require(
            state.get("schema") == "qualification_window_production/v1"
            and state.get("kind") == kind
            and state.get("window_id") == root.name
            and type(state.get("attempt")) is int and state["attempt"] >= 1
            and state.get("phase") in {"started", "completed"}
            and state.get("digest") == _hash({k: v for k, v in state.items() if k != "digest"})
            and isinstance(state.get("directory"), str)
            and re.fullmatch(re.escape(kind) + r"(?:-attempt-[0-9]+)?", state["directory"]),
            "qualification_window_checkpoint_changed",
        )
        directory = root / state["directory"]
        _require(not directory.is_symlink(), "qualification_window_checkpoint_symlink")
        artifact = directory / completion_name
        if state["phase"] == "completed":
            _require(
                artifact.is_file() and _sha(artifact) == state.get("artifact_sha256"),
                "qualification_window_completed_artifact_changed",
            )
            return directory
        if artifact.is_file():
            return directory  # full verifier still runs before marking complete
        if not directory.exists():
            return directory
        archive = root / "production-history" / kind / f"{state['attempt']:04d}.json"
        _private_directory(archive.parent)
        if archive.exists():
            _require(json.loads(archive.read_text()) == state,
                     "qualification_window_checkpoint_history_changed")
        else:
            _write(archive, state)
        attempt = state["attempt"] + 1
        directory = root / f"{kind}-attempt-{attempt:04d}"
        _require(not directory.exists(), "qualification_window_recovery_directory_exists")
    else:
        directory, attempt = root / kind, 1
        _require(not directory.is_symlink(), "qualification_window_checkpoint_symlink")
        if directory.exists():
            _require((directory / completion_name).is_file(),
                     f"qualification_window_{kind}_incomplete")
    state = {
        "schema": "qualification_window_production/v1", "kind": kind,
        "window_id": root.name, "attempt": attempt, "directory": directory.name,
        "phase": "started",
    }
    _write(checkpoint, {**state, "digest": _hash(state)})
    return directory


def _window_completed(root, kind, artifact):
    from quant_system.research.external_intake import _write

    path = root / f"{kind}-production.json"
    state = json.loads(path.read_text())
    _require(artifact.parent.name == state["directory"], "qualification_window_checkpoint_changed")
    state.pop("digest")
    state.update(phase="completed", artifact_sha256=_sha(artifact))
    _write(path, {**state, "digest": _hash(state)})


def _window_controls(window, configuration):
    from quant_system.research.admission_window import produce_controls
    from quant_system.research.external_intake import _lock

    root = Path(window["root"])
    generated = 0
    with _lock(root / "production.lock", nonblocking=True):
        controls = _window_slot(root, "controls", "artifact-manifest.json")
        if controls.exists():
            _require(
                (controls / "summary.json").is_file(), "qualification_window_controls_incomplete"
            )
        else:
            family = _calibration_ledger(configuration["recipes"]["consumer"])
            summary = produce_controls(
                window["manifest_path"], window["manifest_sha256"], family, controls
            )
            generated = summary["n_variants"]
        _require((controls / "artifact-manifest.json").is_file(),
                 "qualification_window_controls_incomplete")
        _window_completed(root, "controls", controls / "artifact-manifest.json")
    # Existence or a summary is never a pass. The fixed consumer verifies the
    # full population, source closure and every engine result before registration.
    return {
        **{key: value for key, value in configuration["recipes"]["consumer"].items()
           if key != "calibration_ledger_path"},
        "random_root": str(controls),
        "window_manifest": window["manifest_path"],
        "window_manifest_sha256": window["manifest_sha256"],
    }, generated


def _input_key(settings, path, protocol, configuration):
    """Actual immutable inputs and financial-peer facts; not mutable worker timestamps."""
    from quant_system.execution.assistant_remote import load_book
    from quant_system.research.admission_v2 import code_identity
    from quant_system.research.external_intake import _job_path

    root = Path(settings.data.data_dir).resolve()
    path = Path(path).resolve()
    _require(
        path.is_relative_to(root / "strategy_library") and path.name == "validation.json",
        "qualification_validation_path_invalid",
    )
    run = path.parent
    names = (
        "validation.json",
        "platform-result.json",
        "prices.parquet",
        "qlib-replay.json",
        "signal-analysis.json",
    )
    files = {str(run / name): _sha(run / name) for name in names}
    files[str(run.parent.parent / "definition.json")] = _sha(run.parent.parent / "definition.json")
    job = json.loads(_job_path(settings, protocol["job_id"]).read_text())
    peers = [
        {
            key: row.get(key)
            for key in (
                "candidate_id",
                "sleeve_id",
                "definition_digest",
                "source_path",
                "source_digest",
                "comparison_digest",
                "verification_receipt_digest",
                "performance",
            )
        }
        for row in load_book(settings)["candidates"]
        if row.get("status") == "hung"
    ]
    for row in peers:
        if row["source_path"]:
            files[row["source_path"]] = _sha(row["source_path"])
    document = {
        "code_digest": code_identity()["digest"],
        "protocol": protocol,
        "configuration": configuration,
        "files": files,
        "job": {
            key: job.get(key) for key in ("proposal", "plans", "evaluation", "admission_protocol")
        },
        "baseline_receipts": [
            {key: row.get(key) for key in ("definition_digest", "validation_sha256")}
            for row in job.get("results", [])
            if row.get("variant") == "baseline"
        ],
        "ledger_sha256": _sha(root / "trials/trials.jsonl"),
        "peers": sorted(peers, key=lambda row: row["candidate_id"]),
    }
    return _hash(document), document["code_digest"]


def _publish(settings, input_digest, refs):
    from quant_system.research.external_intake import _lock, _write

    root = _root(settings)
    with _lock(root / "catalog.lock", nonblocking=True):
        path = root / "qualifications.json"
        if path.exists():
            _require(
                not path.is_symlink()
                and path.stat().st_uid == os.getuid()
                and path.stat().st_mode & 0o077 == 0,
                "qualification_catalog_owner_invalid",
            )
            value = json.loads(path.read_text())
            _require(
                value.get("schema") == "admission_qualification_index/v1"
                and isinstance(value.get("entries"), dict),
                "qualification_catalog_schema_invalid",
            )
        else:
            value = {"schema": "admission_qualification_index/v1", "entries": {}}
        value["entries"][input_digest] = refs
        _write(path, value)


def ensure_qualifications(settings, *, validation_path, protocol):
    """No financial locks; busy producers return a finite retry, never block a worker."""
    from quant_system.research.external_intake import _private_directory, _write

    try:
        return _ensure_qualifications(settings, validation_path=validation_path, protocol=protocol)
    except BlockingIOError:
        configuration = read_recipes(settings)
        identity, code_digest = _input_key(settings, validation_path, protocol, configuration)
        result = {
            "schema": "admission_qualification_attempt/v1",
            "attempt_id": identity,
            "code_digest": code_digest,
            "validation_path": str(Path(validation_path).resolve()),
            "status": "not_evaluated",
            "reason": "qualification_production_busy",
            "error_type": "BlockingIOError",
            "retryable": True,
            "next_retry_at": time.time() + RETRY_DELAYS_SECONDS[0],
            "cached": False,
            "capital_authorized": False,
            "backtests_run": 0,
            "new_trials": 0,
        }
        # Separate immutable trace: do not overwrite the active producer's memo.
        trace = _root(settings) / "attempts/busy" / identity
        _private_directory(trace)
        _write(trace / f"{time.time_ns()}.json", result)
        return result


def _recover_attempt_memo(path, identity):
    """History is committed first; reconstruct a lost/stale memo without new work."""
    from quant_system.research.external_intake import _write

    directory = path.parent / "history" / identity
    if not directory.exists():
        return
    archives = list(directory.iterdir())
    _require(
        not directory.is_symlink()
        and all(
            item.is_file()
            and not item.is_symlink()
            and item.suffix == ".json"
            and item.stem.isdecimal()
            for item in archives
        ),
        "qualification_attempt_history_invalid",
    )
    records = []
    for number, item in enumerate(sorted(archives, key=lambda p: int(p.stem)), start=1):
        value = json.loads(item.read_text())
        _require(
            item.name == f"{number:04d}.json"
            and value.get("attempt_id") == identity
            and value.get("attempt_number") == number
            and value.get("digest") == _hash({k: v for k, v in value.items() if k != "digest"}),
            "qualification_attempt_history_changed",
        )
        records.append(value)
    if not records:
        return
    memo = json.loads(path.read_text()) if path.exists() else None
    _require(memo is None or memo in records, "qualification_attempt_memo_history_mismatch")
    if memo != records[-1]:
        _write(path, records[-1])


def _ensure_qualifications(settings, *, validation_path, protocol):
    """Run once for exact code/input/owner recipe; safe only outside financial locks."""
    from quant_system.research.admission_v2 import verify_protocol
    from quant_system.research.external_intake import _lock, _private_directory, _write

    configuration = read_recipes(settings)
    if configuration is None or not configuration["enabled"]:
        return {
            "status": "not_configured",
            "reason": "qualification_recipes_not_enabled",
            "cached": False,
        }
    from quant_system.research.admission_qualifier import (
        inspect_data_binding,
        register_qualification,
    )

    identity, code_digest = _input_key(settings, validation_path, protocol, configuration)
    root = _root(settings)
    attempts = root / "attempts"
    _private_directory(attempts)
    path = attempts / (identity + ".json")
    with _lock(attempts / (identity + ".lock"), nonblocking=True):
        _recover_attempt_memo(path, identity)
        previous = None
        if path.exists():
            value = json.loads(path.read_text())
            _require(
                value.get("attempt_id") == identity
                and value.get("digest")
                == _hash({key: item for key, item in value.items() if key != "digest"}),
                "qualification_attempt_changed",
            )
            if not value.get("retryable") or time.time() < value.get("next_retry_at", 0):
                return {**value, "cached": True}
            previous = value
        number = int(previous.get("attempt_number", 1)) + 1 if previous else 1
        attempt = {
            "schema": "admission_qualification_attempt/v1",
            "attempt_id": identity,
            "code_digest": code_digest,
            "recipe_digest": _hash(configuration),
            "validation_path": str(Path(validation_path).resolve()),
            "input_digest": None,
            "status": "not_evaluated",
            "reason": None,
            "registrations": {},
            "capital_authorized": False,
            "backtests_run": 0,
            "new_trials": 0,
            "attempt_number": number,
            "retryable": False,
            "next_retry_at": None,
        }
        refs = {}
        try:
            verify_protocol(protocol)
            from quant_system.research.admission_consumer_checks import (
                CURRENT_CONTROL_RULE,
                collect_control_execution_trace,
                inspect_current_consumer_scope,
            )

            current_scope = inspect_current_consumer_scope(settings, validation_path)
            attempt["current_consumer_scope"] = current_scope
            _require(
                current_scope["status"] == "ready_for_verification",
                current_scope["reason"] or "current_consumer_scope_unavailable",
            )
            _require(
                configuration["recipes"]["consumer"].get("current_control_rule")
                == CURRENT_CONTROL_RULE,
                "current_control_contract_required",
            )
            facts = inspect_data_binding(settings, validation_path)
            attempt["input_digest"] = facts["input_digest"]
            window = None
            if _validate_window_recipe(settings, configuration):
                window = _window_input(settings, validation_path, configuration)
                attempt["window"] = window
                attempt["control_variants_generated"] = 0
                # Cold artifact verification also replays engines. Do not report
                # zero total runs or confuse these controls with alpha trials.
                attempt["backtests_run"] = None
                attempt["backtest_count_scope"] = "control_generation_and_audit_are_separate"
                attempt["new_trials_scope"] = "canonical_alpha_family_not_calibration_ledger"
            # Cheap input validity first. Unsupported input never runs a 500-control program.
            for kind in ("data", "review", "consumer"):
                evidence = dict(configuration["recipes"][kind])
                if kind == "data":
                    evidence["validation_path"] = str(Path(validation_path).resolve())
                    if window is not None:
                        evidence.update(
                            source_root=str(Path(window["manifest_path"]).parent),
                            window_manifest_sha256=window["manifest_sha256"],
                        )
                elif kind == "consumer" and window is not None:
                    evidence, count = _window_controls(window, configuration)
                    attempt["control_variants_generated"] = count
                if kind == "consumer":
                    evidence["validation_path"] = str(Path(validation_path).resolve())
                with collect_control_execution_trace() as control_work:
                    result = register_qualification(
                        settings,
                        kind=kind,
                        scope=protocol["scope"],
                        evidence=evidence,
                        input_digest=facts["input_digest"] if kind == "data" else None,
                    )
                if kind == "consumer":
                    attempt["consumer_engine_revalidation"] = control_work
                refs[kind] = result["descriptor"]
                attempt["registrations"][kind] = result
                if result["verification"]["status"] != "passed":
                    attempt["reason"] = (
                        result["verification"].get("reason") or "qualification_not_evaluated"
                    )
                    details = result["verification"].get("details") or {}
                    attempt["retryable"] = details.get("retryable") is True
                    attempt["error_type"] = details.get("error_type")
                    break
            else:
                attempt["status"] = "registered"
            # A producer's failed registration is evidence too, but never a pass.
            _require(
                _input_key(settings, validation_path, protocol, configuration)[0] == identity,
                "qualification_inputs_changed_during_production",
            )
            _require(
                read_recipes(settings) == configuration,
                "qualification_recipes_changed_during_production",
            )
            _publish(settings, facts["input_digest"], refs)
        except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
            attempt["status"] = "not_evaluated"
            attempt["reason"] = str(exc)
            attempt["retryable"] = isinstance(exc, OSError) and not isinstance(
                exc, FileNotFoundError
            )
            attempt["error_type"] = type(exc).__name__
        if attempt["status"] == "registered":
            attempt["retryable"] = False
        if attempt["retryable"]:
            attempt["next_retry_at"] = (
                time.time() + RETRY_DELAYS_SECONDS[min(number - 1, len(RETRY_DELAYS_SECONDS) - 1)]
            )
        attempt["digest"] = _hash(attempt)
        archive = attempts / "history" / identity / f"{number:04d}.json"
        _private_directory(archive.parent)
        _require(not archive.exists(), "qualification_attempt_history_exists")
        _write(archive, attempt)
        _write(path, attempt)
        return {**attempt, "cached": False}


def should_retry(settings, *, validation_path, protocol, previous):
    """Cheap queue readiness; an unchanged definite failure cannot starve newer jobs."""
    configuration = read_recipes(settings)
    if configuration is None or not configuration["enabled"]:
        return False
    identity, _ = _input_key(settings, validation_path, protocol, configuration)
    if identity != previous.get("attempt_id"):
        return True
    return previous.get("retryable") is True and time.time() >= (previous.get("next_retry_at") or 0)
