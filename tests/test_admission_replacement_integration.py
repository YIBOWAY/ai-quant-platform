"""Real gate/callback/lifecycle composition with explicitly sealed engine/producer inputs."""

import json
from pathlib import Path

import pytest

from quant_system.execution import assistant_remote as remote
from quant_system.execution import strategy_replacement as lifecycle
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.research import admission_v2 as admission
from quant_system.research import external_intake as intake
from quant_system.research import strategy_library as library
from tests import test_admission_v2_consumers as fixtures
from tests.gate_v2_fixtures import platform_result
from tests.test_admission_v2 import qualify
from tests.test_external_intake import proposal


@pytest.fixture
def context(tmp_path):
    return fixtures.context.__wrapped__(tmp_path)


@pytest.fixture(autouse=True)
def sealed_producer(monkeypatch):
    yield from fixtures.sealed_producer.__wrapped__(monkeypatch)


def prepared(context, monkeypatch, *, auto_enable=False, source_drift=False):
    settings, old_entry, old_candidate = fixtures.fundable_consumer(context, monkeypatch)
    assert intake.run_once(settings)["status"] == "completed"
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    monkeypatch.setattr(
        lifecycle, "observe_paper_emergency_stop", lambda *a, **k: {"active": False}
    )
    first = remote.hang_candidate(
        settings,
        candidate_id=old_candidate["candidate_id"],
        expected_source_digest=old_candidate["source_digest"],
    )
    old_definition = json.loads(Path(old_candidate["source_path"]).read_text())
    if source_drift:
        from quant_system.research import strategy_definition

        original_digest = strategy_definition._file_digest
        monkeypatch.setattr(
            strategy_definition,
            "_file_digest",
            lambda path: (
                "d" * 64
                if str(path).endswith("/research/strategy_runtime.py")
                else original_digest(path)
            ),
        )
    original = library.evaluate_definition

    def evaluate(prices, definition, start, end, *, initial_cash):
        value = original(prices, definition, start, end, initial_cash=initial_cash)
        if len(definition.factors) != len(old_definition["factors"]):
            positive = platform_result(
                equity_returns=[0.006 + (0.004 if i % 2 else -0.004) for i in range(260)],
                benchmark_returns=[0.0001] * 260,
                initial_cash=initial_cash,
            )
            value["curve"] = positive["curve"]
            value["metrics"]["sharpe"] = 3.0
        return value

    monkeypatch.setattr(library, "evaluate_definition", evaluate)
    requested = proposal(
        proposal_id="sealed-replacement",
        expression="$close/Ref($close,63)-1",
        upgrade_target={"candidate_id": old_candidate["candidate_id"]},
        increment_objective={
            "metric": "sharpe",
            "minimum_improvement": 0.01,
            "max_regressions": {},
        },
    )
    if auto_enable:
        policy_path = intake.root(settings) / "policy.json"
        policy = json.loads(policy_path.read_text())
        policy["auto_enable"] = True
        policy_path.write_text(json.dumps(policy))
    submitted = intake.submit(settings, requested)
    result = intake.run_once(settings)
    assert result["status"] == "admission_waiting", result
    new_entry = library.read_strategy(settings, result["results"][-1]["strategy_id"])
    run = Path(new_entry["admission_v2"]["path"]).parent
    args = dict(
        settings=settings,
        protocol=result["admission_protocol"],
        validation_path=run / "validation.json",
        expected_validation_sha=new_entry["validation_sha256"],
        definition_digest=new_entry["definition_digest"],
        source_sha256=new_entry["source_sha256"],
        evaluation=new_entry["evaluation"],
        book=remote.load_book(settings),
    )
    _, receipt = qualify(args)
    assert receipt["gate"]["upgrade"]["upgrade_accepted"] is True
    assert receipt["gate"]["concentration"]["applicable"] is False
    new_entry = library.refresh_admission(
        settings,
        new_entry["strategy_id"],
        new_entry["evaluation"],
        result["admission_protocol"],
        publish_entry=True,
    )
    assert new_entry["status"] == "validated", new_entry
    return settings, old_entry, old_candidate, new_entry, first["sleeve_id"], submitted


