"""Finite source-bound activation of the audited static-24 intake protocol.

The state is a set of references, not a pass certificate. Funding additionally
requires this process to execute the fixed stage verification outside money
locks. Future datasets/windows are not qualified by this frozen experiment.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import time
from contextlib import ExitStack
from pathlib import Path

from quant_system.research.admission_qualifier import inspect_data_binding as _inspect_bound_input
from quant_system.research.evaluation_service import _hash

SCHEMA = "admission_activation/v1"
STAGE_SCHEMA = "admission_parallel_stage/v1"
HISTORY_SHA = "fdc7b24163d07b1219091651323130571b4a4e0bd3d2e492c5d076943bcb2e74"
# Original fixed-39 family alias manifest, already recorded in the immutable
# original-file inventories of both the 277a and b4ee real owner runs.
_HISTORICAL_ALIAS_PROVENANCE_SHA = (
    "3f1ace1d1796b8bff17f97d3c019b25509b52c0812f1603cdbde07ede71026df"
)
_WARM = {}
_WARM_SECONDS = 120
_AUTO_DATASET = "futu24-auto-window-v1"
_WINDOW_KEYS = {
    "window_id",
    "manifest",
    "prices_sha256",
    "calendar_digest",
    "code_digest",
    "owner_root",
    "method_digest",
    "producer_sources_digest",
    "requested_start",
    "requested_end",
}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _root(settings):
    from quant_system.research.admission_qualification_flow import _root as owner_root

    return owner_root(settings)


def _scope(dataset="futu24-current-20260920"):
    from quant_system.research.admission_consumer_checks import CONTROL_VERSIONS
    from quant_system.research.admission_v2 import SCOPE

    _require(
        dataset in {"futu24-current-20260920", "futu24-saved-intake-20260924"},
        "activation_dataset_scope_unsupported",
    )
    return {
        "scope": SCOPE,
        "dataset": dataset,
        "context": copy.deepcopy(CONTROL_VERSIONS[dataset]["context"]),
        "historical_pit_verified": False,
        "future_inputs_qualified": False,
    }


def _is_auto(scope):
    return isinstance(scope, dict) and scope.get("dataset") == _AUTO_DATASET


def _regular_file(path, *, root=None):
    path = Path(path)
    _require(
        path.is_absolute()
        and path.is_file()
        and not any(p.is_symlink() for p in (path, *path.parents)),
        "activation_window_file_invalid",
    )
    _require(
        root is None or path.resolve().is_relative_to(root), "activation_window_owner_mismatch"
    )
    return path.resolve()


def _auto_scope(settings, manifest_path, manifest_sha, *, full):
    """Full checks run outside money locks; stored-state reads hash bytes only."""
    from quant_system.research.admission_qualification_flow import read_recipes
    from quant_system.research.admission_v2 import SCOPE, code_identity, file_sha
    from quant_system.research.admission_window import SCHEMA as WINDOW_SCHEMA

    _require(
        manifest_path is not None and manifest_sha is not None,
        "activation_window_scope_requires_frozen_stage",
    )
    owner = Path(settings.data.data_dir).resolve()
    recipes = read_recipes(settings)
    _require(
        recipes is not None
        and recipes["enabled"]
        and recipes["recipes"]["data"]["dataset"] == _AUTO_DATASET
        and recipes["recipes"]["consumer"].get("control_version") == _AUTO_DATASET,
        "activation_data_control_scope_mismatch",
    )
    namespace = Path(recipes["recipes"]["data"]["source_root"]).resolve()
    path = _regular_file(manifest_path, root=namespace)
    _require(
        path.name == "input-manifest.json" and file_sha(path) == manifest_sha,
        "activation_window_manifest_changed",
    )
    if full:
        from quant_system.research.admission_window import read_window

        _, manifest = read_window(path, manifest_sha)
    else:
        manifest = json.loads(path.read_text())
    _require(
        manifest["schema"] == WINDOW_SCHEMA
        and manifest["dataset"] == _AUTO_DATASET
        and manifest["code_digest"] == code_identity()["digest"]
        and manifest["source"]["owner_root"] == str(owner)
        and path.parent.parent.name == manifest["window_id"],
        "activation_window_owner_or_code_mismatch",
    )
    seed = _regular_file(manifest["source"]["validation_path"], root=owner / "strategy_library")
    _require(
        file_sha(seed) == manifest["source"]["files"][str(seed)], "activation_window_seed_changed"
    )
    validation = json.loads(seed.read_text())
    return {
        "scope": SCOPE,
        "dataset": _AUTO_DATASET,
        "context": copy.deepcopy(manifest["context"]),
        "historical_pit_verified": False,
        "future_inputs_qualified": False,
        "window": {
            "window_id": manifest["window_id"],
            "manifest": {"path": str(path), "sha256": manifest_sha},
            "prices_sha256": manifest["source"]["prices_sha256"],
            "calendar_digest": validation["evaluation_calendar_digest"],
            "code_digest": manifest["code_digest"],
            "owner_root": str(owner),
            "method_digest": _hash(manifest["method"]),
            "producer_sources_digest": _hash(manifest["producer_sources"]),
            "requested_start": manifest["requested_start"],
            "requested_end": manifest["requested_end"],
        },
    }


def _add_files(files, additional):
    from quant_system.research.admission_v2 import file_sha

    _require(isinstance(additional, dict), "activation_stage_file_manifest_invalid")
    for raw, digest in additional.items():
        path = _regular_file(raw)
        _require(
            file_sha(path) == digest and (str(path) not in files or files[str(path)] == digest),
            "activation_stage_inputs_changed",
        )
        files[str(path)] = digest


def _window_files(settings, scope, *, full):
    ref = scope["window"]["manifest"]
    _require(
        _auto_scope(settings, ref["path"], ref["sha256"], full=full) == scope,
        "activation_window_scope_changed",
    )
    path = Path(ref["path"])
    manifest = json.loads(path.read_text())
    owner = Path(settings.data.data_dir).resolve()
    files = {str(path): ref["sha256"]}
    _require(
        set(manifest["artifacts"]) == {"prices.parquet", "source-audit.json"},
        "activation_window_artifacts_changed",
    )
    for name, item in manifest["artifacts"].items():
        _require(item["path"] == name, "activation_window_artifacts_changed")
        _add_files(files, {str(path.parent / name): item["sha256"]})
    for raw, digest in manifest["source"]["files"].items():
        original = _regular_file(raw, root=owner)
        _add_files(files, {str(original): digest})
    repo = Path(__file__).resolve().parents[3]
    for relative, digest in manifest["producer_sources"].items():
        original = _regular_file(repo / relative, root=repo)
        _add_files(files, {str(original): digest})
    return files


def _owner_scope(settings, *, window_manifest=None, window_manifest_sha256=None):
    from quant_system.research.admission_qualification_flow import read_recipes

    recipes = read_recipes(settings)
    if recipes and recipes["recipes"]["data"]["dataset"] == _AUTO_DATASET:
        return _auto_scope(settings, window_manifest, window_manifest_sha256, full=True)
    _require(
        window_manifest is None and window_manifest_sha256 is None,
        "activation_window_arguments_require_auto_recipe",
    )
    if recipes and recipes["recipes"]["data"]["dataset"] == "futu24-saved-intake-20260924":
        _require(
            recipes["recipes"]["consumer"].get("control_version") == "futu24-saved-intake-20260924",
            "activation_data_control_scope_mismatch",
        )
        return _scope("futu24-saved-intake-20260924")
    return _scope()


def _stored_scope(settings, scope):
    if not _is_auto(scope):
        return _owner_scope(settings)
    _window_files(settings, scope, full=False)
    return scope


def _snapshot_for_scope(settings, scope):
    return _snapshot(settings, supported_scope=scope) if _is_auto(scope) else _snapshot(settings)


def _review_for_scope(settings, cohort, scope):
    if _is_auto(scope):
        return _review_stage(settings, cohort, supported_scope=scope)
    return _review_stage(settings, cohort)


def _parallel_jobs(settings):
    from quant_system.research.admission_v2 import code_identity
    from quant_system.research.external_intake import _jobs

    code = code_identity()["digest"]
    jobs = _jobs(settings)
    cohort = [
        row
        for row in jobs
        if row.get("admission_protocol", {}).get("code", {}).get("digest") == code
        and row["admission_protocol"]["mode"] == "parallel"
    ]
    return jobs, cohort


def _classify_job(settings, job, *, supported_scope=None):
    """Only bound actual inputs may prove an exclusion; unknowns stay blocking."""
    from quant_system.research.admission_v2 import file_sha, qualification_input_context

    try:
        _require(job["status"] in {"completed", "failed"}, "activation_stage_job_not_terminal")
        results = {row["variant"]: row for row in job["results"]}
        _require(
            len(results) == len(job["results"]) == len(job["plans"])
            and set(results) == {p["variant"] for p in job["plans"]},
            "activation_stage_variants_incomplete",
        )
        variants, files = [], {}
        for plan in job["plans"]:
            result = results[plan["variant"]]
            path = Path(result["admission_v2"]["path"]).parent / "validation.json"
            _require(file_sha(path) == result["validation_sha256"], "activation_validation_changed")
            facts = _inspect_bound_input(settings, path)
            binding = facts["binding"]
            _require(
                binding["job_id"] == job["job_id"]
                and binding["definition_digest"] == plan["definition_digest"],
                "activation_plan_input_mismatch",
            )
            context = qualification_input_context(binding)
            scope = supported_scope if supported_scope is not None else _owner_scope(settings)
            mismatches = {
                k: {"actual": v, "supported": scope["context"].get(k)}
                for k, v in context.items()
                if scope["context"].get(k) != v
            }
            if _is_auto(scope):
                for key in ("prices_sha256", "calendar_digest"):
                    if binding.get(key) != scope["window"][key]:
                        mismatches[key] = {
                            "actual": binding.get(key),
                            "supported": scope["window"][key],
                        }
            variants.append({"variant": plan["variant"], "scope_mismatches": mismatches})
            for item in (
                path,
                path.parent.parent.parent / "definition.json",
                path.parent / "platform-result.json",
                path.parent / "prices.parquet",
                path.parent / "qlib-replay.json",
                path.parent / "signal-analysis.json",
                Path(facts["evaluation"]["prices_path"]),
            ):
                files[str(item)] = file_sha(item)
        if all(row["scope_mismatches"] for row in variants):
            return {
                "classification": "out_of_scope",
                "job_id": job["job_id"],
                "reason": "bound_actual_inputs_outside_frozen_context",
                "variants": variants,
                "files": files,
            }
        return {"classification": "in_scope", "job_id": job["job_id"]}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {"classification": "unknown", "job_id": job["job_id"], "reason": str(exc)}


def _snapshot(settings, *, supported_scope=None):
    from quant_system.research.admission_v2 import file_sha
    from quant_system.research.external_intake import _job_path

    jobs, parallel = _parallel_jobs(settings)
    classified = [
        _classify_job(settings, job)
        if supported_scope is None
        else _classify_job(settings, job, supported_scope=supported_scope)
        for job in parallel
    ]
    excluded = [row for row in classified if row["classification"] == "out_of_scope"]
    included = {row["job_id"] for row in classified if row["classification"] != "out_of_scope"}
    return {
        "cohort": {
            row["job_id"]: file_sha(_job_path(settings, row["job_id"]))
            for row in parallel
            if row["job_id"] in included
        },
        "parallel": {
            row["job_id"]: file_sha(_job_path(settings, row["job_id"])) for row in parallel
        },
        "exclusions": excluded,
        "unknown": [row for row in classified if row["classification"] == "unknown"],
        "directory": {row["job_id"]: file_sha(_job_path(settings, row["job_id"])) for row in jobs},
    }


def _activation_status(settings):
    """(status, state-or-None): 'absent' / 'valid' / 'invalid:<reason>'.

    Presence of an unusable file must not look like absence: a half-written or
    stale switch is a refused switch while it remains, not a fallback to the
    pre-switch rules.
    """
    try:
        state = _read_state(settings)
        return ("absent", None) if state is None else ("valid", state)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        detail = exc.args[0] if exc.args else type(exc).__name__
        return f"invalid:{detail}", None


def activation_status(settings):
    """Public diagnostic string for the installed switch ('absent'/'valid'/'invalid:…')."""
    return _activation_status(settings)[0]


def configured(settings):
    return _activation_status(settings)[0] == "valid"


def _seal(value):
    return {**value, "digest": _hash(value)}


def _read_sealed(path):
    _require(not path.is_symlink(), "activation_symlink_forbidden")
    value = json.loads(path.read_text())
    _require(isinstance(value, dict), "activation_object_required")
    _require(
        value.get("digest") == _hash({k: v for k, v in value.items() if k != "digest"}),
        "activation_digest_mismatch",
    )
    return value


def _read_state(settings):
    from quant_system.research.admission_qualification_flow import read_recipes
    from quant_system.research.admission_v2 import code_identity, file_sha
    from quant_system.research.gate_v2.verdict import GATE_V2_CONFIG

    path = _root(settings) / "activation.json"
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    _require(stat.S_ISREG(info.st_mode), "activation_regular_file_required")
    _require(
        info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
        "activation_owner_invalid",
    )
    state = _read_sealed(path)
    _require(
        set(state)
        == {
            "schema",
            "code_digest",
            "config_digest",
            "supported_scope",
            "recipe_digest",
            "stage",
            "digest",
        }
        and state["schema"] == SCHEMA
        and state["code_digest"] == code_identity()["digest"]
        and state["config_digest"] == _hash(GATE_V2_CONFIG)
        and state["supported_scope"] == _stored_scope(settings, state["supported_scope"])
        and state["recipe_digest"] == _hash(read_recipes(settings)),
        "activation_source_scope_or_recipe_changed",
    )
    stage_path = Path(state["stage"]["path"])
    _require(
        stage_path.resolve().is_relative_to(_root(settings).resolve() / "stages")
        and not stage_path.is_symlink()
        and file_sha(stage_path) == state["stage"]["sha256"],
        "activation_stage_changed",
    )
    stage = _read_sealed(stage_path)
    _require(
        stage["schema"] == STAGE_SCHEMA
        and stage["code_digest"] == state["code_digest"]
        and stage["recipe_digest"] == state["recipe_digest"]
        and stage["supported_scope"] == state["supported_scope"],
        "activation_stage_binding_mismatch",
    )
    return state


def _plans_match_scope(plans, scope):
    """Conservative, metadata-only routing; prices are checked after evaluation."""
    try:
        _require(isinstance(plans, list) and bool(plans), "activation_plans_missing")
        context = scope["context"]
        requested = scope.get("window", {})
        start = requested.get("requested_start", "2018-01-01")
        end = requested.get("requested_end", context["end"])
        for plan in plans:
            payload, origin = plan["payload"], plan["origin"]
            if not (
                origin["start"] == start
                and origin["end"] == end
                and payload["symbols"] == context["ordered_symbols"]
                and payload.get("history_start", plan.get("history_start", "2015-01-01"))
                == context.get("history_start", "2015-01-01")
                and all(
                    payload[k] == context[k]
                    for k in (
                        "benchmark_symbol",
                        "rebalance",
                        "top_n",
                        "execution_price",
                        "commission_bps",
                        "slippage_bps",
                        "target_gross_exposure",
                        "max_weight_per_symbol",
                        "selection",
                        "min_order_value",
                        "whole_share_orders",
                    )
                )
            ):
                return False
        return True
    except (ValueError, KeyError, TypeError):
        return False


def protocol_binding(settings, *, plans=None):
    """Cheap reference projection for NEW jobs only; not funding authorization."""
    state = _read_state(settings)
    if state is None:
        return None
    if (
        plans is not None
        and _is_auto(state["supported_scope"])
        and not _plans_match_scope(plans, state["supported_scope"])
    ):
        return None
    return {
        "schema": SCHEMA,
        "state_digest": state["digest"],
        "stage_sha256": state["stage"]["sha256"],
        "code_digest": state["code_digest"],
        "supported_scope": state["supported_scope"],
    }


def _binding_scope_valid(scope, code_digest):
    if not _is_auto(scope):
        return scope == _scope(scope.get("dataset"))
    from quant_system.research.admission_v2 import SCOPE

    try:
        value = scope["window"]
        return (
            set(scope)
            == {
                "scope",
                "dataset",
                "context",
                "historical_pit_verified",
                "future_inputs_qualified",
                "window",
            }
            and scope["scope"] == SCOPE
            and isinstance(scope["context"], dict)
            and scope["historical_pit_verified"] is False
            and scope["future_inputs_qualified"] is False
            and set(value) == _WINDOW_KEYS
            and value["code_digest"] == code_digest
            and set(value["manifest"]) == {"path", "sha256"}
            and Path(value["manifest"]["path"]).is_absolute()
            and Path(value["owner_root"]).is_absolute()
            and re.fullmatch(r"futu24-window-[0-9a-f]{64}", value["window_id"]) is not None
            and all(
                re.fullmatch(r"[0-9a-f]{64}", value[k]) is not None
                for k in (
                    "prices_sha256",
                    "calendar_digest",
                    "code_digest",
                    "method_digest",
                    "producer_sources_digest",
                )
            )
            and re.fullmatch(r"[0-9a-f]{64}", value["manifest"]["sha256"]) is not None
        )
    except (KeyError, TypeError, ValueError):
        return False


def validate_binding(binding, *, current_scope=True):
    _require(
        isinstance(binding, dict)
        and set(binding)
        == {"schema", "state_digest", "stage_sha256", "code_digest", "supported_scope"}
        and binding["schema"] == SCHEMA
        and isinstance(binding["supported_scope"], dict)
        and (
            not current_scope
            or _binding_scope_valid(binding["supported_scope"], binding.get("code_digest"))
        )
        and all(
            isinstance(binding[k], str) and len(binding[k]) == 64
            for k in ("state_digest", "stage_sha256", "code_digest")
        ),
        "activation_protocol_binding_invalid",
    )


def _require_scope_input(scope, context, source_binding):
    _require(
        all(scope["context"].get(k) == v for k, v in context.items()),
        "activation_input_outside_frozen_scope",
    )
    if _is_auto(scope):
        _require(
            isinstance(source_binding, dict)
            and all(
                source_binding.get(k) == scope["window"][k]
                for k in ("prices_sha256", "calendar_digest")
            ),
            "activation_window_input_mismatch",
        )


def require_context(binding, context, *, source_binding=None):
    validate_binding(binding)
    _require_scope_input(binding["supported_scope"], context, source_binding)


# Typed require_context refusals: a bound input that can never enter the frozen
# scope, as opposed to evidence that is merely still missing.
FROZEN_SCOPE_REJECTIONS = (
    "activation_protocol_binding_invalid",
    "activation_input_outside_frozen_scope",
    "activation_window_input_mismatch",
)


def capital_requires_authoritative_job(settings, protocol):
    """Installed state withdraws new capital from every non-authoritative job.

    "Installed" means the switch file is present, not merely valid: a stale or
    unreadable activation still names a switch, and falling back to legacy money
    rules while one is broken would silently re-open the pre-switch path.
    """
    return (
        _activation_status(settings)[0] != "absent"
        and (protocol or {}).get("mode") != "authoritative"
    )


def deactivate(settings, *, reason: str) -> dict:
    """Revoke the installed switch with an audit trail; pre-switch money rules resume.

    The sealed artifact is moved (never edited in place) so its recorded digest
    still verifies after removal, and a note records the original sha256, its
    validity at removal time and the operator reason.
    """
    from quant_system.research.external_intake import _lock

    _require(_root(settings).is_dir(), "activation_missing")
    with _lock(_root(settings) / "activation-review.lock", nonblocking=True):
        return _deactivate_locked(settings, reason=reason)


def _deactivate_locked(settings, *, reason):
    from quant_system.research.admission_v2 import file_sha
    from quant_system.research.external_intake import _private_directory, _write

    path = _root(settings) / "activation.json"
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("activation_missing") from exc
    _require(stat.S_ISREG(info.st_mode), "activation_regular_file_required")
    _require(bool(reason.strip()), "deactivate_reason_required")
    raw = path.read_bytes()
    status, state = _activation_status(settings)
    # Archived switch state stays owner-only like every other intake record.
    _private_directory(_root(settings) / "deactivated")
    target_dir = _root(settings) / "deactivated"
    digest = hashlib.sha256(raw).hexdigest()
    event_id = f"activation-{digest[:12]}-{time.time_ns()}"
    target = target_dir / f"{event_id}.json"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _require(
        file_sha(target) == file_sha(path) == digest,
        "deactivate_artifact_changed_during_move",
    )
    note = {
        "activation_sha256": digest,
        "reason": reason,
        "removed_at_epoch": time.time(),
        "valid_at_removal": status == "valid",
        "state_digest": (state or {}).get("digest"),
        "status_at_removal": status,
    }
    note_path = target_dir / f"{event_id}.removed.json"
    _write(note_path, note)
    _require(file_sha(path) == digest, "deactivate_artifact_changed_during_move")
    path.unlink()
    _WARM.clear()
    return {
        "status": "deactivated",
        "activation_sha256": digest,
        "archived_at": str(target),
        "note": note,
    }


def _history(path):
    from quant_system.research.admission_v2 import file_sha

    _require(
        path is not None and file_sha(path) == HISTORY_SHA,
        "activation_historical_inventory_unavailable",
    )
    value = json.loads(Path(path).read_text())
    return [
        {
            "job_id": row["job_id"],
            "variant": row["variant"],
            "validation_run_id": row["validation_run_id"],
            "saved_status": row["status"],
            "v2_as_of_status": "not_evaluated",
            "reason": "historical_peer_protocol_qualifier_context_not_frozen",
        }
        for row in value["validation_references"]
    ]


def _calibration_file_bindings(settings, descriptor, consumer):
    """Bind the fixed historical snapshot's declared leaf aliases, never arbitrary links."""
    from quant_system.research.admission_consumer_checks import CURRENT_CONTROL_RULE, LEDGER_SHA
    from quant_system.research.admission_qualification_flow import read_recipes
    from quant_system.research.admission_v2 import file_sha

    inputs = consumer["calibration"]["input_files"]
    _require(isinstance(inputs, dict) and bool(inputs), "activation_window_control_files_missing")
    linked = {p: digest for p, digest in inputs.items() if Path(p).is_symlink()}
    files, aliases = {}, {}
    _add_files(files, {p: digest for p, digest in inputs.items() if p not in linked})
    if not linked:
        return files, aliases
    _add_files(files, {descriptor["path"]: descriptor["sha256"]})
    registration = json.loads(Path(descriptor["path"]).read_text())
    recipes = read_recipes(settings)
    root = Path(recipes["recipes"]["consumer"]["data_root"])
    _require(
        root.is_absolute()
        and root.is_dir()
        and not any(p.is_symlink() for p in (root, *root.parents))
        and registration["evidence"]["data_root"] == str(root),
        "activation_calibration_alias_root_changed",
    )
    root = root.resolve()
    provenance_path = _regular_file(root / "snapshot-provenance.json", root=root)
    _require(
        file_sha(provenance_path) == _HISTORICAL_ALIAS_PROVENANCE_SHA,
        "activation_calibration_alias_provenance_changed",
    )
    provenance = json.loads(provenance_path.read_text())
    if consumer.get("current_control_rule") == CURRENT_CONTROL_RULE:
        # The old ledger is producer provenance, never the current population.
        _require(
            consumer.get("historical_family_39")
            == {"purpose": "original_engine_population_provenance_only",
                "new_funding_qualification": False}
            and any(Path(path).name == "source-trials.jsonl" and digest == LEDGER_SHA
                    for path, digest in inputs.items()),
            "activation_historical_control_provenance_missing",
        )
        historical_ledger = LEDGER_SHA
    else:
        historical_ledger = consumer.get("historical_control_population", {}).get(
            "original_ledger_sha256"
        )
    _require(
        set(provenance) == {"schema", "original_ledger_sha256", "files"}
        and provenance["schema"] == "fixed_family_source_aliases/v1"
        and provenance["original_ledger_sha256"]
        == historical_ledger
        == LEDGER_SHA
        and isinstance(provenance["files"], dict),
        "activation_calibration_alias_provenance_changed",
    )
    declared = {}
    for relative, item in provenance["files"].items():
        _require(
            not Path(relative).is_absolute()
            and ".." not in Path(relative).parts
            and set(item) == {"original_path", "sha256"},
            "activation_calibration_alias_provenance_changed",
        )
        declared[str(root / relative)] = (relative, item)
    _require(set(declared) == set(linked), "activation_calibration_alias_population_changed")
    _add_files(files, {str(provenance_path): file_sha(provenance_path)})
    for raw, digest in linked.items():
        alias = Path(raw)
        relative, item = declared[raw]
        target = _regular_file(item["original_path"])
        _require(
            alias.is_absolute()
            and alias.is_file()
            and not any(p.is_symlink() for p in alias.parents)
            and os.readlink(alias) == item["original_path"] == str(target)
            and alias.resolve() == target
            and digest == item["sha256"] == file_sha(target) == file_sha(alias),
            "activation_calibration_alias_changed",
        )
        _add_files(files, {str(target): digest})
        files[str(alias)] = digest  # Keep the alias itself, not just its resolved target.
        aliases[str(alias)] = {
            "target_path": str(target),
            "link_text": os.readlink(alias),
            "sha256": digest,
            "provenance_path": str(provenance_path),
            "provenance_relative": relative,
        }
    return files, aliases


