"""Explicit artificial protocol originals; no market-data or money operations."""

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from quant_system.d34.docker_runtime import D34DockerReceipt
from quant_system.d34.market_data_snapshot import MarketDataSnapshotError
from quant_system.d34.platform_replay import run_platform_replay
from quant_system.d34.research_request import digest_document
from quant_system.execution.assistant_remote import AssistantRemoteError
from quant_system.research.capital_evidence import CurrentFamilyResolver
from quant_system.research.gate_v2.family import project_family_v2
from quant_system.research.registered_family_evidence import (
    CURVE,
    INTENT,
    census_registered_trials,
    commit_registered_trial,
    read_registered_trial,
    registered_producer_sources,
)
from quant_system.research.trials import TrialsLedger, universe_digest
from tests.test_registered_factor_verification import _Boundary, _settings, _verify


def produce(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34")
    candidate = _verify(settings, boundary)
    root = tmp_path / "_runtime/d34/jobs" / candidate["evidence_ref"]["job_id"]
    return settings, boundary, candidate, root


def test_real_writer_once_and_original_generic_family_reader(tmp_path, monkeypatch):
    settings, boundary, candidate, root = produce(tmp_path, monkeypatch)
    ledger = TrialsLedger(tmp_path / "trials")
    rows = ledger.list()
    assert len(rows) == 1 and rows[0].kind == "platform_backtest"
    before = ledger.path.read_bytes()
    assert _verify(settings, boundary) == candidate
    assert ledger.path.read_bytes() == before
    assert boundary.calls.count("platform-replay") == 1
    selected = read_registered_trial(tmp_path, root, rows)
    assert selected["producer_sources"] == registered_producer_sources()
    assert selected["loaded_process_attested"] is False
    assert [item["command"][0] for item in selected["producer_boundary_receipts"]] == [
        "qlib-adapt",
        "registered-verify",
    ]
    assert selected["raw_receipt_returns"] == boundary.returns
    assert selected["selected"] == pytest.approx(boundary.returns, abs=1e-12, rel=0)
    assert selected["comparison_accepted"] is True
    assert selected["contract"]["benchmark"] == {"symbol": None, "method": "none"}
    resolver = CurrentFamilyResolver(tmp_path, trusted_trials=rows)
    family = project_family_v2(
        trials_rows=rows,
        universe_digest=universe_digest(["SPY", "QQQ"]),
        compatibility_contract=selected["contract"],
        curve_resolver=resolver,
        legacy_resolver=resolver.legacy,
    )
    assert family["n_trials"] == 1 and family["excluded"] == []
    assert family["evidence_state"] == "insufficient_members"
    assert census_registered_trials(tmp_path, rows)["entries"][0]["status"] == "recorded"


def test_dual_engine_failure_retains_platform_trial_and_does_not_repeat(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34", divergent=True)
    for _ in range(2):
        with pytest.raises(AssistantRemoteError, match="registered_factor_dual_engine_rejected"):
            _verify(settings, boundary)
    rows = TrialsLedger(tmp_path / "trials").list()
    assert len(rows) == 1
    root = tmp_path / "_runtime/d34/jobs" / rows[0].metadata["registered_job_id"]
    result = read_registered_trial(tmp_path, root, rows)
    assert result["raw_receipt_returns"] == [-x for x in boundary.returns]
    assert result["selected"] == pytest.approx([-x for x in boundary.returns], abs=1e-12, rel=0)
    assert result["comparison_accepted"] is False
    assert boundary.calls.count("platform-replay") == 1
    assert not (tmp_path / "assistant_remote/book.json").exists()


def test_infrastructure_failure_preserved_zero_trial_then_same_input_can_recover(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34")
    fetch = boundary.fetch_ohlcv

    def fail(*args, **kwargs):
        raise OSError("artificial provider unavailable before evaluation")

    boundary.fetch_ohlcv = fail
    with pytest.raises(MarketDataSnapshotError) as unavailable:
        _verify(settings, boundary)
    assert unavailable.value.code == "snapshot_futu_unavailable"
    assert TrialsLedger(tmp_path / "trials").list() == []
    before = census_registered_trials(tmp_path, [])
    assert len(before["entries"]) == 1
    assert before["entries"][0]["status"] == "no_real_evaluation"
    failure = Path(before["entries"][0]["failure_receipt_path"])
    saved = failure.read_bytes()
    boundary.fetch_ohlcv = fetch
    _verify(settings, boundary)
    assert len(TrialsLedger(tmp_path / "trials").list()) == 1
    assert failure.read_bytes() == saved


def test_rename_then_ledger_write_failure_recovers_same_frozen_intent(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34")
    append = TrialsLedger.append

    def fail(self, row):
        raise OSError("artificial ledger unavailable")

    monkeypatch.setattr(TrialsLedger, "append", fail)
    with pytest.raises(OSError, match="ledger unavailable"):
        _verify(settings, boundary)
    intent = next((tmp_path / "_runtime/d34/jobs").glob("job-registered-*/" + INTENT))
    saved = intent.read_bytes()
    assert not (tmp_path / "trials/trials.jsonl").exists()
    monkeypatch.setattr(TrialsLedger, "append", append)
    _verify(settings, boundary)
    assert intent.read_bytes() == saved
    assert len(TrialsLedger(tmp_path / "trials").list()) == 1
    assert boundary.calls.count("platform-replay") == 1


def test_legacy_cached_originals_are_disclosed_without_automatic_backfill(tmp_path, monkeypatch):
    settings, boundary, _, root = produce(tmp_path, monkeypatch)
    # Construct a historical-format artificial fixture before invoking the reader.
    (root / INTENT).unlink()
    (root / CURVE).unlink()
    (tmp_path / "trials/trials.jsonl").unlink()
    before = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    _verify(settings, boundary)
    assert not (tmp_path / "trials/trials.jsonl").exists()
    census = census_registered_trials(tmp_path, [])
    assert census["entries"][0]["status"] == "unrecorded_real_evaluation"
    assert census["entries"][0]["contract"]["return_definition"] == "net_total_return"
    assert before == {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("target", ["curve", "intent", "raw", "ledger"])
def test_current_reader_rejects_missing_or_changed_originals(tmp_path, monkeypatch, target):
    _, _, _, root = produce(tmp_path, monkeypatch)
    rows = TrialsLedger(tmp_path / "trials").list()
    before = (tmp_path / "trials/trials.jsonl").read_bytes()
    if target == "curve":
        value = json.loads((root / CURVE).read_text())
        value["curve"].reverse()
        (root / CURVE).write_text(json.dumps(value))
    elif target == "intent":
        (root / INTENT).unlink()
    elif target == "raw":
        next((root / "platform-replay").rglob("receipt.json")).write_text("{}")
    else:
        rows = []
    with pytest.raises((OSError, ValueError)):
        read_registered_trial(tmp_path, root, rows)
    assert (tmp_path / "trials/trials.jsonl").read_bytes() == before


def test_duplicate_commit_rejects_changed_same_input_trial(tmp_path, monkeypatch):
    _, _, _, root = produce(tmp_path, monkeypatch)
    intent = json.loads((root / INTENT).read_text())
    intent["trial"]["metadata"]["invented_replacement_identity"] = True
    (root / INTENT).write_text(json.dumps(intent))
    before = (tmp_path / "trials/trials.jsonl").read_bytes()
    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        commit_registered_trial(tmp_path, root)
    assert (tmp_path / "trials/trials.jsonl").read_bytes() == before


def test_census_never_silently_drops_missing_manifest_or_uncommitted_trial(tmp_path, monkeypatch):
    _, _, _, root = produce(tmp_path, monkeypatch)
    rows = TrialsLedger(tmp_path / "trials").list()
    uncommitted = census_registered_trials(tmp_path, [])
    assert uncommitted["entries"][0]["status"] == "unrecorded_real_evaluation"
    (root / "manifest.json").unlink()
    missing = census_registered_trials(tmp_path, rows)
    assert len(missing["entries"]) == 1
    assert missing["entries"][0]["status"] == "unknown"
    assert missing["entries"][0]["universe_digest"] is None


def test_invalid_manifest_cannot_supply_foreign_universe_to_census(tmp_path, monkeypatch):
    _, _, _, root = produce(tmp_path, monkeypatch)
    rows = TrialsLedger(tmp_path / "trials").list()
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["universe"] = ["UNRELATED"]
    (root / "manifest.json").write_text(json.dumps(manifest))
    result = census_registered_trials(tmp_path, rows)["entries"][0]
    assert result["status"] == "unknown"
    assert result["universe_digest"] is None


def test_failure_boolean_cannot_erase_existing_platform_evaluation(tmp_path, monkeypatch):
    class MissingCostBoundary(_Boundary):
        def replay(self, **kwargs):
            result = super().replay(**kwargs)
            path = result.output_dir / "receipt.json"
            raw = json.loads(path.read_text())
            raw.pop("config")
            raw["receipt_digest"] = digest_document(
                {key: value for key, value in raw.items() if key != "receipt_digest"}
            )
            path.write_text(json.dumps(raw))
            return result

    settings = _settings(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="platform_cost_contract_unproven"):
        _verify(settings, MissingCostBoundary(tmp_path / "_runtime/d34"))
    path = next(
        (tmp_path / "_runtime/d34/jobs/registered-failures").glob("*/*/failure-receipt.json")
    )
    failure = json.loads(path.read_text())
    assert failure["stage"] == "family_recording" and failure["platform_receipt_present"] is True
    failure["platform_evaluation_attempted"] = False
    path.write_text(json.dumps(failure))
    result = census_registered_trials(tmp_path, [])["entries"][0]
    assert result["status"] == "unknown"


def test_target_weights_bytes_are_bound_to_registered_originals(tmp_path, monkeypatch):
    _, _, _, root = produce(tmp_path, monkeypatch)
    rows = TrialsLedger(tmp_path / "trials").list()
    target = next((root / "qlib-result").rglob("target_weights.parquet"))
    target.write_bytes(b"changed artificial target schedule")
    with pytest.raises(ValueError, match="original_changed"):
        read_registered_trial(tmp_path, root, rows)


def test_producer_file_identity_change_during_evaluation_prevents_trial_publication(
    tmp_path, monkeypatch
):
    from quant_system.research import admission_v2

    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34")
    fetch = boundary.fetch_ohlcv
    # Keep the actual source-hashing implementation. Only its filesystem input
    # is an isolated copy, so no project or installed file is changed.
    source_copy = tmp_path / "artificial-repo/src/quant_system"
    shutil.copytree(
        Path(admission_v2.__file__).parents[1],
        source_copy,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    docker_copy = source_copy.parents[1] / "docker/d34"
    docker_copy.mkdir(parents=True)
    shutil.copy2(
        Path(admission_v2.__file__).parents[3] / "docker/d34/container_entrypoint.py",
        docker_copy / "container_entrypoint.py",
    )
    scripts_copy = source_copy.parents[1] / "scripts"
    scripts_copy.mkdir()
    shutil.copy2(
        Path(admission_v2.__file__).parents[3] / "scripts/calibrate_admission_semantics.py",
        scripts_copy / "calibrate_admission_semantics.py",
    )
    monkeypatch.setattr(admission_v2, "_ROOT", source_copy)
    engine_source = source_copy / "backtest/engine.py"

    def changed_environment(*args, **kwargs):
        result = fetch(*args, **kwargs)
        engine_source.write_text(engine_source.read_text() + "\n# ARTIFICIAL disk identity drift\n")
        return result

    boundary.fetch_ohlcv = changed_environment
    with pytest.raises(AssistantRemoteError, match="registered_producer_sources_changed"):
        _verify(settings, boundary)
    assert TrialsLedger(tmp_path / "trials").list() == []
    census = census_registered_trials(tmp_path, [])
    assert census["entries"][0]["status"] == "unknown"
    assert not (tmp_path / "api_runs").exists()


def test_historical_original_reader_preserves_old_producer_without_current_relabelling(
    tmp_path, monkeypatch
):
    from quant_system.research import registered_family_evidence as evidence

    _, _, _, root = produce(tmp_path, monkeypatch)
    rows = TrialsLedger(tmp_path / "trials").list()
    before = read_registered_trial(tmp_path, root, rows)
    monkeypatch.setattr(evidence, "registered_producer_sources", lambda: {"digest": "f" * 64})
    after = read_registered_trial(tmp_path, root, rows)
    assert after["producer_sources"] == before["producer_sources"]
    assert after["producer_sources"] != evidence.registered_producer_sources()
    assert after["selected"] == before["selected"]


def test_legacy_exposure_is_read_only_without_new_intent_or_ledger(tmp_path, monkeypatch):
    from quant_system.research.registered_family_evidence import (
        ATTEMPT_INPUT,
        PRODUCER_IDENTITY,
        read_registered_exposure,
    )

    _, _, _, root = produce(tmp_path, monkeypatch)
    # Prepare an old-format artificial archive before either consumer reads it.
    for name in (INTENT, CURVE, ATTEMPT_INPUT, PRODUCER_IDENTITY):
        (root / name).unlink()
    (tmp_path / "trials/trials.jsonl").unlink()
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    exposure = read_registered_exposure(tmp_path, root)
    assert exposure["exposure_returns"] == exposure["total"] == exposure["selected"]
    assert len(exposure["exposure_dates"]) == len(exposure["total"]) == 240
    assert exposure["producer_sources"] is None
    assert exposure["source_files"]
    assert exposure["funding_authority"] is False
    assert exposure["purpose"] == "historical_registered_exposure_only"
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    # No fallback: the new-money reader still refuses the same old archive.
    with pytest.raises(FileNotFoundError):
        read_registered_trial(tmp_path, root, [])


@pytest.mark.parametrize("kind", ["raw", "snapshot"])
def test_legacy_exposure_does_not_ignore_original_tampering(tmp_path, monkeypatch, kind):
    from quant_system.research.registered_family_evidence import read_registered_exposure

    _, _, _, root = produce(tmp_path, monkeypatch)
    (root / INTENT).unlink()
    manifest = json.loads((root / "manifest.json").read_text())
    path = root / manifest["platform_receipt_path" if kind == "raw" else "snapshot_path"]
    path.write_bytes(b"changed original")
    with pytest.raises(ValueError, match="original_changed"):
        read_registered_exposure(tmp_path, root)


def test_resealed_foreign_manifest_must_match_original_request_engine_and_snapshot(
    tmp_path, monkeypatch
):
    from quant_system.research.registered_family_evidence import ATTEMPT_INPUT, PRODUCER_IDENTITY

    _, _, _, root = produce(tmp_path, monkeypatch)
    for name in (INTENT, CURVE, ATTEMPT_INPUT, PRODUCER_IDENTITY):
        (root / name).unlink()
    (tmp_path / "trials/trials.jsonl").unlink()
    (tmp_path / "assistant_remote/book.json").unlink()
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["universe"] = ["UNRELATED"]
    identity = {
        key: manifest[key]
        for key in (
            "contract",
            "factor_id",
            "factor_identity_digest",
            "source_digest",
            "universe",
            "market_session",
        )
    }
    digest = digest_document(identity)
    manifest.update(
        job_id="job-registered-" + digest[:32], run_id="attempt-registered-" + digest[:32]
    )
    manifest["manifest_digest"] = digest_document(
        {k: v for k, v in manifest.items() if k != "manifest_digest"}
    )
    (root / "manifest.json").write_text(json.dumps(manifest))
    changed = root.with_name(manifest["job_id"])
    root.rename(changed)
    result = census_registered_trials(tmp_path, [])["entries"][0]
    assert result["status"] == "unknown"
    assert result["universe_verified"] is False and result["universe_digest"] is None


def test_changed_snapshot_cannot_resolve_prior_evaluated_failure(tmp_path, monkeypatch):
    class MissingCost(_Boundary):
        def replay(self, **kwargs):
            result = super().replay(**kwargs)
            path = result.output_dir / "receipt.json"
            raw = json.loads(path.read_text())
            raw.pop("config")
            raw["receipt_digest"] = digest_document(
                {k: v for k, v in raw.items() if k != "receipt_digest"}
            )
            path.write_text(json.dumps(raw))
            return result

    class ChangedPrices(_Boundary):
        def fetch_ohlcv(self, *args, **kwargs):
            frame = super().fetch_ohlcv(*args, **kwargs)
            for key in ("open", "high", "low", "close"):
                frame[key] += 10
            return frame

    settings = _settings(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="platform_cost_contract_unproven"):
        _verify(settings, MissingCost(tmp_path / "_runtime/d34"))
    _verify(settings, ChangedPrices(tmp_path / "_runtime/d34"))
    rows = TrialsLedger(tmp_path / "trials").list()
    assert len(rows) == 1
    entries = census_registered_trials(tmp_path, rows)["entries"]
    failure = next(item for item in entries if item.get("failure_receipt_path"))
    assert failure["status"] == "unknown"


@pytest.mark.parametrize("change_prices", [False, True])
def test_evaluated_writer_io_failure_recovers_only_with_proven_same_inputs(
    tmp_path, monkeypatch, change_prices
):
    settings = _settings(tmp_path, monkeypatch)
    boundary = _Boundary(tmp_path / "_runtime/d34")
    original_open = Path.open

    def fail_curve_write(path, mode="r", *args, **kwargs):
        if path.name == CURVE and mode == "x":
            raise OSError("artificial curve publication unavailable")
        return original_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Path, "open", fail_curve_write)
        with pytest.raises(OSError, match="curve publication unavailable"):
            _verify(settings, boundary)
    before = census_registered_trials(tmp_path, [])["entries"][0]
    assert before["status"] == "unknown" and before["evaluation_input_identity"] is not None
    failure_path = Path(before["failure_receipt_path"])
    original_failure = failure_path.read_bytes()
    if change_prices:
        fetch = boundary.fetch_ohlcv

        def changed(*args, **kwargs):
            frame = fetch(*args, **kwargs)
            for column in ("open", "high", "low", "close"):
                frame[column] += 10
            return frame

        boundary.fetch_ohlcv = changed
    _verify(settings, boundary)
    rows = TrialsLedger(tmp_path / "trials").list()
    assert len(rows) == 1
    entries = census_registered_trials(tmp_path, rows)["entries"]
    success = next(item for item in entries if item["status"] == "recorded")
    prior = next(item for item in entries if item.get("failure_receipt_path"))
    assert (
        success["evaluation_input_identity"] == prior["evaluation_input_identity"]
    ) is not change_prices
    assert prior["status"] == ("unknown" if change_prices else "recovered_evaluation")
    assert failure_path.read_bytes() == original_failure


def test_actual_platform_engine_outputs_record_even_when_artificial_qlib_disagrees(
    tmp_path, monkeypatch
):
    class ActualPlatformBoundary(_Boundary):
        def run(self, *, job_id, command, timeout_seconds=None):
            receipt = super().run(job_id=job_id, command=command, timeout_seconds=timeout_seconds)
            if command[0] != "registered-verify":
                return receipt
            output = dict(receipt.output)
            target = self._host(output["target_weights_path"])
            request = self.requests[-1]
            pd.DataFrame(
                [
                    {
                        "tradeable_ts": pd.Timestamp(request["calendar"][0]),
                        "symbol": "SPY",
                        "target_weight": 1.0,
                    }
                ]
            ).to_parquet(target, index=False)
            output["target_weights_digest"] = hashlib.sha256(target.read_bytes()).hexdigest()
            raw_path = self._host(output["qlib_receipt_path"])
            raw = json.loads(raw_path.read_text())
            raw["target_weights_digest"] = output["target_weights_digest"]
            raw["receipt_digest"] = digest_document(
                {k: v for k, v in raw.items() if k != "receipt_digest"}
            )
            raw_path.write_text(json.dumps(raw))
            output["qlib_receipt_digest"] = raw["receipt_digest"]
            return D34DockerReceipt(
                contract=receipt.contract,
                job_id=job_id,
                image_ref=receipt.image_ref,
                image_digest=receipt.image_digest,
                command=receipt.command,
                output=output,
                receipt_digest=digest_document(output),
            )

        def replay(self, *, qlib_receipt, **kwargs):
            del qlib_receipt
            self.calls.append("actual-platform-replay")
            return run_platform_replay(**kwargs)

    settings = _settings(tmp_path, monkeypatch)
    boundary = ActualPlatformBoundary(tmp_path / "_runtime/d34")
    with pytest.raises(AssistantRemoteError, match="registered_factor_dual_engine_rejected"):
        _verify(settings, boundary)
    rows = TrialsLedger(tmp_path / "trials").list()
    assert len(rows) == 1 and boundary.calls.count("actual-platform-replay") == 1
    root = tmp_path / "_runtime/d34/jobs" / rows[0].metadata["registered_job_id"]
    selected = read_registered_trial(tmp_path, root, rows)
    assert selected["comparison_accepted"] is False
    assert selected["selected"] != boundary.returns
    assert selected["raw_receipt_returns"][0] == 0.0
    # Day-one open-to-close gains can exceed costs. Independently account for
    # the saved first day's fills instead of assuming net P&L must be negative.
    manifest = selected["manifest"]
    bars = pd.read_parquet(root / manifest["snapshot_path"])
    fills = pd.read_parquet(
        (root / manifest["platform_receipt_path"]).parent / "trade_blotter.parquet"
    )
    day = pd.Timestamp(selected["dates"][0], tz="UTC")
    closes = bars[bars.timestamp == day].set_index("symbol").close.to_dict()
    cash, positions, cost_drag = 100000.0, {}, 0.0
    for fill in fills[fills.timestamp == day].itertuples(index=False):
        sign = 1 if fill.side == "buy" else -1
        positions[fill.symbol] = positions.get(fill.symbol, 0.0) + sign * fill.quantity
        cash -= sign * fill.quantity * fill.fill_price + fill.commission
        cost_drag += (
            sign * fill.quantity * (fill.fill_price - fill.requested_price) + fill.commission
        )
    net = cash + sum(quantity * closes[symbol] for symbol, quantity in positions.items())
    assert cost_drag > 0
    assert selected["selected"][0] == pytest.approx(net / 100000.0 - 1, abs=1e-12, rel=0)
    assert selected["selected"][0] != selected["raw_receipt_returns"][0]
    assert selected["return_reconstruction"]["method"] == "initial_cash_then_original_equity/v1"
    assert selected["turnover"] > 0
