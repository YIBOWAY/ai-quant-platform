"""Artificial producer boundaries and actual statistics, identity and consumers.

No market/provider evidence is claimed. Quality/DSR/cost and funding are real;
the external engines and qualification issuer are explicit isolated specimens.
"""

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from quant_system.research import admission_v2 as admission
from quant_system.research import external_intake as intake
from tests import test_admission_v2 as core_fixtures
from tests import test_external_intake as intake_fixtures
from tests.gate_v2_fixtures import DEFAULT_UNIVERSE, platform_result
from tests.test_admission_v2 import qualify
from tests.test_external_intake import policy, proposal


@pytest.fixture
def context(tmp_path):
    return core_fixtures.context.__wrapped__(tmp_path)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    return intake_fixtures.settings.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def sealed_producer(monkeypatch):
    yield from core_fixtures.sealed_producer.__wrapped__(monkeypatch)


def consumer(context, monkeypatch, mode, *, negative=False, keep_context_job=False):
    import pandas as pd

    from quant_system.research import strategy_library as library
    from tests.test_assistant_remote import _settings

    root = context["settings"].data.data_dir
    if not keep_context_job:
        (root / "research_intake/jobs" / (context["protocol"]["job_id"] + ".json")).unlink()
    settings = _settings(root, monkeypatch)
    policy(settings, admission_mode=mode)
    prices = pd.DataFrame(
        {
            "timestamp": pd.bdate_range("2024-01-02", periods=260, tz="UTC"),
            "symbol": ["SPY"] * 260,
            "close": [100.0] * 260,
        }
    )
    calls = []
    monkeypatch.setattr(library, "_collect_prices", lambda *_: (prices, {}))
    monkeypatch.setattr(
        "quant_system.research.definition_paper.definition_schedule_available", lambda: True
    )

    def evaluate(prices, definition, start, end, *, initial_cash):
        calls.append("engine")
        # For the measured T0 case, ordinary active mean is negative versus
        # the declared benchmark while total net return survives the real cost
        # check. The old negative-total fixture hid that distinction by mocking
        # the cost/DSR core. No quality/statistic is replaced here.
        value = platform_result(
            equity_returns=[
                (0.00005 if negative else 0.003) + (0.004 if i % 2 else -0.004)
                for i in range(260)
            ],
            benchmark_returns=[0.0001] * 260,
            initial_cash=initial_cash,
        )
        value.update(
            source="futu",
            price_adjustment="qfq",
            frequency="daily",
            definition=definition.model_dump(mode="json"),
            definition_digest=definition.content_digest,
            status="available",
            start=start,
            end=end,
            profile={
                "id": "sealed",
                "symbols": list(definition.symbols),
                "benchmark_symbol": "SPY",
            },
            costs={"commission_bps": 1, "slippage_bps": 5},
            metrics={"turnover": 1.0, "total_return": 1.0, "sharpe": 2.0, "max_drawdown": 0.1},
        )
        return value

    def docker(run, module, args):
        value = json.loads((run / "platform-result.json").read_text())
        sources = {
            name: admission.file_sha(Path(library.__file__).with_name(name))
            for name in (
                "definition_qlib_replay.py",
                "strategy_signal_validation.py",
                "qlib_evaluation.py",
            )
        }
        source = {"prices_sha256": admission.file_sha(run / "prices.parquet")}
        if module.endswith("definition_qlib_replay"):
            source.update(
                platform_result_sha256=admission.file_sha(run / "platform-result.json"),
                replay_source_sha256=sources["definition_qlib_replay.py"],
            )
            library._write(
                run / "qlib-replay.json",
                {
                    "status": "available",
                    "definition_digest": value["definition_digest"],
                    "initial_cash": 10000,
                    "terminal_nav_unit": "USD",
                    "source": source,
                },
            )
        else:
            source.update(
                result_sha256=admission.file_sha(run / "platform-result.json"),
                validation_source_sha256=sources["strategy_signal_validation.py"],
                fit_metrics_source_sha256=sources["qlib_evaluation.py"],
            )
            library._write(
                run / "signal-analysis.json",
                {
                    "status": "available",
                    "definition_digest": value["definition_digest"],
                    "source": source,
                },
            )

    monkeypatch.setattr(library, "evaluate_definition", evaluate)
    monkeypatch.setattr(library, "_docker", docker)
    monkeypatch.setattr(
        library, "_comparison", lambda *_: {"accepted": True, "comparison_digest": "c" * 64}
    )
    job = intake.submit(
        settings, proposal(strategy_spec={"symbols": list(DEFAULT_UNIVERSE), "top_n": 2})
    )
    result = intake.run_once(settings)
    assert result.get("error") is None, result
    entry = library.read_strategy(settings, result["results"][0]["strategy_id"])
    assert "admission_v2" in entry, entry
    return settings, job, result, entry, calls