def _verify_review_files(review):
    """Cheap byte and link-relation CAS. No verifier, engine or DataFrame work."""
    from quant_system.research.admission_v2 import file_sha

    files, aliases = review["files"], review.get("file_aliases", {})
    _require(
        isinstance(aliases, dict) and set(aliases) <= set(files),
        "activation_stage_alias_manifest_changed",
    )
    _require(
        all(file_sha(p) == digest for p, digest in files.items()), "activation_stage_inputs_changed"
    )
    provenance_cache = {}
    for raw in files:
        if raw not in aliases:
            _regular_file(raw)
            continue
        alias, relation = Path(raw), aliases[raw]
        _require(
            set(relation)
            == {"target_path", "link_text", "sha256", "provenance_path", "provenance_relative"},
            "activation_stage_alias_manifest_changed",
        )
        target = _regular_file(relation["target_path"])
        provenance = _regular_file(relation["provenance_path"])
        _require(
            alias.is_absolute()
            and alias.is_symlink()
            and not any(p.is_symlink() for p in alias.parents)
            and os.readlink(alias) == relation["link_text"] == str(target)
            and alias.resolve() == target
            and files.get(str(target)) == files[raw] == relation["sha256"]
            and str(provenance) in files,
            "activation_stage_alias_changed",
        )
        if str(provenance) not in provenance_cache:
            provenance_cache[str(provenance)] = json.loads(provenance.read_text())
        original = provenance_cache[str(provenance)]["files"][relation["provenance_relative"]]
        _require(
            original == {"original_path": str(target), "sha256": relation["sha256"]},
            "activation_stage_alias_manifest_changed",
        )


