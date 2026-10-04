"""One isolated native owner job on the separately frozen current 24-stock panel.

This is an authorized retrospective engineering variant, not a natural delivery,
new provider request, formal trial or funding operation. The ordinary submit and
worker paths own protocol/validation/qualification; this adapter only supplies
the existing hash-bound snapshot contract and fixed owner recipe references.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from quant_system.research.admission_qualifier import CONTROL_SYMBOLS, CURRENT_MANIFEST_SHA

ROOT = Path(__file__).resolve().parents[1]
EXPRESSION = "(($close/Ref($close,5))-1)"
CANDIDATE_SHA = "c2c74bafe7c3e32599686064fc576fee3ec4ac2510b0a73d3003c036309f2229"
LEDGER_SHA = "cb4f3939bd350636037a2c83d49447c5c17209e5770f4d3d71390cc4827f5628"


def require_project_python():
    if sys.version_info[:2] == (3, 11):
        return
    common = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"], cwd=ROOT, text=True
        ).strip()
    )
    main = (common if common.is_absolute() else ROOT / common).resolve().parent
    command = shlex.join(
        [str(main / ".venv/bin/python"), str(Path(__file__).resolve()), *sys.argv[1:]]
    )
    raise RuntimeError(
        "owner_example_requires_python_3_11; no owner/job was created. Run: "
        f"PYTHONPATH={shlex.quote(str(ROOT / 'src'))} {command}"
    )


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
    path.chmod(0o600)


def make_proposal(candidate, *, retrieved_at):
    original = candidate["proposal"]
    if original["expression"] != EXPRESSION:
        raise ValueError("owner_example_expression_changed")
    return {
        "schema_version": 1,
        "proposal_id": "phase2-current-24-monthly-top5-engineering-20260920-v1",
        "source_title": "Authorized local 24-stock monthly Top5 engineering variant",
        "source_urls": original["source_urls"],
        "published_at": None,
        "retrieved_at": retrieved_at,
        "hypothesis": "Fixed five-session close momentum engineering check; no alpha claim.",
        "expression": EXPRESSION,
        "adaptation_note": (
            "A new engineering variant: the previously frozen five-session expression is "
            "applied to the explicitly frozen 24-stock monthly Top5 contract. It is not the "
            "original four-stock candidate identity, an external publication, or a natural "
            "Grok/Hermes delivery. Source URL describes the data interface only. Saved Futu "
            "QFQ is retrospective, with historical PIT/vintage and survivor limits retained."
        ),
        "baseline_factor_ids": [],
        "strategy_spec": {
            "symbols": list(CONTROL_SYMBOLS),
            "benchmark_symbol": "SPY",
            "rebalance": "monthly",
            "top_n": 5,
            "normalization": "rank",
            "selection": "top",
            "max_weight_per_symbol": 1.0,
            "target_gross_exposure": 1.0,
            "min_order_value": 0.0,
            "factor_weights": {},
        },
    }


def isolated_settings(output):
    from quant_system.config.settings import (
        DatabaseSettings,
        DataSettings,
        PaperAccountSettings,
        SafetySettings,
        Settings,
    )

    output = Path(output).resolve()
    if not any(
        output.is_relative_to(p.resolve())
        for p in (ROOT / "artifacts", Path(tempfile.gettempdir()))
    ):
        raise ValueError("owner_example_output_not_isolated")
    return Settings(
        _env_file=None,
        environment="test",
        data=DataSettings(
            data_dir=output / "data",
            parquet_dir=output / "data/parquet",
            duckdb_path=output / "data/unused.duckdb",
            reports_dir=output / "reports",
        ),
        database=DatabaseSettings(_env_file=None, enabled=False, url=None, auto_migrate=False),
        paper_account=PaperAccountSettings(
            _env_file=None, db_mode="file", auto_process_pending_orders_enabled=False
        ),
        safety=SafetySettings(
            _env_file=None,
            live_trading_enabled=False,
            paper_observation_enabled=False,
            dry_run=True,
            paper_trading=True,
            kill_switch=True,
        ),
    )


def install_family_references(settings, snapshot):
    """Copy checked archival inputs, never make a formal archive writable via symlink."""
    snapshot = Path(snapshot)
    provenance = json.loads((snapshot / "snapshot-provenance.json").read_text())
    for relative, info in provenance["files"].items():
        target = settings.data.data_dir / relative
        if (
            Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or Path(relative).parts[0] not in {"strategy_library", "strategy_studies"}
        ):
            raise ValueError("owner_example_family_path_invalid")
        source = Path(info["original_path"])
        if sha(source) != info["sha256"]:
            raise ValueError("owner_example_family_source_changed")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ValueError("owner_example_reference_destination_exists")
        shutil.copyfile(source, target)
        target.chmod(0o600)


def prepare_native_job(
    settings,
    proposal,
    prices_path,
    manifest,
    provenance,
    *,
    expected_code,
    initialize=True,
):
    import exchange_calendars as xc

    from quant_system.research import admission_v2
    from quant_system.research import external_intake as intake
    from quant_system.research.intake_evaluation import digest, validate_snapshot

    if admission_v2.code_identity()["digest"] != expected_code:
        raise ValueError("owner_example_code_changed")
    directory = settings.data.data_dir / "research_intake"
    if initialize:
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        write_json(
            directory / "policy.json",
            intake.IntakePolicy(
                enabled=True, auto_enable=False, admission_mode="parallel"
            ).model_dump(),
        )
    policy = intake.read_policy(settings)
    if not policy.enabled or policy.auto_enable or policy.admission_mode != "parallel":
        raise ValueError("owner_example_policy_must_remain_research_only")
    submission = intake.submit(settings, proposal)
    job = intake._load_job(settings, submission["job_id"])
    expected_mode = "parallel" if initialize else "authoritative"
    if job["admission_protocol"]["mode"] != expected_mode:
        raise ValueError("owner_example_native_activation_not_consumed")
    # Preserve the native requested window and protocol. A weekend end may
    # differ from the panel's original request while selecting exactly the same
    # sessions; the distinct request remains bound in this evaluation identity.
    native_start = job["plans"][0]["origin"]["start"]
    native_end = job["plans"][0]["origin"]["end"]
    if any(
        plan["origin"]["start"] != manifest["requested_start"]
        or plan["origin"]["end"] != native_end
        for plan in job["plans"]
    ):
        raise ValueError("owner_example_native_requested_window_changed")
    calendar = xc.get_calendar(
        "XNYS",
        start=datetime.fromisoformat(native_start) - timedelta(days=7),
        end=datetime.fromisoformat(max(native_end, manifest["requested_end"])) + timedelta(days=7),
    )
    if not calendar.sessions_in_range(native_start, native_end).equals(
        calendar.sessions_in_range(manifest["requested_start"], manifest["requested_end"])
    ):
        raise ValueError("owner_example_native_requested_window_changed")
    frozen = directory / "evaluations" / job["job_id"]
    frozen.mkdir(parents=True)
    path = frozen / "prices.parquet"
    shutil.copyfile(prices_path, path)
    path.chmod(0o600)
    evaluation = {
        "job_id": job["job_id"],
        "plans_sha256": job["plans_sha256"],
        "prices_path": str(path.resolve()),
        "prices_sha256": sha(path),
        "start": native_start,
        "end": native_end,
        "symbols": [*CONTROL_SYMBOLS, "SPY"],
        "cash": 10000,
        "commission_bps": 1,
        "slippage_bps": 5,
        "frozen_input_provenance": provenance,
    }
    evaluation["evaluation_id"] = "evaluation-" + digest(evaluation)
    validate_snapshot(settings, evaluation)
    write_json(frozen / "snapshot.json", evaluation)
    return job, evaluation


def finish_receipt(output, receipt):
    output = Path(output)
    receipt["finished_at"] = datetime.now(UTC).isoformat()
    write_json(output / "receipt.json", receipt)
    files = {
        str(p.relative_to(output)): sha(p)
        for p in output.rglob("*")
        if p.is_file() and p != output / "artifact-manifest.json"
    }
    write_json(output / "artifact-manifest.json", {"files": files})


def review_stage_and_prepare_new(
    settings, *, historical_inventory, proposal, prices_path, manifest, provenance, expected_code
):
    """Use the fixed owner reviewer, then let native submit consume its actual state."""
    from quant_system.research.admission_activation import review_and_activate

    stage = review_and_activate(settings, historical_inventory=historical_inventory, activate=True)
    if stage["status"] != "activated":
        return {"stage": stage}
    next_proposal = copy.deepcopy(proposal)
    next_proposal["proposal_id"] += "-post-stage"
    next_proposal["retrieved_at"] = datetime.now(UTC).isoformat()
    next_proposal["adaptation_note"] += (
        " Same-formula post-stage engineering replay, not another discovered alpha. "
        "The original parallel job and protocol are retained unchanged."
    )
    job, evaluation = prepare_native_job(
        settings,
        next_proposal,
        prices_path,
        manifest,
        provenance,
        expected_code=expected_code,
        initialize=False,
    )
    return {"stage": stage, "proposal": next_proposal, "job": job, "evaluation": evaluation}


def run_example(
    *, candidate_path, manifest_path, recipes_path, expected_code, historical_inventory=None
):
    require_project_python()
    from quant_system.execution import assistant_remote
    from quant_system.research import admission_v2
    from quant_system.research import external_intake as intake
    from quant_system.research import strategy_library as library
    from quant_system.research.admission_consumer_checks import PEER_DIGEST
    from quant_system.research.admission_qualification_flow import read_recipes

    if admission_v2.code_identity()["digest"] != expected_code:
        raise ValueError("owner_example_code_changed")
    candidate_path, manifest_path, recipes_path = map(
        Path, (candidate_path, manifest_path, recipes_path)
    )
    if sha(candidate_path) != CANDIDATE_SHA:
        raise ValueError("owner_example_parent_candidate_changed")
    spec = importlib.util.spec_from_file_location(
        "fixed_current_input_reader", ROOT / "scripts/prepare_current_phase2_inputs.py"
    )
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    _prices, manifest = reader.read_frozen_inputs(manifest_path, CURRENT_MANIFEST_SHA)
    recipes = json.loads(recipes_path.read_text())
    if Path(recipes["recipes"]["data"]["source_root"]).resolve() != manifest_path.parent.resolve():
        raise ValueError("owner_example_recipe_input_mismatch")
    consumer = recipes["recipes"]["consumer"]
    ledger_path = Path(consumer["random_root"]) / "families/source-trials.jsonl"
    if sha(ledger_path) != LEDGER_SHA:
        raise ValueError("owner_example_family_ledger_changed")
    peer_path = Path(consumer["peer_snapshot_path"])
    peers = json.loads(peer_path.read_text())
    _, peer_identity = admission_v2.peer_snapshot(peers)
    if peer_identity["digest"] != PEER_DIGEST:
        raise ValueError("owner_example_reference_peer_changed")
    family_provenance = Path(consumer["data_root"]) / "snapshot-provenance.json"
    family_files = json.loads(family_provenance.read_text())["files"]
    original_files = [
        candidate_path,
        manifest_path,
        recipes_path,
        ledger_path,
        peer_path,
        family_provenance,
        *[Path(info["original_path"]) for info in family_files.values()],
        *[Path(row["source_path"]) for row in peers["candidates"]],
    ]
    if historical_inventory is not None:
        historical_inventory = Path(historical_inventory).resolve()
        original_files.append(historical_inventory)
    before = {str(path.resolve()): sha(path) for path in original_files}
    artifacts = ROOT / "artifacts/phase2-current-owner-20260920"
    artifacts.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="attempt-", dir=artifacts))
    settings = isolated_settings(output)
    receipt = {
        "schema": "isolated_current_owner_example/v1",
        "status": "running",
        "admission_outcome": "unknown",
        "output_dir": str(output),
        "started_at": datetime.now(UTC).isoformat(),
        "code_digest": expected_code,
        "admission_mode": "native_derived_no_policy_switch",
        "stage_requested": historical_inventory is not None,
        "stage_scope": "isolated_engineering_not_formal_activation",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "script_sha256": sha(__file__),
        "input_hashes_before": before,
        "formal_queue_submitted": False,
        "formal_trial_writes": 0,
        "capital_allocated": 0,
        "natural_delivery": False,
        "provider_requests": 0,
        "hermes_session_id": None,
        "hermes_run_id": None,
        "capital_authorized": False,
        "limits": [
            "Retrospective static24, not independently complete historical PIT.",
            "Reference-only historical40 trial rows and real2 peer returns are copied; "
            "no sleeves/accounts are installed.",
            "The ordinary validator retains its added trial and all failures; no family trimming.",
            "Not the original four-symbol candidate or a natural Grok/Hermes delivery.",
            "Any 10000 USD field is replay initial cash, never allocated capital.",
        ],
    }
    write_json(output / "receipt.json", receipt)
    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append("provider_or_funding_attempt")
        raise RuntimeError("owner_example_forbids_provider_and_funding")

    try:
        install_family_references(settings, consumer["data_root"])
        (settings.data.data_dir / "trials").mkdir(parents=True)
        shutil.copyfile(ledger_path, settings.data.data_dir / "trials/trials.jsonl")
        write_json(
            settings.data.data_dir / "assistant_remote/book.json",
            {
                "contract": assistant_remote.BOOK_CONTRACT,
                "reference_only_engineering_fixture": True,
                "candidates": peers["candidates"],
                "requests": [],
            },
        )
        proposal = make_proposal(
            json.loads(candidate_path.read_text()), retrieved_at=datetime.now(UTC).isoformat()
        )
        provenance = {
            "adapter": "approved_frozen_futu_qfq_bytes/v1",
            "provider": "futu",
            "delivery": "saved_files_not_new_vendor_request",
            "manifest_sha256": CURRENT_MANIFEST_SHA,
            "manifest_path": str(manifest_path.resolve()),
            "parent_candidate_sha256": CANDIDATE_SHA,
            "historical_pit_verified": False,
            "corporate_action_vintage_verified": False,
            "universe_mode": "explicit_static_24_symbols",
            "knowledge_ts": "retained_from_saved_bars",
        }
        write_json(output / "proposal.json", proposal)
        write_json(output / "input-provenance.json", provenance)
        with (
            patch.object(library, "_collect_prices", forbidden),
            patch.object(library, "enable_strategy", forbidden),
        ):
            job, evaluation = prepare_native_job(
                settings,
                proposal,
                manifest_path.parent / "prices.parquet",
                manifest,
                provenance,
                expected_code=expected_code,
            )
            write_json(
                settings.data.data_dir / "research_intake/admission_v2/recipes.json", recipes
            )
            read_recipes(settings)
            receipt.update(
                job_id=job["job_id"], evaluation=evaluation, protocol=job["admission_protocol"]
            )
            write_json(output / "receipt.json", receipt)
            receipt["intake_outcome"] = intake.run_once(settings)
            parallel = intake._load_job(settings, job["job_id"])
            write_json(output / "parallel-intake-job.json", parallel)
            receipt["parallel_job_id"] = job["job_id"]
            receipt["parallel_protocol"] = job["admission_protocol"]
            receipt["parallel_intake_outcome"] = receipt["intake_outcome"]
            parallel_path = (
                settings.data.data_dir / "research_intake/jobs" / f"{job['job_id']}.json"
            )
            parallel_sha = sha(parallel_path)
            policy_path = settings.data.data_dir / "research_intake/policy.json"
            policy_sha = sha(policy_path)
            if historical_inventory is not None:
                following = review_stage_and_prepare_new(
                    settings,
                    historical_inventory=historical_inventory,
                    proposal=proposal,
                    prices_path=manifest_path.parent / "prices.parquet",
                    manifest=manifest,
                    provenance=provenance,
                    expected_code=expected_code,
                )
                receipt["stage_review"] = following["stage"]
                write_json(output / "stage-review.json", following["stage"])
                if "job" in following:
                    job, evaluation = following["job"], following["evaluation"]
                    write_json(output / "post-stage-proposal.json", following["proposal"])
                    receipt.update(
                        job_id=job["job_id"],
                        evaluation=evaluation,
                        protocol=job["admission_protocol"],
                    )
                    write_json(output / "receipt.json", receipt)
                    receipt["intake_outcome"] = intake.run_once(settings)
            if sha(parallel_path) != parallel_sha or sha(policy_path) != policy_sha:
                raise AssertionError("owner_example_original_parallel_or_policy_changed")
        terminal = intake._load_job(settings, job["job_id"])
        write_json(output / "terminal-intake-job.json", terminal)
        receipt.update(
            status="completed",
            results=terminal["results"],
            job_status=terminal["status"],
            admission_outcome=receipt["intake_outcome"].get("outcome", "unknown"),
        )
        current_book = assistant_remote.load_book(settings)
        new_rows = [
            r
            for r in current_book["candidates"]
            if r["candidate_id"] not in {p["candidate_id"] for p in peers["candidates"]}
        ]
        if any(r.get("status") == "hung" or r.get("sleeve_id") for r in new_rows):
            raise AssertionError("owner_example_unexpected_activation")
        if (settings.data.data_dir / "api_runs").exists():
            raise AssertionError("owner_example_unexpected_account_or_sleeve_state")
        receipt["new_isolated_candidate_records"] = len(new_rows)
        receipt["isolated_trial_rows"] = len(
            (settings.data.data_dir / "trials/trials.jsonl").read_text().splitlines()
        )
    except Exception as exc:
        receipt.update(
            status="failed", admission_outcome="unknown", error=f"{type(exc).__name__}: {exc}"
        )
    receipt["forbidden_calls"] = forbidden_calls
    receipt["input_hashes_after"] = {str(path.resolve()): sha(path) for path in original_files}
    receipt["source_inputs_unchanged"] = before == receipt["input_hashes_after"]
    receipt["code_unchanged"] = admission_v2.code_identity()["digest"] == expected_code
    try:
        reader.read_frozen_inputs(manifest_path, CURRENT_MANIFEST_SHA)
    except Exception as exc:
        receipt.update(status="failed", admission_outcome="unknown", input_recheck_error=str(exc))
    if forbidden_calls or not receipt["source_inputs_unchanged"] or not receipt["code_unchanged"]:
        receipt.update(status="failed", admission_outcome="unknown")
    finish_receipt(output, receipt)
    return receipt


def snapshot_current_owner(source_root, settings):
    """Copy the complete trial population and its canonical archived inputs.

    This snapshot is separate from the frozen 39-member calibration population.
    A concurrent source change refuses the snapshot before any research starts.
    """
    from quant_system.execution import assistant_remote

    source_root = Path(source_root).resolve()
    target = settings.data.data_dir
    if target.is_relative_to(source_root) or source_root.is_relative_to(target):
        raise ValueError("owner_snapshot_must_be_isolated")
    ledger, book = source_root / "trials/trials.jsonl", source_root / "assistant_remote/book.json"
    before = {str(path): sha(path) for path in (ledger, book)}
    source_files = {ledger, book}
    original_book = json.loads(book.read_text())
    for candidate in original_book["candidates"]:
        if not candidate.get("source_path"):
            continue
        source = Path(candidate["source_path"])
        expected = candidate.get("source_digest") or candidate.get("candidate_code_digest")
        if (
            source.is_symlink()
            or not source.resolve().is_relative_to(source_root)
            or not source.is_file()
            or sha(source) != expected
        ):
            raise ValueError("owner_snapshot_candidate_source_unbound")
        source_files.add(source.resolve())
    for pattern in (
        "strategy_library/*/*.json",
        "strategy_library/*/validations/*/*",
        "strategy_studies/runs/*/report.json",
        "strategy_studies/runs/*/prices.parquet",
    ):
        source_files.update(path for path in source_root.glob(pattern) if path.is_file())
    copied = {}
    for source in sorted(source_files):
        if source.is_symlink():
            raise ValueError("owner_snapshot_source_symlink")
        identity = sha(source)
        destination = target / source.relative_to(source_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(0o600)
        if sha(destination) != identity or sha(source) != identity:
            raise ValueError("owner_snapshot_source_changed")
        copied[str(source.relative_to(source_root))] = {"source": str(source), "sha256": identity}
    after = {str(path): sha(path) for path in (ledger, book)}
    if before != after:
        raise ValueError("owner_snapshot_population_changed_before_research")
    # Local references retain the original bytes and identities while avoiding
    # dependence on writable formal paths in subsequent isolated execution.
    local_book = json.loads((target / "assistant_remote/book.json").read_text())
    for candidate in local_book["candidates"]:
        if candidate.get("source_path"):
            source = Path(candidate["source_path"]).resolve()
            if source.is_relative_to(source_root):
                destination = target / source.relative_to(source_root)
                if not destination.exists() or sha(destination) != sha(source):
                    raise ValueError("owner_snapshot_candidate_source_not_copied")
                candidate["source_path"] = str(destination)
            else:
                raise ValueError("owner_snapshot_candidate_source_outside_owner")
    assistant_remote.save_book(settings, local_book)
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "formal_hashes_before": before,
        "formal_hashes_after": after,
        "files": copied,
        "trial_rows": len((target / "trials/trials.jsonl").read_text().splitlines()),
        "scope": "complete_current_owner_population_not_the_historical_calibration_family",
    }


def run_saved_job_example(
    *, source_job, manifest_path, recipes_path, expected_code, historical_inventory=None
):
    """One existing proposal in an isolated current owner, with no formal submission."""
    require_project_python()
    from quant_system.research import admission_dataset_20260924 as dataset
    from quant_system.research import admission_v2
    from quant_system.research import external_intake as intake
    from quant_system.research import strategy_library as library
    from quant_system.research.admission_qualifier import SEPTEMBER24_MANIFEST_SHA

    source_job, manifest_path, recipes_path = map(Path, (source_job, manifest_path, recipes_path))
    if (
        sha(source_job) != dataset.JOB_SHA
        or admission_v2.code_identity()["digest"] != expected_code
    ):
        raise ValueError("owner_saved_job_or_current_code_changed")
    _, manifest = dataset.read_frozen_inputs(manifest_path, SEPTEMBER24_MANIFEST_SHA)
    recipes = json.loads(recipes_path.read_text())
    if (
        recipes["recipes"]["data"]["dataset"] != dataset.DATASET
        or Path(recipes["recipes"]["data"]["source_root"]).resolve()
        != manifest_path.parent.resolve()
        or recipes["recipes"]["consumer"].get("control_version") != dataset.DATASET
    ):
        raise ValueError("owner_saved_job_recipe_scope_mismatch")
    original = json.loads(source_job.read_text())
    if original["proposal"].get("upgrade_target"):
        raise ValueError("owner_saved_job_requires_independent_proposal")
    root = ROOT / "artifacts/phase3-current-owner-20260925"
    root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="attempt-", dir=root))
    settings = isolated_settings(output)
    receipt = {
        "schema": "isolated_existing_proposal_current_owner/v1",
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "output_dir": str(output),
        "source_job_id": original["job_id"],
        "source_job_sha256": sha(source_job),
        "code_digest": expected_code,
        "script_sha256": sha(__file__),
        "provider_requests": 0,
        "formal_queue_submitted": False,
        "capital_allocated": 0,
        "capital_authorized": False,
        "natural_delivery": False,
        "scope": "existing_proposal_current_code_engineering_not_new_alpha",
    }
    write_json(output / "receipt.json", receipt)
    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append("provider_or_funding_attempt")
        raise RuntimeError("owner_example_forbids_provider_and_funding")

    try:
        snapshot = snapshot_current_owner(source_job.resolve().parents[2], settings)
        write_json(output / "current-owner-source-snapshot.json", snapshot)
        receipt["current_owner_snapshot"] = {
            "path": str(output / "current-owner-source-snapshot.json"),
            "sha256": sha(output / "current-owner-source-snapshot.json"),
            "trial_rows": snapshot["trial_rows"],
        }
        write_json(output / "original-proposal.json", original["proposal"])
        proposal = copy.deepcopy(original["proposal"])
        proposal["proposal_id"] = "phase3-20260924-existing-" + dataset.JOB_SHA[:20]
        provenance = {
            "adapter": "existing_intake_frozen_same_bytes/v1",
            "manifest_sha256": SEPTEMBER24_MANIFEST_SHA,
            "source_job_sha256": dataset.JOB_SHA,
            "historical_pit_verified": False,
            "corporate_action_vintage_verified": False,
        }
        with (
            patch.object(library, "_collect_prices", forbidden),
            patch.object(library, "enable_strategy", forbidden),
        ):
            job, _ = prepare_native_job(
                settings,
                proposal,
                manifest_path.parent / "prices.parquet",
                manifest,
                provenance,
                expected_code=expected_code,
            )
            write_json(
                settings.data.data_dir / "research_intake/admission_v2/recipes.json", recipes
            )
            receipt["parallel_outcome"] = intake.run_once(settings)
            receipt["parallel_job_id"] = job["job_id"]
            parallel_path = intake._job_path(settings, job["job_id"])
            original_parallel_sha = sha(parallel_path)
            write_json(
                output / "parallel-intake-job.json", intake._load_job(settings, job["job_id"])
            )
            if historical_inventory:
                following = review_stage_and_prepare_new(
                    settings,
                    historical_inventory=historical_inventory,
                    proposal=proposal,
                    prices_path=manifest_path.parent / "prices.parquet",
                    manifest=manifest,
                    provenance=provenance,
                    expected_code=expected_code,
                )
                receipt["stage_review"] = following["stage"]
                if "job" in following:
                    job = following["job"]
                    receipt["post_stage_outcome"] = intake.run_once(settings)
            if sha(parallel_path) != original_parallel_sha:
                raise ValueError("owner_original_parallel_job_changed")
        terminal = intake._load_job(settings, job["job_id"])
        write_json(output / "terminal-intake-job.json", terminal)
        receipt["terminal_job_id"] = terminal["job_id"]
        receipt["terminal_job_status"] = terminal["status"]
        receipt["status"] = "completed"
        receipt["isolated_trial_rows"] = len(
            (settings.data.data_dir / "trials/trials.jsonl").read_text().splitlines()
        )
        if (settings.data.data_dir / "api_runs").exists() or forbidden_calls:
            raise ValueError("owner_example_unexpected_account_or_provider_state")
        dataset.read_frozen_inputs(manifest_path, SEPTEMBER24_MANIFEST_SHA)
        if admission_v2.code_identity()["digest"] != expected_code:
            raise ValueError("owner_example_code_changed")
    except Exception as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    receipt["forbidden_calls"] = forbidden_calls
    finish_receipt(output, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--candidate", type=Path)
    source.add_argument("--source-intake-job", type=Path)
    parser.add_argument("--input-manifest", required=True, type=Path)
    parser.add_argument("--recipes", required=True, type=Path)
    parser.add_argument("--expected-code", required=True)
    parser.add_argument("--historical-inventory", type=Path)
    args = parser.parse_args(argv)
    operation = run_saved_job_example if args.source_intake_job else run_example
    result = operation(
        **(
            {"source_job": args.source_intake_job}
            if args.source_intake_job
            else {"candidate_path": args.candidate}
        ),
        manifest_path=args.input_manifest,
        recipes_path=args.recipes,
        expected_code=args.expected_code,
        historical_inventory=args.historical_inventory,
    )
    if args.source_intake_job:
        print(
            json.dumps(
                {
                    key: result.get(key)
                    for key in (
                        "status",
                        "output_dir",
                        "code_digest",
                        "terminal_job_id",
                        "terminal_job_status",
                        "error",
                        "provider_requests",
                        "formal_queue_submitted",
                        "capital_allocated",
                    )
                },
                allow_nan=False,
            )
        )
    else:
        print(json.dumps(result, allow_nan=False))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