def test_actual_validate_reads_parallel_sidecar_without_changing_legacy_outcome(
    context, monkeypatch
):
    from quant_system.execution import assistant_remote as remote
    from quant_system.research import strategy_library as library

    settings, job, result, entry, calls = consumer(context, monkeypatch, "parallel")
    assert result["status"] == "completed" and entry["status"] == "validated"
    assert entry["admission_v2"]["status"] == "not_evaluated"
    assert entry["candidate_id"].startswith("strategy-v2-")
    candidate = remote.load_book(settings)["candidates"][0]
    assert admission.candidate_receipt(settings, candidate)["mode"] == "parallel"
    raw = Path(entry["admission_v2"]["path"]).parent / "validation.json"
    assert json.loads(raw.read_text())["status"] == "passed"
    assert (
        library.find_evaluation(settings, entry["strategy_id"], entry["evaluation"])["admission_v2"]
        == entry["admission_v2"]
    )
    assert calls == ["engine"]
    assert not (settings.data.data_dir / "api_runs").exists()


def test_native_identical_computation_reuses_frozen_source_despite_new_proposal_title(
    context, monkeypatch
):
    from quant_system.research import strategy_library as library

    settings, _, _, first, calls = consumer(context, monkeypatch, "parallel")
    source = settings.data.data_dir / "strategy_library" / first["strategy_id"] / "definition.json"
    original = source.read_bytes()
    new = proposal(strategy_spec={"symbols": list(DEFAULT_UNIVERSE), "top_n": 2})
    new["proposal_id"] += "-new-display-title"
    submitted = intake.submit(settings, new)
    job = intake.run_once(settings)
    assert job["job_id"] == submitted["job_id"]
    result = job["results"][0]
    assert result["definition_digest"] == first["definition_digest"]
    assert source.read_bytes() == original
    record = json.loads(Path(result["admission_v2"]["path"]).read_text())
    assert record["gate"] is not None, record["reasons"]
    assert calls == ["engine", "engine"]
    assert (
        library.read_strategy(settings, first["strategy_id"])["definition"]["title"]
        == json.loads(original)["title"]
    )


def test_unknown_authoritative_tier_has_zero_candidate_account_writes_and_refresh_no_replay(
    context, monkeypatch
):
    from quant_system.execution import assistant_remote as remote

    settings, job, result, entry, calls = consumer(context, monkeypatch, "authoritative")
    assert result["status"] == "admission_waiting"
    assert entry["candidate_id"] is None
    assert remote.load_book(settings)["candidates"] == []
    before = (settings.data.data_dir / "trials/trials.jsonl").read_bytes()
    old_ref = entry["admission_v2"]
    again = intake.run_once(settings)
    assert again["status"] == "admission_waiting"
    assert again["results"][0]["admission_v2"] == old_ref
    assert calls == ["engine"]
    assert (settings.data.data_dir / "trials/trials.jsonl").read_bytes() == before
    assert not (settings.data.data_dir / "assistant_remote/book.json").exists()
    assert not (settings.data.data_dir / "api_runs").exists()