def _same_review_files(first, second):
    return first["files"] == second["files"] and first.get("file_aliases", {}) == second.get(
        "file_aliases", {}
    )


def _qualified_window_files(settings, scope, fresh):
    """Only already executed qualifier results supply this stage's full file closure."""
    data = fresh["qualifications"]["data"]["registration"]["details"]["provenance"]
    consumer = fresh["qualifications"]["consumer"]["registration"]["details"]
    ref = scope["window"]
    _require(
        data["manifest_sha256"] == ref["manifest"]["sha256"]
        and data["window_id"] == consumer["window_id"] == ref["window_id"]
        and data["prices_sha256"] == ref["prices_sha256"],
        "activation_window_qualification_mismatch",
    )
    files, aliases = _calibration_file_bindings(
        settings, fresh["qualifications"]["consumer"]["descriptor"], consumer
    )
    from quant_system.research.admission_consumer_checks import CURRENT_CONTROL_RULE

    if consumer.get("current_control_rule") == CURRENT_CONTROL_RULE:
        semantic = consumer.get("semantic_calibration") or {}
        _require(semantic.get("status") == "passed"
                 and isinstance(semantic.get("input_files"), dict)
                 and bool(semantic["input_files"]),
                 "activation_semantic_calibration_files_missing")
        _add_files(files, semantic["input_files"])
    _add_files(files, consumer["test_execution_evidence"]["files"])
    execution = consumer["test_execution_evidence"]
    _add_files(files, {execution["path"]: execution["sha256"]})
    for row in fresh["qualifications"].values():
        descriptor = row["descriptor"]
        _add_files(files, {descriptor["path"]: descriptor["sha256"]})
    return files, aliases