def replace(settings, entry):
    return library.replace_strategy(
        settings,
        entry["strategy_id"],
        entry["definition_digest"],
        expected_receipt={
            key: entry[key] for key in ("validation_sha256", "candidate_id", "evaluation")
        },
        expected_admission_sha=entry["admission_v2"]["sha256"],
    )


def test_actual_mathematical_replacement_keeps_capital_and_projects_old_version(
    context, monkeypatch
):
    settings, old_entry, old, new, sleeve_id, _ = prepared(context, monkeypatch)
    repo = remote.build_paper_account_repository(
        settings.data.data_dir / "api_runs", settings=settings
    )
    before = repo.load().model_dump(mode="json")
    with pytest.raises(remote.AssistantRemoteError, match="replacement_requires_lifecycle"):
        remote.hang_candidate(
            settings, candidate_id=new["candidate_id"], expected_source_digest=new["source_sha256"]
        )
    result = replace(settings, new)
    assert result["status"] == "paper_running" and result["sleeve_id"] == sleeve_id
    assert result["replacement"]["capital_delta_usd"] == 0
    assert repo.load().model_dump(mode="json") == before
    superseded = library.read_strategy(settings, old_entry["strategy_id"])
    assert superseded["status"] == "superseded" and superseded["replaced_by"] == new["candidate_id"]
    assert (
        replace(settings, new)["replacement"]["replacement_id"]
        == result["replacement"]["replacement_id"]
    )


def test_current_baseline_can_replace_an_authenticated_stale_target(context, monkeypatch):
    settings, _, old, new, sleeve_id, _ = prepared(context, monkeypatch, source_drift=True)
    repo = remote.build_paper_account_repository(
        settings.data.data_dir / "api_runs", settings=settings
    )
    account_before = repo.load().model_dump(mode="json")
    original_source = Path(old["source_path"]).read_bytes()
    result = replace(settings, new)
    assert result["status"] == "paper_running" and result["sleeve_id"] == sleeve_id
    assert result["replacement"]["capital_delta_usd"] == 0
    assert repo.load().model_dump(mode="json") == account_before
    assert Path(old["source_path"]).read_bytes() == original_source


@pytest.mark.parametrize("change", ["old_target", "old_source", "factor", "window", "weight"])
def test_current_baseline_cannot_reinterpret_authenticated_old_recipe(context, monkeypatch, change):
    settings, _, _, new, _, submitted = prepared(context, monkeypatch, source_drift=True)
    receipt = json.loads(Path(new["admission_v2"]["path"]).read_text())
    job = intake._load_job(settings, submitted["job_id"])
    binding = receipt["source_binding"]["increment_binding"]
    if change == "old_target":
        job["plans"][0]["origin"]["replacement_target"]["candidate_id"] = "wrong-old-target"
    elif change == "old_source":
        job["plans"][0]["origin"]["baseline_revalidation"]["original_source_sha256"] = "0" * 64
    else:
        baseline = job["plans"][0]
        definition = json.loads(
            (
                settings.data.data_dir
                / "strategy_library"
                / baseline["strategy_id"]
                / "definition.json"
            ).read_text()
        )
        if change == "factor":
            definition["factors"][0]["factor_id"] = "different_factor"
        elif change == "window":
            definition["history_start"] = "2016-01-01"
        else:
            definition["factors"][0]["weight"] += 1
        binding["baseline_semantics_digest"] = admission._hash(
            {
                key: value
                for key, value in definition.items()
                if key not in {"title", "content_digest", "source_fingerprints"}
            }
        )
    with pytest.raises(
        ValueError, match="replacement_baseline_(origin_mismatch|semantics_changed)"
    ):
        admission._require_replacement_baseline(job, binding, receipt["replacement"])