def fundable_consumer(context, monkeypatch):
    from quant_system.execution import assistant_remote as remote
    from quant_system.research import strategy_library as library

    settings, job, result, entry, calls = consumer(context, monkeypatch, "authoritative")
    path = Path(entry["admission_v2"]["path"]).parent / "validation.json"
    args = dict(
        settings=settings,
        protocol=result["admission_protocol"],
        validation_path=path,
        expected_validation_sha=entry["validation_sha256"],
        definition_digest=entry["definition_digest"],
        source_sha256=entry["source_sha256"],
        evaluation=entry["evaluation"],
        book=remote.load_book(settings),
    )
    qualify(args)
    refreshed = library.refresh_admission(
        settings,
        entry["strategy_id"],
        entry["evaluation"],
        result["admission_protocol"],
        publish_entry=True,
    )
    assert refreshed["status"] == "validated", refreshed
    return settings, refreshed, remote.load_book(settings)["candidates"][0]


@pytest.mark.parametrize("tier, expected_status", [("T0", "recorded"), ("T1", "shadow")])
def test_known_unfunded_tiers_never_create_allocated_zero_cash_sleeves(
    context,
    monkeypatch,
    tier,
    expected_status,
):
    from quant_system.execution import assistant_remote as remote
    from quant_system.research import strategy_library as library

    if tier == "T1":
        ledger = context["settings"].data.data_dir / "trials/trials.jsonl"
        ledger.write_text("\n".join(ledger.read_text().splitlines()[:3]) + "\n")
    settings, _, result, entry, _ = consumer(
        context,
        monkeypatch,
        "authoritative",
        negative=tier == "T0",
    )
    path = Path(entry["admission_v2"]["path"]).parent / "validation.json"
    args = dict(
        settings=settings,
        protocol=result["admission_protocol"],
        validation_path=path,
        expected_validation_sha=entry["validation_sha256"],
        definition_digest=entry["definition_digest"],
        source_sha256=entry["source_sha256"],
        evaluation=entry["evaluation"],
        book=remote.load_book(settings),
    )
    qualify(args, expected_tier=tier)
    refreshed = library.refresh_admission(
        settings,
        entry["strategy_id"],
        entry["evaluation"],
        result["admission_protocol"],
        publish_entry=True,
    )
    assert refreshed["admission_v2"]["status"] == expected_status
    assert refreshed["admission_v2"]["validated_tier"] == tier
    assert refreshed["candidate_id"] is None
    completed = intake.run_once(settings)
    assert completed["status"] == "completed"
    assert completed["outcome"] == ("unfunded_record" if tier == "T0" else "shadow_evidence")
    assert not (settings.data.data_dir / "assistant_remote/book.json").exists()
    assert not (settings.data.data_dir / "api_runs").exists()


def test_actual_capital_consumer_disabled_and_removed_receipt_fail_before_account(
    context, monkeypatch
):
    from quant_system.execution import assistant_remote as remote

    settings, entry, candidate = fundable_consumer(context, monkeypatch)
    monkeypatch.setattr(
        remote, "build_paper_account_repository", lambda *a, **k: pytest.fail("account reached")
    )
    kwargs = dict(
        candidate_id=candidate["candidate_id"], expected_source_digest=candidate["source_digest"]
    )
    before = (settings.data.data_dir / "assistant_remote/book.json").read_bytes()
    with pytest.raises(remote.AssistantRemoteError, match="authority_disabled"):
        remote.hang_candidate(settings, **kwargs)
    assert (settings.data.data_dir / "assistant_remote/book.json").read_bytes() == before
    book = remote.load_book(settings)
    book["candidates"][0].pop("admission_v2")
    remote.save_book(settings, book)
    with pytest.raises(remote.AssistantRemoteError, match="original_protocol_required"):
        remote.hang_candidate(settings, **kwargs)