def _current_control_population(consumer, fresh):
    """Keep present qualification and historical producer provenance distinct."""
    from quant_system.research.admission_consumer_checks import CURRENT_CONTROL_RULE

    rule = consumer.get("current_control_rule")
    population = consumer.get("current_control_population")
    if rule is None and population is None:
        return None
    _require(rule == CURRENT_CONTROL_RULE and isinstance(population, dict),
             "activation_current_control_population_missing")
    _require(
        all(isinstance(population.get(key), str) and len(population[key]) == 64
            and set(population[key]) <= set("0123456789abcdef")
            for key in ("family_digest", "original_ledger_sha256", "admission_peer_digest",
                        "peer_digest")),
        "activation_current_control_population_missing",
    )
    calibration = consumer.get("calibration") or {}
    scope = calibration.get("current_scope") or {}
    family = fresh["gate"]["family"]
    binding = fresh["source_binding"]
    _require(
        population.get("family_digest") == family["family_digest"]
        == (calibration.get("family") or {}).get("family_digest")
        and population.get("family_n_trials") == family["n_trials"]
        == (calibration.get("family") or {}).get("n_trials")
        and population.get("original_ledger_sha256") == binding["trial_ledger_sha256"]
        == scope.get("trial_ledger_sha256")
        and population.get("admission_peer_digest") == binding["peer_digest"]
        == scope.get("admission_peer_digest")
        and population.get("peer_digest") == scope.get("peer_digest")
        == (calibration.get("peer_identity") or {}).get("digest")
        and population.get("n_controls") == calibration.get("n_controls") == 500
        and population.get("statistically_evaluable")
        == calibration.get("statistically_evaluable") == 500,
        "activation_current_control_population_mismatch",
    )
    return {
        **population,
        "current_control_rule": rule,
        "calibration_digest": consumer["calibration_digest"],
        "control_version": consumer["control_version"],
        "purpose": "fixed_real_price_controls_under_current_complete_family_and_strict_peers",
        "not_current_family_false_pass_estimate": False,
        "historical_family_provenance": consumer.get("historical_family_39"),
    }