def test_abort_preserves_failed_version_but_old_hang_reads_active_config(context, monkeypatch):
    settings, _, old, new, sleeve_id, _ = prepared(context, monkeypatch)
    original = lifecycle._save_journal
    failed = []

    def fail_once(settings, record, phase):
        if phase == "book_bound" and not failed:
            failed.append(phase)
            raise OSError("sealed book-bound crash")
        return original(settings, record, phase)

    monkeypatch.setattr(lifecycle, "_save_journal", fail_once)
    with pytest.raises(OSError, match="sealed"):
        replace(settings, new)
    storage = PaperStrategySleeveStorage(settings.data.data_dir / "api_runs")
    pending = storage.load_sleeve(sleeve_id)
    result = lifecycle.recover_replacement(
        settings, pending.metadata[lifecycle.MARKER], action="abort"
    )
    assert result["status"] == "aborted"
    current = storage.load_sleeve(sleeve_id)
    assert current.strategy_config_version == 1
    assert storage.load_strategy_config(current.strategy_config_id).version == 2
    before = (
        remote.build_paper_account_repository(
            settings.data.data_dir / "api_runs", settings=settings
        )
        .load()
        .model_dump(mode="json")
    )
    repeated = remote.hang_candidate(
        settings, candidate_id=old["candidate_id"], expected_source_digest=old["source_digest"]
    )
    assert repeated["already_hung"] is True and repeated["sleeve_id"] == sleeve_id
    assert (
        remote.build_paper_account_repository(
            settings.data.data_dir / "api_runs", settings=settings
        )
        .load()
        .model_dump(mode="json")
        == before
    )


def test_native_intake_consumer_calls_replacement_not_new_money(context, monkeypatch):
    settings, _, old, new, sleeve_id, submitted = prepared(context, monkeypatch, auto_enable=True)
    monkeypatch.setattr(library, "enable_strategy", lambda *a, **k: pytest.fail("new-money path"))
    result = intake.run_once(settings)
    assert result["job_id"] == submitted["job_id"] and result["status"] == "completed", result
    assert result["results"][-1]["last_action"] == "replace"
    assert result["results"][-1]["sleeve_id"] == sleeve_id


def test_real_callback_resumes_verified_pending_preimage_without_new_allocation(
    context, monkeypatch
):
    settings, _, _, new, sleeve_id, _ = prepared(context, monkeypatch)
    original = lifecycle._save_journal
    failed = []

    def fail_once(settings, record, phase):
        if phase == "book_bound" and not failed:
            failed.append(phase)
            raise OSError("sealed replacement crash")
        return original(settings, record, phase)

    monkeypatch.setattr(lifecycle, "_save_journal", fail_once)
    repo = remote.build_paper_account_repository(
        settings.data.data_dir / "api_runs", settings=settings
    )
    before = repo.load().model_dump(mode="json")
    with pytest.raises(OSError, match="sealed"):
        replace(settings, new)
    storage = PaperStrategySleeveStorage(settings.data.data_dir / "api_runs")
    pending = storage.load_sleeve(sleeve_id)
    admission._WARM_QUALIFICATIONS.clear()
    recovered = lifecycle.recover_replacement(settings, pending.metadata[lifecycle.MARKER])
    assert recovered["status"] == "committed"
    assert storage.load_sleeve(sleeve_id).strategy_config_version == 2
    assert repo.load().model_dump(mode="json") == before