@pytest.mark.parametrize("strip_base_marker", [False, True])
def test_legacy_named_alias_cannot_strip_the_original_job_protocol(
    context,
    monkeypatch,
    strip_base_marker,
):
    from quant_system.execution import assistant_remote as remote

    settings, entry, candidate = fundable_consumer(context, monkeypatch)
    book = remote.load_book(settings)
    book["candidates"][0].pop("admission_v2")
    book["candidates"][0]["candidate_id"] = "legacy-looking-alias"
    if strip_base_marker:
        base_path = Path(entry["admission_v2"]["path"]).parent / "validation.json"
        base = json.loads(base_path.read_text())
        base.pop("admission_protocol_digest")
        base_path.write_text(json.dumps(base))
        candidate["verification_receipt_digest"] = admission.file_sha(base_path)
        book["candidates"][0]["verification_receipt_digest"] = candidate[
            "verification_receipt_digest"
        ]
    remote.save_book(settings, book)
    monkeypatch.setattr(
        remote,
        "build_paper_account_repository",
        lambda *a, **k: pytest.fail("account reached"),
    )
    with pytest.raises(remote.AssistantRemoteError, match="original_protocol_required"):
        remote.hang_candidate(
            settings,
            candidate_id="legacy-looking-alias",
            expected_source_digest=candidate["source_digest"],
        )
    with pytest.raises(remote.AssistantRemoteError, match="original_protocol_required"):
        remote.record_verified_candidate(
            settings,
            candidate_id="new-alias",
            source="strategy_definition",
            objective="sealed",
            source_path=candidate["source_path"],
            source_digest=candidate["source_digest"],
            factor_id=candidate["factor_id"],
            universe=candidate["universe"],
            comparison_digest=candidate["comparison_digest"],
            verification_receipt_digest=candidate["verification_receipt_digest"],
            daily_returns=candidate["performance"]["daily_returns"],
            return_dates=candidate["performance"]["return_dates"],
        )


def test_authoritative_real_transaction_allocates_10000_once_and_recovery_ignores_new_gate(
    context, monkeypatch
):
    from quant_system.execution import assistant_remote as remote
    from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage

    settings, entry, candidate = fundable_consumer(context, monkeypatch)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    kwargs = dict(
        candidate_id=candidate["candidate_id"], expected_source_digest=candidate["source_digest"]
    )
    result = remote.hang_candidate(settings, **kwargs)
    assert result["status"] == "hung"
    repo = remote.build_paper_account_repository(
        settings.data.data_dir / "api_runs", settings=settings
    )
    account = repo.load()
    assert account.sleeve_cash[result["sleeve_id"]] == 10000
    assert len([r for r in account.ledger if r.kind == "sleeve_cash_allocated"]) == 1
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", False)
    with (settings.data.data_dir / "trials/trials.jsonl").open("a") as handle:
        handle.write("\n")
    assert remote.hang_candidate(settings, **kwargs)["already_hung"] is True
    assert len(PaperStrategySleeveStorage(settings.data.data_dir / "api_runs").list_sleeves()) == 1
    assert len([r for r in repo.load().ledger if r.kind == "sleeve_cash_allocated"]) == 1


def test_disclosed_external_copy_still_requires_original_protocol(context, monkeypatch):
    import shutil

    from quant_system.execution import assistant_remote as remote

    settings, entry, candidate = fundable_consumer(context, monkeypatch)
    original = Path(candidate["source_path"]).parent
    copied = settings.data.data_dir.parent / (settings.data.data_dir.name + "-external-copy")
    shutil.copytree(original, copied)
    book = remote.load_book(settings)
    book["candidates"][0].pop("admission_v2")
    book["candidates"][0].update(
        candidate_id="external-legacy-alias", source_path=str(copied / "definition.json")
    )
    remote.save_book(settings, book)
    monkeypatch.setattr(
        remote, "build_paper_account_repository", lambda *a, **k: pytest.fail("account reached")
    )
    with pytest.raises(remote.AssistantRemoteError, match="original_protocol_required"):
        remote.hang_candidate(
            settings,
            candidate_id="external-legacy-alias",
            expected_source_digest=candidate["source_digest"],
        )