def _review_stage(settings, cohort, *, supported_scope=None):
    """Recompute every native variant through fixed qualification and gate programs."""
    from quant_system.execution.assistant_remote import load_book
    from quant_system.research import admission_v2 as admission
    from quant_system.research.admission_qualification_flow import ensure_qualifications
    from quant_system.research.external_intake import _job_path, _load_job

    _require(bool(cohort), "activation_parallel_cohort_empty")
    scope = supported_scope if supported_scope is not None else _owner_scope(settings)
    files = _window_files(settings, scope, full=True) if _is_auto(scope) else {}
    rows, populations, current_populations, file_aliases = [], [], [], {}
    for job_id, job_sha in sorted(cohort.items()):
        path = _job_path(settings, job_id)
        _require(admission.file_sha(path) == job_sha, "activation_cohort_job_changed")
        files[str(path)] = job_sha
        job = _load_job(settings, job_id)
        protocol = job["admission_protocol"]
        admission.verify_protocol(protocol)
        _require(
            protocol["mode"] == "parallel" and "activation" not in protocol,
            "activation_stage_must_precede_authority",
        )
        _require(job["status"] in {"completed", "failed"}, "activation_stage_job_not_terminal")
        results = {row["variant"]: row for row in job["results"]}
        _require(
            len(results) == len(job["results"]) == len(job["plans"])
            and set(results) == {p["variant"] for p in job["plans"]},
            "activation_stage_variants_incomplete",
        )
        for plan in job["plans"]:
            result = results[plan["variant"]]
            descriptor = result.get("admission_v2")
            _require(isinstance(descriptor, dict), "activation_parallel_receipt_missing")
            run = Path(descriptor["path"]).parent
            definition = run.parent.parent / "definition.json"
            saved = admission.read_bound_receipt(
                settings,
                descriptor,
                definition_digest=plan["definition_digest"],
                validation_sha256=result["validation_sha256"],
                source_sha256=admission.file_sha(definition),
            )
            _require(saved.get("gate") is not None, "activation_saved_v2_statistics_missing")
            ensure_qualifications(
                settings, validation_path=run / "validation.json", protocol=protocol
            )
            fresh = admission.evaluate_validation(
                settings,
                protocol=protocol,
                validation_path=run / "validation.json",
                expected_validation_sha=result["validation_sha256"],
                definition_digest=plan["definition_digest"],
                source_sha256=admission.file_sha(definition),
                evaluation=job["evaluation"],
                book=load_book(settings),
            )
            _require(
                fresh["status"] in {"recorded", "shadow", "passed"}
                and all(v["status"] == "passed" for v in fresh["qualifications"].values()),
                "activation_fixed_qualifications_incomplete",
            )
            actual = admission.qualification_input_context(fresh["source_binding"])
            if _is_auto(scope):
                _require_scope_input(scope, actual, fresh["source_binding"])
                additional, aliases = _qualified_window_files(settings, scope, fresh)
                for path, digest in additional.items():
                    _require(
                        path not in files or files[path] == digest,
                        "activation_stage_inputs_changed",
                    )
                    files[path] = digest
                for path, relation in aliases.items():
                    _require(
                        path not in file_aliases or file_aliases[path] == relation,
                        "activation_stage_alias_manifest_changed",
                    )
                    file_aliases[path] = relation
            else:
                _require(
                    all(scope["context"].get(k) == v for k, v in actual.items()),
                    "activation_stage_outside_frozen_scope",
                )
            gate = fresh["gate"]
            _require(
                gate["family"]["trusted"]
                and gate["dsr"]["path"] == "data_driven"
                and gate["dsr"].get("reason") is None
                and not gate["concentration"]["raw_unavailable_sleeves"]
                and fresh["residual_calibration"]["status"] in {"evaluated", "not_applicable"},
                "activation_stage_statistics_not_evaluated",
            )
            validation = json.loads((run / "validation.json").read_text())
            old = validation["status"] == "passed"
            new = saved["gate"]["tier_recommendation"]["tier"] == "T2"
            rows.append(
                {
                    "job_id": job_id,
                    "variant": plan["variant"],
                    "validation_sha256": result["validation_sha256"],
                    "saved_v1_passed": old,
                    "saved_v2_numeric_passed": new,
                    "conclusion_changed": old != new,
                    "current_qualified_tier": fresh["validated_tier"],
                    "declared_increment": (
                        fresh["source_binding"].get("increment_binding") or {}
                    ).get("objective"),
                    "current_family_digest": gate["family"]["family_digest"],
                    "current_family_n_trials": gate["family"]["n_trials"],
                    "current_peer_digest": fresh["source_binding"]["peer_digest"],
                    "current_trial_ledger_sha256": fresh["source_binding"]["trial_ledger_sha256"],
                }
            )
            consumer = fresh["qualifications"]["consumer"]["registration"]["details"]
            current_population = _current_control_population(consumer, fresh)
            if current_population is not None:
                current_populations.append(current_population)
            else:
                populations.append(
                    {
                        **consumer["historical_control_population"],
                        "calibration_digest": consumer["calibration_digest"],
                        "control_version": consumer["control_version"],
                        "purpose": (
                            "static_code_calibration_with_frozen_historical_39_family_2_peers"
                        ),
                        "not_current_family_false_pass_estimate": True,
                    }
                )
            for item in (
                definition,
                run / "validation.json",
                Path(descriptor["path"]),
                run / "platform-result.json",
                run / "prices.parquet",
                run / "qlib-replay.json",
                run / "signal-analysis.json",
            ):
                files[str(item)] = admission.file_sha(item)
    _require(rows, "activation_parallel_cohort_empty")
    closing = _current_population(settings)
    _require(
        all(
            row["current_trial_ledger_sha256"] == closing["trial_ledger_sha256"]
            and row["current_peer_digest"] == closing["peer_digest"]
            for row in rows
        ),
        "activation_population_changed_during_review",
    )
    return {
        "closing_population": closing,
        "rows": rows,
        "files": files,
        "file_aliases": file_aliases,
        "historical_control_populations": populations,
        "current_control_populations": current_populations,
        "current_stage_populations": [
            {
                k: row[k]
                for k in (
                    "job_id",
                    "variant",
                    "current_family_digest",
                    "current_family_n_trials",
                    "current_peer_digest",
                    "current_trial_ledger_sha256",
                )
            }
            for row in rows
        ],
        "limitations": [
            "static_24_frozen_window_only",
            "no_future_dataset_qualification",
            "more_trials_not_claimed_monotonically_conservative",
            "no_required_T2_hit_rate",
            "historical_unknowns_not_reconstructed",
        ],
    }


