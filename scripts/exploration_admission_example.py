"""ONE isolated engineering replay of an existing frozen exploration candidate.

No formal first submission, provider requests, paper capital or live authority.
Uses the unchanged intake and Platform/Qlib validators against a preinstalled
hash-bound input snapshot. Results, including failures, remain under artifacts.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

SYMBOLS = ["AAPL", "MSFT", "NVDA", "SPY"]
START, END, HISTORY_START = "2018-01-01", "2026-09-18", "2015-01-01"
ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen_prices(files: list[dict]) -> pd.DataFrame:
    """Read only original Futu QFQ bytes; no fetching, fallback or filling."""
    if [item["symbol"] for item in files] != SYMBOLS:
        raise ValueError("example_fixed_universe_mismatch")
    frames = []
    for item in files:
        path = Path(item["path"])
        metadata = path.with_suffix(".metadata.json")
        if sha(path) != item["sha256"] or sha(metadata) != item["metadata_sha256"]:
            raise ValueError("example_frozen_price_digest_mismatch")
        meta = json.loads(metadata.read_text())
        if any(
            meta.get(k) != v
            for k, v in {
                "symbol": item["symbol"],
                "source": "futu",
                "adjustment": "futu_qfq",
                "sha256": item["sha256"],
            }.items()
        ):
            raise ValueError("example_frozen_price_metadata_mismatch")
        frame = pd.read_parquet(path)
        if any(
            set(frame[k]) != {v}
            for k, v in {
                "symbol": item["symbol"],
                "provider": "futu",
                "interval": "1d",
                "price_adjustment": "qfq",
            }.items()
        ):
            raise ValueError("example_frozen_price_identity_mismatch")
        frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
        if frame.timestamp.duplicated().any() or not frame.timestamp.is_monotonic_increasing:
            raise ValueError("example_frozen_price_calendar_invalid")
        values = frame[["open", "high", "low", "close", "volume"]].to_numpy(float)
        if not np.isfinite(values).all() or (values[:, :4] <= 0).any() or (values[:, 4] < 0).any():
            raise ValueError("example_frozen_price_values_invalid")
        frames.append(frame)
    if any(not frames[0].timestamp.equals(frame.timestamp) for frame in frames[1:]):
        raise ValueError("example_frozen_price_calendar_mismatch")
    return pd.concat(frames, ignore_index=True).sort_values(["timestamp", "symbol"])


def verify_candidate(path: Path) -> tuple[dict, dict]:
    """Recheck the real sibling sandbox receipt; local self-digests alone are insufficient."""
    from quant_system.research.exploration_admission import prepare_exploration_candidate
    from quant_system.research.exploration_sandbox import digest

    candidate = json.loads(path.read_text())
    if candidate.get("candidate_digest") != digest(
        {k: v for k, v in candidate.items() if k != "candidate_digest"}
    ):
        raise ValueError("example_candidate_digest_mismatch")
    proposal = candidate["proposal"]
    if (
        proposal["strategy_spec"]["symbols"] != SYMBOLS
        or proposal["expression"] != "(($close/Ref($close,5))-1)"
        or candidate.get("queue_submitted") is not False
        or candidate.get("capital_authorized") is not False
    ):
        raise ValueError("example_frozen_scope_mismatch")
    source_material = {
        k: proposal[k]
        for k in (
            "source_urls",
            "source_title",
            "published_at",
            "retrieved_at",
            "hypothesis",
            "adaptation_note",
        )
    }
    revalidated = prepare_exploration_candidate(
        path.parent / "run",
        source_material=source_material,
        ordered_symbols=SYMBOLS,
        data_provenance=candidate["binding"]["data_provenance"],
    )
    # A newer strict parser may be inspected, but neither proposal nor any
    # sandbox/source binding may be changed. Save both envelopes in the example.
    exclude = {"candidate_digest", "intake_schema_validation"}
    if {k: v for k, v in candidate.items() if k not in exclude} != {
        k: v for k, v in revalidated.items() if k not in exclude
    }:
        raise ValueError("example_sandbox_revalidation_mismatch")
    return candidate, revalidated


def isolated_settings(output: Path):
    from quant_system.config.settings import (
        DatabaseSettings,
        DataSettings,
        PaperAccountSettings,
        SafetySettings,
        Settings,
    )

    output = output.resolve()
    if not any(
        output.is_relative_to(p.resolve())
        for p in (
            ROOT / "artifacts",
            Path(tempfile.gettempdir()),
        )
    ):
        raise ValueError("example_output_not_isolated")
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
            _env_file=None,
            db_mode="file",
            auto_process_pending_orders_enabled=False,
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


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    path.chmod(0o600)


def prepare_intake(settings, proposal: dict, prices: pd.DataFrame, provenance: dict):
    """Install one explicit frozen snapshot using the existing intake contract."""
    from quant_system.research import external_intake as intake
    from quant_system.research.intake_evaluation import digest, validate_snapshot

    directory = settings.data.data_dir / "research_intake"
    directory.mkdir(parents=True, exist_ok=False)
    directory.chmod(0o700)
    write_json(
        directory / "policy.json", intake.IntakePolicy(enabled=True, auto_enable=False).model_dump()
    )
    submission = intake.submit(settings, proposal)
    job = json.loads((directory / "jobs" / f"{submission['job_id']}.json").read_text())
    frozen = directory / "evaluations" / job["job_id"]
    frozen.mkdir(parents=True)
    path = frozen / "prices.parquet"
    prices.to_parquet(path, index=False)
    path.chmod(0o600)
    evaluation = {
        "job_id": job["job_id"],
        "plans_sha256": job["plans_sha256"],
        "prices_path": str(path.resolve()),
        "prices_sha256": sha(path),
        "start": START,
        "end": END,
        "symbols": SYMBOLS,
        "cash": 10000,
        "commission_bps": 1,
        "slippage_bps": 5,
        "frozen_input_provenance": provenance,
    }
    evaluation["evaluation_id"] = "evaluation-" + digest(evaluation)
    validate_snapshot(settings, evaluation)
    write_json(frozen / "snapshot.json", evaluation)
    return job, evaluation


def run_example(candidate_path: Path) -> dict:
    """One authorized engineering attempt, never a formal delivery or capital request."""
    from quant_system.execution import assistant_remote
    from quant_system.research import external_intake as intake
    from quant_system.research import strategy_library as library
    from quant_system.research.study_runtime import resolve_docker_executable

    candidate_path = candidate_path.resolve()
    candidate, revalidated = verify_candidate(candidate_path)
    files = candidate["binding"]["data_provenance"]["files"]
    prices = load_frozen_prices(files)
    prices = prices[
        prices.timestamp.between(pd.Timestamp(HISTORY_START, tz="UTC"), pd.Timestamp(END, tz="UTC"))
    ]
    # The window is fixed before seeing any strategy result, never tuned to pass.
    if prices.timestamp.nunique() < 2000:
        raise ValueError("example_frozen_history_insufficient")
    input_paths = [
        candidate_path,
        *[Path(item["path"]) for item in files],
        *[Path(item["path"]).with_suffix(".metadata.json") for item in files],
    ]
    before = {str(path): sha(path) for path in input_paths}
    artifacts = ROOT / "artifacts" / "phase2-exploration-admission-20260920"
    artifacts.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="attempt-", dir=artifacts))
    settings = isolated_settings(output)
    provenance = {
        "adapter": "frozen_futu_qfq_parquet_readonly/v1",
        "provider": "futu",
        "delivery": "previously_collected_files_not_new_vendor_request",
        "source_files": files,
        "source_candidate_sha256": sha(candidate_path),
        "price_history_start": HISTORY_START,
        "price_history_end": END,
        "historical_pit_verified": False,
        "corporate_action_vintage_verified": False,
        "universe_mode": "explicit_static_four_symbols",
    }
    write_json(output / "original-candidate.json", candidate)
    write_json(output / "revalidated-candidate.json", revalidated)
    write_json(output / "input-provenance.json", provenance)
    receipt = {
        "schema": "isolated_exploration_admission_example/v1",
        "status": "running",
        "scope": "retrospective_engineering_example_not_natural_delivery",
        "started_at": datetime.now(UTC).isoformat(),
        "output_dir": str(output),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "script_sha256": sha(Path(__file__)),
        "input_hashes_before": before,
        "window": {"start": START, "end": END, "history_start": HISTORY_START},
        "symbols": SYMBOLS,
        "expression": candidate["proposal"]["expression"],
        "policy": {"enabled": True, "auto_enable": False},
        "formal_queue_submitted": False,
        "natural_delivery": False,
        "capital_authorized": False,
        "capital_allocated": 0,
        "hermes_session_id": None,
        "hermes_run_id": None,
        "provider_requests": 0,
        "formal_state_writes": False,
        "limits": [
            "Four static symbols are not a broad-universe alpha qualification.",
            "Isolation starts with an empty trial family and no hung candidates; "
            "formal DSR/correlation context is not reproduced.",
            "Current saved QFQ is retrospective; historical publication times "
            "and adjustment vintages remain unverified.",
            "Any pipeline-generated Grok title is an existing intake label, "
            "not evidence of a Grok/Hermes session.",
            "Any 10000 USD field is the historical replay notional, never an allocation.",
        ],
    }
    write_json(output / "receipt.json", receipt)
    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append("provider_or_activation_attempt")
        raise RuntimeError("isolated_example_forbids_provider_and_activation")

    try:
        docker = resolve_docker_executable()
        image = subprocess.run(
            [docker, "image", "inspect", "hqa-qlib-evaluation:0.1.0", "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        receipt["qlib_image_id"] = image.stdout.strip()
        with (
            patch.object(library, "_collect_prices", forbidden),
            patch.object(library, "enable_strategy", forbidden),
        ):
            job, evaluation = prepare_intake(settings, candidate["proposal"], prices, provenance)
            receipt["job_id"] = job["job_id"]
            receipt["evaluation"] = evaluation
            write_json(output / "receipt.json", receipt)
            outcome = intake.run_once(settings)
            receipt["intake_outcome"] = outcome
            final_job = json.loads(
                (
                    settings.data.data_dir / "research_intake/jobs" / f"{job['job_id']}.json"
                ).read_text()
            )
            write_json(output / "terminal-intake-job.json", final_job)
        validations = list(
            (settings.data.data_dir / "strategy_library").glob("*/validations/*/validation.json")
        )
        if len(validations) == 1:
            validation = json.loads(validations[0].read_text())
            receipt.update(
                status="completed",
                admission_outcome="passed" if validation["status"] == "passed" else "rejected",
                validation_path=str(validations[0]),
                validation_sha256=sha(validations[0]),
                comparison=validation.get("comparison"),
                gates=validation.get("gates"),
                blockers=validation.get("blockers"),
            )
        else:
            receipt.update(
                status="partial",
                admission_outcome="unknown",
                error=final_job.get("error"),
                results=final_job.get("results"),
            )
        book = assistant_remote.load_book(settings)
        if any(row.get("status") == "hung" or row.get("sleeve_id") for row in book["candidates"]):
            raise AssertionError("isolated_example_unexpected_activation")
        receipt["isolated_candidate_records"] = len(book["candidates"])
    except Exception as exc:
        receipt.update(
            status="failed", admission_outcome="unknown", error=f"{type(exc).__name__}: {exc}"
        )
    receipt["forbidden_calls"] = forbidden_calls
    receipt["input_hashes_after"] = {str(path): sha(path) for path in input_paths}
    receipt["source_inputs_unchanged"] = before == receipt["input_hashes_after"]
    if forbidden_calls or not receipt["source_inputs_unchanged"]:
        receipt.update(status="failed", admission_outcome="unknown")
    receipt["finished_at"] = datetime.now(UTC).isoformat()
    write_json(output / "receipt.json", receipt)
    manifest = {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}
    write_json(output / "artifact-manifest.json", {"files": manifest})
    return receipt


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = run_example(args.candidate)
    print(json.dumps(receipt, ensure_ascii=False, allow_nan=False))
    return 0 if receipt["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