def test_replacement_does_not_exclude_another_concurrent_peer(context, monkeypatch):
    settings, _, old, new, _, submitted = prepared(context, monkeypatch)
    book = remote.load_book(settings)
    target = next(row for row in book["candidates"] if row["candidate_id"] == old["candidate_id"])
    # This fixture represents a distinct already-funded peer, not a book-only
    # invented ID. Use the real isolated account/sleeve writer, retaining its
    # original return evidence; the replacement must still compare this exposure.
    from quant_system.execution.paper_strategy_sleeves import (
        PaperStrategySleeveService,
        StrategySleeveMode,
    )

    storage = PaperStrategySleeveStorage(settings.data.data_dir / "api_runs")
    original_sleeve = storage.load_sleeve(target["sleeve_id"])
    config = storage.load_strategy_config(original_sleeve.strategy_config_id,
                                         version=original_sleeve.strategy_config_version)
    repo = remote.build_paper_account_repository(
        settings.data.data_dir / "api_runs", settings=settings,
    )
    account = repo.load()
    other = PaperStrategySleeveService(storage).create_sleeve(
        account, config=config, mode=StrategySleeveMode.ALLOCATED, allocated_cash=10000,
        sleeve_id="other-sleeve",
        metadata={**original_sleeve.metadata, "candidate_id": "other-peer"},
    )
    storage.save_sleeve(other)
    repo.save(account)
    assert account.sleeve_cash[other.sleeve_id] == 10000
    book["candidates"].append({**target, "candidate_id": "other-peer", "sleeve_id": "other-sleeve"})
    remote.save_book(settings, book)
    job = intake._load_job(settings, submitted["job_id"])
    refreshed = library.refresh_admission(
        settings,
        new["strategy_id"],
        new["evaluation"],
        job["admission_protocol"],
        publish_entry=True,
    )
    receipt = json.loads(Path(refreshed["admission_v2"]["path"]).read_text())
    assert receipt["gate"]["concentration"]["raw_passed"] is False
    assert [row["sleeve_id"] for row in receipt["gate"]["concentration"]["raw_by_sleeve"]] == [
        "other-sleeve"
    ]
    assert refreshed["candidate_id"] is None


@pytest.mark.parametrize("mutation", ["prices", "symbols", "benchmark", "cost", "cash"])
def test_disclosed_baseline_self_resigning_cannot_change_actual_pair(
    context, monkeypatch, mutation
):
    import pandas as pd

    from quant_system.research.validation_receipts import receipt_bindings

    settings, _, _, new, _, submitted = prepared(context, monkeypatch)
    job = intake._load_job(settings, submitted["job_id"])
    baseline = job["results"][0]
    run = (
        settings.data.data_dir
        / "strategy_library"
        / baseline["strategy_id"]
        / "validations"
        / baseline["validation"]["run_id"]
    )
    payload = json.loads((run / "platform-result.json").read_text())
    if mutation == "prices":
        prices = pd.read_parquet(run / "prices.parquet")
        prices["close"] *= 1.25
        prices.to_parquet(run / "prices.parquet", index=False)
    elif mutation == "symbols":
        payload["profile"]["symbols"] = ["UNRELATED"]
    elif mutation == "benchmark":
        payload["profile"]["benchmark_symbol"] = "QQQ"
    elif mutation == "cost":
        payload["costs"]["commission_bps"] = 0
    else:
        payload["evaluation_initial_cash"] = 100000
    (run / "platform-result.json").write_text(json.dumps(payload))
    for filename, result_key in [
        ("qlib-replay.json", "platform_result_sha256"),
        ("signal-analysis.json", "result_sha256"),
    ]:
        value = json.loads((run / filename).read_text())
        value["source"]["prices_sha256"] = admission.file_sha(run / "prices.parquet")
        value["source"][result_key] = admission.file_sha(run / "platform-result.json")
        (run / filename).write_text(json.dumps(value))
    validation = json.loads((run / "validation.json").read_text())
    validation["receipts"] = receipt_bindings(run)
    (run / "validation.json").write_text(json.dumps(validation))
    baseline["validation_sha256"] = admission.file_sha(run / "validation.json")
    intake._write(intake._job_path(settings, job["job_id"]), job)
    new_run = Path(new["admission_v2"]["path"]).parent
    record = admission.evaluate_validation(
        settings,
        protocol=job["admission_protocol"],
        validation_path=new_run / "validation.json",
        expected_validation_sha=new["validation_sha256"],
        definition_digest=new["definition_digest"],
        source_sha256=new["source_sha256"],
        evaluation=new["evaluation"],
        book=remote.load_book(settings),
    )
    assert record["gate"] is None
    assert record["reasons"][0].startswith("admission_v2_baseline_")