def _current_population(settings):
    from quant_system.execution.assistant_remote import load_book
    from quant_system.research.admission_v2 import ledger_snapshot, peer_snapshot

    return {
        "trial_ledger_sha256": ledger_snapshot(settings)[1],
        "peer_digest": peer_snapshot(load_book(settings), settings=settings)[1]["digest"],
    }


def _save(path, value):
    from quant_system.research.external_intake import _private_directory, _write

    _private_directory(path.parent)
    if path.exists():
        _require(json.loads(path.read_text()) == value, "activation_immutable_record_collision")
    else:
        _write(path, value)


def _review_existing(settings, state, historical_inventory, activate):
    """Response-loss retry is verify-only; never revoke already frozen protocols.

    Current trial/catalog growth is audited separately from the closed phase.
    A different parallel cohort is blocked, not silently installed as a new
    activation that invalidates old job bindings.
    """
    from quant_system.research.external_intake import _lock, root

    stage = _read_sealed(Path(state["stage"]["path"]))
    key = _warm_key(settings, state, stage)
    _verify_membership(settings, stage)
    history = _history(historical_inventory)
    reviewed = _review_for_scope(settings, stage["snapshot"]["cohort"], state["supported_scope"])
    _require(
        _same_review_files(reviewed, stage["review"]), "activation_stage_file_manifest_mismatch"
    )
    with ExitStack() as stack:
        for name in ("worker.lock", "queue.lock"):
            stack.enter_context(_lock(root(settings) / name, nonblocking=True))
        _require(
            _read_state(settings) == state and _warm_key(settings, state, stage) == key,
            "activation_changed_during_review",
        )
        _require(
            _current_population(settings) == reviewed["closing_population"],
            "activation_population_changed_before_publish",
        )
    return {
        "status": "activated" if activate else "ready",
        "reasons": [],
        "capital_authorized": False,
        "reused_existing_activation": True,
        "stage": state["stage"],
        "state_digest": state["digest"],
        "supported_scope": state["supported_scope"],
        "phase_snapshot": stage["snapshot"],
        "review": reviewed,
        "historical_unknown": history,
    }