def test_peer_family_cas_inside_existing_locks_has_zero_allocation(context, monkeypatch):
    from quant_system.execution import assistant_remote as remote
    from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage

    settings, entry, candidate = fundable_consumer(context, monkeypatch)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    original = remote._book_mutation_lock

    @contextmanager
    def race(current, **kwargs):
        with original(current, **kwargs):
            with (settings.data.data_dir / "trials/trials.jsonl").open("a") as handle:
                handle.write("\n")
            yield

    monkeypatch.setattr(remote, "_book_mutation_lock", race)
    before = (settings.data.data_dir / "assistant_remote/book.json").read_bytes()
    with pytest.raises(remote.AssistantRemoteError, match="family_changed"):
        remote.hang_candidate(
            settings,
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
        )
    assert (
        remote.build_paper_account_repository(
            settings.data.data_dir / "api_runs", settings=settings
        ).load()
        is None
    )
    assert PaperStrategySleeveStorage(settings.data.data_dir / "api_runs").list_sleeves() == []
    assert (settings.data.data_dir / "assistant_remote/book.json").read_bytes() == before


@pytest.mark.parametrize("physical_peer", [False, True])
def test_new_hung_peer_between_preflight_and_lock_is_not_ignored(
    context, monkeypatch, physical_peer,
):
    from quant_system.execution import assistant_remote as remote
    from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
    from quant_system.execution.paper_strategy_sleeves import (
        PaperStrategySleeveService,
        StrategyConfig,
        StrategySleeveMode,
    )
    from quant_system.research.definition_paper import definition_config_fields
    from quant_system.research.strategy_definition import StrategyDefinition

    settings, entry, candidate = fundable_consumer(context, monkeypatch)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    original = remote._book_mutation_lock
    concurrent_account = None

    @contextmanager
    def race(current, **kwargs):
        nonlocal concurrent_account
        with original(current, **kwargs):
            book = remote.load_book(settings)
            if physical_peer:
                repo = remote.build_paper_account_repository(
                    settings.data.data_dir / "api_runs", settings=settings,
                )
                account = repo.load_or_open(initial_cash=1_000_000)
                storage = PaperStrategySleeveStorage(settings.data.data_dir / "api_runs")
                definition = StrategyDefinition.model_validate(
                    json.loads(Path(candidate["source_path"]).read_text())
                )
                config = StrategyConfig.create(name="Artificial concurrent peer",
                                                **definition_config_fields(definition))
                sleeve = PaperStrategySleeveService(storage).create_sleeve(
                    account, config=config, mode=StrategySleeveMode.ALLOCATED,
                    allocated_cash=10_000, sleeve_id="sleeve-concurrent",
                    metadata={"candidate_id": "concurrent-peer",
                              "source_digest": candidate["source_digest"],
                              "mandate_id": "remote-hang"},
                )
                storage.save_strategy_config(config)
                storage.save_sleeve(sleeve)
                repo.save(account)
                concurrent_account = account.model_dump(mode="json")
            book["candidates"].append(
                {
                    **candidate,
                    "candidate_id": "concurrent-peer",
                    "status": "hung",
                    "sleeve_id": "sleeve-concurrent",
                }
            )
            remote.save_book(settings, book)
            yield

    monkeypatch.setattr(remote, "_book_mutation_lock", race)
    reason = "peers_changed" if physical_peer else "peer_sleeve_unavailable"
    with pytest.raises(remote.AssistantRemoteError, match=reason):
        remote.hang_candidate(
            settings,
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
        )
    account = remote.build_paper_account_repository(
        settings.data.data_dir / "api_runs", settings=settings,
    ).load()
    if physical_peer:
        assert account.model_dump(mode="json") == concurrent_account
        assert account.sleeve_cash["sleeve-concurrent"] == 10_000
        assert len([row for row in account.ledger if row.kind == "sleeve_cash_allocated"]) == 1
    else:
        assert account is None
    assert remote.load_book(settings)["candidates"][0]["status"] == "verified"