def _record_review(settings, output):
    record = _root(settings) / "switch-reviews" / str(time.time_ns())
    _save(record.with_suffix(".json"), output)
    with record.with_suffix(".md").open("x") as stream:
        stream.write(_render_review(output))
    record.with_suffix(".md").chmod(0o600)


def review_and_activate(
    settings,
    *,
    historical_inventory,
    activate=True,
    window_manifest=None,
    window_manifest_sha256=None,
):
    """One bounded review; ready evidence automatically installs state, never funds."""
    from quant_system.research.admission_qualification_flow import read_recipes
    from quant_system.research.admission_v2 import code_identity, file_sha
    from quant_system.research.external_intake import _lock, _private_directory, _write, root
    from quant_system.research.gate_v2.verdict import GATE_V2_CONFIG

    output = {"status": "blocked", "reasons": [], "capital_authorized": False}
    try:
        _private_directory(root(settings))
        _private_directory(_root(settings))
        with _lock(_root(settings) / "activation-review.lock", nonblocking=True):
            existing = _read_state(settings)
            if existing is not None:
                if window_manifest is not None or window_manifest_sha256 is not None:
                    requested = _owner_scope(
                        settings,
                        window_manifest=window_manifest,
                        window_manifest_sha256=window_manifest_sha256,
                    )
                    _require(
                        requested == existing["supported_scope"],
                        "activation_existing_window_change_forbidden",
                    )
                output = _review_existing(settings, existing, historical_inventory, activate)
                _record_review(settings, output)
                return output
            scope = _owner_scope(
                settings,
                window_manifest=window_manifest,
                window_manifest_sha256=window_manifest_sha256,
            )
            with ExitStack() as stack:
                for name in ("worker.lock", "queue.lock"):
                    stack.enter_context(_lock(root(settings) / name, nonblocking=True))
                snapshot = _snapshot_for_scope(settings, scope)
            output.update(phase_snapshot=snapshot, supported_scope=scope)
            _require(not snapshot["unknown"], "activation_stage_scope_unknown")
            _require(snapshot["cohort"], "activation_parallel_cohort_empty")
            recipes = read_recipes(settings)
            _require(recipes is not None and recipes["enabled"], "activation_recipes_not_enabled")
            code = code_identity()["digest"]
            history = _history(historical_inventory)
            output.update(
                historical_unknown=history,
                phase_snapshot=snapshot,
                supported_scope=scope,
            )
            reviewed = _review_for_scope(settings, snapshot["cohort"], scope)
            stage = _seal(
                {
                    "schema": STAGE_SCHEMA,
                    "code_digest": code,
                    "recipe_digest": _hash(recipes),
                    "supported_scope": scope,
                    "closed_at_epoch": time.time(),
                    "snapshot": snapshot,
                    "historical_inventory": {
                        "path": str(Path(historical_inventory).resolve()),
                        "sha256": HISTORY_SHA,
                    },
                    "historical_unknown": history,
                    "review": reviewed,
                }
            )
            stage_path = _root(settings) / "stages" / (stage["digest"] + ".json")
            with ExitStack() as stack:
                for name in ("worker.lock", "queue.lock"):
                    stack.enter_context(_lock(root(settings) / name, nonblocking=True))
                _require(
                    _snapshot_for_scope(settings, scope) == snapshot
                    and code_identity()["digest"] == code
                    and read_recipes(settings) == recipes,
                    "activation_stage_changed_before_publish",
                )
                _require(
                    _current_population(settings) == reviewed["closing_population"],
                    "activation_population_changed_before_publish",
                )
                _verify_review_files(reviewed)
                _save(stage_path, stage)
                state = _seal(
                    {
                        "schema": SCHEMA,
                        "code_digest": code,
                        "config_digest": _hash(GATE_V2_CONFIG),
                        "recipe_digest": _hash(recipes),
                        "supported_scope": scope,
                        "stage": {"path": str(stage_path), "sha256": file_sha(stage_path)},
                    }
                )
                if activate:
                    _write(_root(settings) / "activation.json", state)
                output.update(
                    status="activated" if activate else "ready",
                    stage=state["stage"],
                    state_digest=state["digest"],
                    supported_scope=scope,
                    review=reviewed,
                    historical_unknown=history,
                )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        output["reasons"] = [str(exc)]
    _record_review(settings, output)
    return output