def test_v2_cannot_allocate_beyond_existing_available_cash(context, monkeypatch):
    from quant_system.execution import assistant_remote as remote
    from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage

    settings, entry, candidate = fundable_consumer(context, monkeypatch)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    repo = remote.build_paper_account_repository(
        settings.data.data_dir / "api_runs", settings=settings
    )
    account = repo.load_or_open(initial_cash=9999.0)
    before = account.model_dump(mode="json")
    with pytest.raises(remote.AssistantRemoteError, match="hang_insufficient_funds"):
        remote.hang_candidate(
            settings,
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
        )
    assert repo.load().model_dump(mode="json") == before
    assert PaperStrategySleeveStorage(settings.data.data_dir / "api_runs").list_sleeves() == []


def test_v2_book_write_failure_recovers_one_existing_allocation_without_requalification(
    context, monkeypatch
):
    from quant_system.execution import assistant_remote as remote
    from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage

    settings, entry, candidate = fundable_consumer(context, monkeypatch)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    original = remote.save_book
    calls = []

    def fail_once(settings, book):
        calls.append("save")
        if len(calls) == 1:
            raise OSError("sealed book failure")
        return original(settings, book)

    monkeypatch.setattr(remote, "save_book", fail_once)
    kwargs = dict(
        candidate_id=candidate["candidate_id"], expected_source_digest=candidate["source_digest"]
    )
    with pytest.raises(remote.AssistantRemoteError, match="hang_book_persist_failed"):
        remote.hang_candidate(settings, **kwargs)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", False)
    with (settings.data.data_dir / "trials/trials.jsonl").open("a") as handle:
        handle.write("\n")
    result = remote.hang_candidate(settings, **kwargs)
    assert result["status"] == "hung"
    sleeves = PaperStrategySleeveStorage(settings.data.data_dir / "api_runs").list_sleeves()
    assert len(sleeves) == 1 and sleeves[0].initial_allocated_cash == 10000
    repo = remote.build_paper_account_repository(
        settings.data.data_dir / "api_runs", settings=settings
    )
    assert len([r for r in repo.load().ledger if r.kind == "sleeve_cash_allocated"]) == 1


def test_new_intake_freezes_protocol_and_legacy_job_is_not_upgraded(settings):
    policy(settings)
    result = intake.submit(settings, proposal())
    job = intake._load_job(settings, result["job_id"])
    protocol = job["admission_protocol"]
    admission.verify_protocol(protocol, job_id=job["job_id"], proposal_digest=job["payload_sha256"])
    assert protocol["mode"] == "parallel"
    assert result["admission_protocol"]["protocol_digest"] == protocol["protocol_digest"]
    # Model a genuinely old job: it predates both protocol and plan marker.
    job.pop("admission_protocol")
    for plan in job["plans"]:
        plan["origin"].pop("admission_protocol_digest")
    job["plans_sha256"] = intake._sha(job["plans"])
    intake._write(intake._job_path(settings, job["job_id"]), job)
    before = intake._job_path(settings, job["job_id"]).read_bytes()
    assert "admission_protocol" not in intake.submit(settings, proposal())
    assert intake._job_path(settings, job["job_id"]).read_bytes() == before


def test_protocol_removal_cannot_silently_downgrade_new_job(settings):
    policy(settings)
    result = intake.submit(settings, proposal())
    path = intake._job_path(settings, result["job_id"])
    job = json.loads(path.read_text())
    job.pop("admission_protocol")
    intake._write(path, job)
    with pytest.raises(ValueError, match="admission_v2_protocol_required"):
        intake._load_job(settings, result["job_id"])