def _render_review(value):
    scope = value.get("supported_scope", {}).get("context", {})
    lines = [
        "# 有限范围准入切换评审",
        "",
        f"状态：{value['status']}。本动作不配置资金。",
        "",
        f"阻断原因：{', '.join(value.get('reasons', [])) or '无'}",
        "",
        f"支持范围：原有序 24 股，SPY，月度 Top5，next_open，1bp+5bp，"
        f"实际交易日 {scope.get('start', 'unknown')} 至 {scope.get('end', 'unknown')}。",
        "未来价格、其他窗口、其他股票池没有自动取得资格。",
        "",
        "## 本阶段保存的新旧结论",
        "",
        "| 作业 | 变体 | 保存 v1 | 保存 v2 数学判定 | 当前完整资格等级 | 改变 |",
        "|---|---|---|---|---|---|",
    ]
    review = value.get("review", {})
    for row in review.get("rows", []):
        lines.append(
            f"| {row.get('job_id')} | {row.get('variant')} | {row.get('saved_v1_passed')} | "
            f"{row.get('saved_v2_numeric_passed')} | {row.get('current_qualified_tier')} | "
            f"{row.get('conclusion_changed')} |"
        )
    lines += [
        "",
        "## 全量范围分类",
        "",
        "只有原件、定义及实际评价绑定可核验且明确范围外的记录可排除；未知或损坏仍阻断。",
        "",
        "| 作业 | 分类 | 具体范围差异或原因 |",
        "|---|---|---|",
    ]
    snapshot = value.get("phase_snapshot", {})
    for row in snapshot.get("exclusions", []):
        fields = "; ".join(
            item["variant"] + ": " + ", ".join(sorted(item["scope_mismatches"]))
            for item in row["variants"]
        )
        lines.append(f"| {row['job_id']} | 明确范围外 | {fields} |")
    for row in snapshot.get("unknown", []):
        lines.append(f"| {row['job_id']} | unknown，不排除 | {row['reason']} |")
    lines += [
        "",
        "## 两种总体不能混用",
        "",
        ("本轮 500 对照使用当前完整试验族和实际同行；历史39仅作为原始引擎总体出处。"
         if review.get("current_control_populations") else
         "500 对照只校准固定历史 39 族 / 2 peer 的代码行为；peer 按真实日期交集计算。"),
        "当前阶段与资金使用完整当下族和 peer 重新判定及 CAS；不声称试验族增加必然更保守。",
        "",
        "```json",
        json.dumps(
            {
                k: review.get(k)
                for k in ("historical_control_populations", "current_control_populations",
                          "current_stage_populations")
            },
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "## 旧历史未能恢复的当时判定",
        "",
        "下列仅保留 unknown，不补造当时的 peer、协议或资格。",
        "",
        "| 作业 | 变体 | 原验证 | 当时 v2 |",
        "|---|---|---|---|",
    ]
    for row in value.get("historical_unknown", []):
        lines.append(
            f"| {row['job_id']} | {row['variant']} | {row['validation_run_id']} | not_evaluated |"
        )
    return "\n".join(lines) + "\n"


def _stage_key(settings, state, stage):
    """Identity of the installed switch for warm-proof keying only.

    Reads the sealed activation/state pair only; byte-level tamper detection is
    _verify_stage_files, which verify_for_funding runs on every call — a warm
    proof never substitutes for file hashing."""
    return _hash(
        {
            "owner": str(Path(settings.data.data_dir).resolve()),
            "state": state,
            "stage_files": stage["review"]["files"],
            "stage_file_aliases": stage["review"].get("file_aliases", {}),
        }
    )


def _verify_cohort_integrity(settings, stage):
    """Per-call integrity of the install-time cohort: members' job files and the
    excluded inputs must still be present and byte-identical. Jobs submitted after
    the switch are outside it and stay withdrawn from capital on their own."""
    from quant_system.research.admission_v2 import file_sha
    from quant_system.research.external_intake import _job_path

    snapshot = stage["snapshot"]
    _, parallel = _parallel_jobs(settings)
    identity = {
        row["job_id"]: file_sha(_job_path(settings, row["job_id"])) for row in parallel
    }
    _require(
        all(
            identity.get(job_id) == expected
            for job_id, expected in snapshot["parallel"].items()
        ),
        "activation_stage_inputs_changed",
    )
    _require(
        all(
            file_sha(p) == s
            for item in snapshot["exclusions"]
            for p, s in item["files"].items()
        ),
        "activation_excluded_input_changed",
    )
    _history(stage["historical_inventory"]["path"])


def _verify_stage_files(settings, stage):
    """Full integrity sweep: cohort checks plus every recorded review artifact
    (control files, consumer execution envelope, alias/provenance bindings).
    This is the per-call layer even inside a warm window — warm proofs skip
    membership re-derivation and consumer re-execution, never file hashing."""
    _verify_cohort_integrity(settings, stage)
    _verify_review_files(stage["review"])


def _warm_key(settings, state, stage):
    _verify_stage_files(settings, stage)
    return _stage_key(settings, state, stage)


def _verify_membership(settings, stage):
    snapshot = stage["snapshot"]
    recorded_ids = set(snapshot["parallel"])
    current = _snapshot_for_scope(settings, stage["supported_scope"])
    # Install-time invariant (install blocks on unknown): parallel == cohort ∪
    # exclusions. A later parallel job is not a cohort member and must not mute
    # the switch; only recorded members classify/mutation matters.
    _require(
        recorded_ids
        == set(snapshot["cohort"]) | {row["job_id"] for row in snapshot["exclusions"]},
        "activation_snapshot_incoherent",
    )
    cohort_now = {
        job_id: sha
        for job_id, sha in current["cohort"].items()
        if job_id in snapshot["cohort"]
    }
    exclusions_now = {
        row["job_id"]: row["files"]
        for row in current["exclusions"]
        if row["job_id"] in recorded_ids
    }
    _require(
        not [u for u in current["unknown"] if u["job_id"] in recorded_ids]
        and cohort_now == snapshot["cohort"]
        and exclusions_now
        == {row["job_id"]: row["files"] for row in snapshot["exclusions"]},
        "activation_parallel_cohort_changed",
    )


def verify_for_funding(settings, protocol, context, *, allow_execution, source_binding=None):
    """Only a real fixed-program evaluation may create process-local warm proof."""
    require_context(protocol.get("activation"), context, source_binding=source_binding)
    state = _read_state(settings)
    _require(
        state is not None and protocol["activation"] == protocol_binding(settings),
        "activation_state_changed_or_missing",
    )
    stage = _read_sealed(Path(state["stage"]["path"]))
    _verify_stage_files(settings, stage)
    key = _stage_key(settings, state, stage)
    warm = _WARM.get(key)
    if warm and warm[0] == os.getpid() and time.monotonic() - warm[1] < _WARM_SECONDS:
        return
    _require(allow_execution, "admission_v2_activation_preflight_required")
    _verify_membership(settings, stage)
    reviewed = _review_for_scope(settings, stage["snapshot"]["cohort"], state["supported_scope"])
    _require(
        _same_review_files(reviewed, stage["review"]), "activation_stage_file_manifest_mismatch"
    )
    _require(
        _read_state(settings) == state and _stage_key(settings, state, stage) == key,
        "activation_changed_during_preflight",
    )
    if len(_WARM) >= 128:
        _WARM.clear()
    _WARM[key] = (os.getpid(), time.monotonic())
