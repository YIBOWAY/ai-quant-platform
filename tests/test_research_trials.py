from __future__ import annotations

import json
import logging
import math
import multiprocessing
import os
from pathlib import Path

import pytest

from quant_system.config.settings import reload_settings
from quant_system.research import trials as trials_module
from quant_system.research.trials import (
    DSR_DEFAULT_MIN,
    DSR_FAMILY_MIN_PERIODS,
    ResearchTrial,
    TrialsLedger,
    deflated_sharpe_ratio,
    evaluate_candidate_dsr,
    performance_from_daily_returns,
    universe_digest,
)


def _concurrent_trial_writer(root, run_id, returns, start, stale_reads, probe_guard, replies):
    """Force the old unlocked implementation to validate two stale reads.

    Pause at the shared validation seam only when the kernel confirms there is
    no exclusive writer lock. A correctly locked implementation must not wait
    for a second process inside its exclusive critical section.
    """
    import fcntl

    ledger = TrialsLedger(root)
    trial = ResearchTrial.record(
        kind="platform_backtest",
        subject="parallel",
        universe=["QQQ"],
        daily_returns=returns,
        source="sealed-test",
        metadata={"run_id": run_id},
    )
    original = ResearchTrial.model_dump
    first = True

    def checkpoint(self, *args, **kwargs):
        nonlocal first
        if first:
            first = False
            # A probe must not mistake the other test probe's brief lock for
            # the production writer lock that this checkpoint is inspecting.
            with probe_guard, ledger.path.open("r") as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    protected = True
                else:
                    fcntl.flock(probe, fcntl.LOCK_UN)
                    protected = False
            if not protected:
                stale_reads.wait(timeout=10)
        return original(self, *args, **kwargs)

    ResearchTrial.model_dump = checkpoint
    try:
        start.wait(timeout=10)
        ledger.append(trial)
        replies.put("ok")
    except Exception as exc:
        replies.put(f"{type(exc).__name__}:{exc}")


@pytest.mark.parametrize("mode", ["same", "conflict", "different"])
def test_ledger_cross_process_append_is_atomic_and_idempotent(tmp_path, mode):
    context = multiprocessing.get_context("spawn")
    root = tmp_path / "trials"
    root.mkdir()
    (root / "trials.jsonl").touch()
    start, stale_reads, replies = context.Barrier(3), context.Barrier(2), context.Queue()
    probe_guard = context.Lock()
    processes = [
        context.Process(
            target=_concurrent_trial_writer,
            args=(
                root,
                "second" if mode == "different" and index else "first",
                [0.2 if mode == "conflict" and index else 0.01, -0.005, 0.003],
                start,
                stale_reads,
                probe_guard,
                replies,
            ),
        )
        for index in range(2)
    ]
    try:
        for process in processes:
            process.start()
        start.wait(timeout=10)
        results = sorted(replies.get(timeout=15) for _ in processes)
        assert results == (
            ["ValueError:trial_run_id_conflict", "ok"] if mode == "conflict" else ["ok", "ok"]
        )
        assert len(TrialsLedger(root).list()) == (2 if mode == "different" else 1)
    finally:
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        replies.close()


def _partial_trial_writer(path, content, ready, release):
    import fcntl

    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        split = len(content) // 2
        stream.write(content[:split])
        stream.flush()
        ready.set()
        if not release.wait(timeout=10):
            raise TimeoutError("reader did not reach shared lock")
        stream.write(content[split:] + "\n")
        stream.flush()


def _concurrent_trial_reader(root, lock_attempt, replies):
    import fcntl

    original = fcntl.flock

    def observed_lock(stream, operation):
        if operation == fcntl.LOCK_SH:
            lock_attempt.set()
        return original(stream, operation)

    fcntl.flock = observed_lock
    try:
        replies.put([row.trial_id for row in TrialsLedger(root).list()])
    except Exception as exc:
        replies.put(type(exc).__name__)


def test_ledger_reader_waits_for_complete_record_without_creating_read_side_files(tmp_path):
    context = multiprocessing.get_context("spawn")
    missing = tmp_path / "missing"
    assert TrialsLedger(missing).list() == []
    assert not missing.exists()
    root = tmp_path / "trials"
    root.mkdir()
    trial = ResearchTrial.record(
        kind="platform_backtest",
        subject="partial-write",
        universe=["QQQ"],
        daily_returns=[0.01, -0.005, 0.002],
        source="sealed-test",
    )
    ready, release, lock_attempt, replies = (
        context.Event(),
        context.Event(),
        context.Event(),
        context.Queue(),
    )
    writer = context.Process(
        target=_partial_trial_writer,
        args=(root / "trials.jsonl", json.dumps(trial.model_dump(mode="json")), ready, release),
    )
    reader = context.Process(target=_concurrent_trial_reader, args=(root, lock_attempt, replies))
    try:
        writer.start()
        assert ready.wait(timeout=10)
        reader.start()
        assert lock_attempt.wait(timeout=5), "list read without acquiring a shared file lock"
        release.set()
        assert replies.get(timeout=10) == [trial.trial_id]
        assert [path.name for path in root.iterdir()] == ["trials.jsonl"]
    finally:
        release.set()
        for process in (writer, reader):
            if process.pid is not None:
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        replies.close()


def _strong_returns(n: int = 240, seed: int = 7) -> list[float]:
    import random

    rng = random.Random(seed)
    value = 1.0
    out = []
    for _ in range(n):
        r = rng.gauss(0.0016, 0.010)
        out.append(r)
        value *= 1 + r
    return out


def test_ledger_append_is_idempotent_and_readable(tmp_path: Path) -> None:
    ledger = TrialsLedger(tmp_path / "trials")
    trial = ResearchTrial.record(
        kind="platform_backtest",
        subject="cross_sectional_top_n",
        universe=["SPY", "QQQ"],
        window_start="2026-01-02",
        window_end="2026-06-30",
        daily_returns=_strong_returns(60),
        source="test-run-1",
    )
    ledger.append(trial)
    ledger.append(trial)

    rows = ledger.list()
    assert len(rows) == 1
    assert rows[0].trial_id == trial.trial_id
    raw = (tmp_path / "trials" / "trials.jsonl").read_text().strip().splitlines()
    assert len(raw) == 1
    assert json.loads(raw[0])["kind"] == "platform_backtest"


def test_trial_run_identity_is_idempotent_and_conflicts_on_changed_content(
    tmp_path: Path,
) -> None:
    ledger = TrialsLedger(tmp_path / "trials")

    def trial(run_id: str, returns: list[float]) -> ResearchTrial:
        return ResearchTrial.record(
            kind="platform_backtest",
            subject="same-input",
            universe=["SPY", "QQQ"],
            daily_returns=returns,
            source=run_id,
            metadata={"run_id": run_id},
        )

    first = trial("run-1", [0.01, -0.005, 0.002])
    replay = trial("run-1", [0.01, -0.005, 0.002])
    changed = trial("run-1", [0.02, -0.005, 0.002])
    second_attempt = trial("run-2", [0.01, -0.005, 0.002])

    assert first.trial_id == replay.trial_id == changed.trial_id
    assert second_attempt.trial_id != first.trial_id
    ledger.append(first)
    ledger.append(replay)
    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        ledger.append(changed)
    ledger.append(second_attempt)
    assert [row.metadata["run_id"] for row in ledger.list()] == ["run-1", "run-2"]


def test_trial_batch_conflict_does_not_partially_append(tmp_path: Path) -> None:
    ledger = TrialsLedger(tmp_path / "trials")

    def trial(run_id: str, returns: list[float]) -> ResearchTrial:
        return ResearchTrial.record(
            kind="d34_experiment",
            subject=run_id,
            universe=["SPY", "QQQ"],
            daily_returns=returns,
            source=run_id,
            metadata={"run_id": run_id},
        )

    ledger.append(trial("run-existing", [0.01, -0.005, 0.002]))

    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        ledger.append_many(
            [
                trial("run-new", [0.01, -0.005, 0.002]),
                trial("run-existing", [0.02, -0.005, 0.002]),
            ]
        )

    assert [row.metadata["run_id"] for row in ledger.list()] == ["run-existing"]


def test_universe_digest_ignores_order_and_case(tmp_path: Path) -> None:
    assert universe_digest(["SPY", "QQQ"]) == universe_digest(["qqq", "spy"])


def test_dsr_passes_for_strong_return_with_single_trial() -> None:
    perf = performance_from_daily_returns(_strong_returns())
    result = deflated_sharpe_ratio(
        sharpe=perf["sharpe_period"],
        n_periods=perf["n_periods"],
        skewness=perf["skewness"],
        kurtosis=perf["kurtosis"],
        trial_sharpes=[perf["sharpe_period"]],
    )
    assert result["n_trials"] == 1
    assert result["threshold_sr"] == 0.0
    assert result["value"] > DSR_DEFAULT_MIN
    assert result["passed"] is True


def test_performance_reports_adjusted_plain_kurtosis() -> None:
    performance = performance_from_daily_returns([0.01, 0.02, 0.03, 0.04, 0.05])

    assert performance["kurtosis"] == pytest.approx(1.8)


def test_dsr_penalizes_many_trials_with_high_variance() -> None:
    perf = performance_from_daily_returns(_strong_returns())
    single = deflated_sharpe_ratio(
        sharpe=perf["sharpe_period"],
        n_periods=perf["n_periods"],
        skewness=perf["skewness"],
        kurtosis=perf["kurtosis"],
        trial_sharpes=[perf["sharpe_period"]],
    )
    noisy_family = [perf["sharpe_period"], *[0.22, -0.05, 0.18, 0.3, -0.12] * 10]
    many = deflated_sharpe_ratio(
        sharpe=perf["sharpe_period"],
        n_periods=perf["n_periods"],
        skewness=perf["skewness"],
        kurtosis=perf["kurtosis"],
        trial_sharpes=noisy_family,
    )
    assert many["n_trials"] == len(noisy_family)
    assert many["threshold_sr"] > 0.0
    assert many["value"] < single["value"]


def test_dsr_matches_probabilistic_sharpe_ratio_math() -> None:
    # PSR vs SR*=0 with known moments: z = SR*sqrt(n-1)/sqrt(1 - skew*SR + (kurt-1)/4*SR^2)
    from statistics import NormalDist

    sharpe, n, skew, kurt = 0.10, 200, 0.0, 3.0
    result = deflated_sharpe_ratio(
        sharpe=sharpe, n_periods=n, skewness=skew, kurtosis=kurt, trial_sharpes=[sharpe]
    )
    z = sharpe * math.sqrt(n - 1) / math.sqrt(1 - skew * sharpe + (kurt - 1) / 4 * sharpe**2)
    assert abs(result["value"] - NormalDist().cdf(z)) < 1e-12


def test_dsr_family_excludes_short_windows(tmp_path: Path) -> None:
    assert DSR_FAMILY_MIN_PERIODS == 20
    ledger = TrialsLedger(tmp_path / "trials")
    universe = ["DIA", "IWM", "QQQ", "SPY"]
    short = ResearchTrial.record(
        kind="d34_experiment",
        subject="momentum:short",
        universe=universe,
        daily_returns=[0.01, -0.01, 0.02],
        source="fixture-short-window",
    )
    long = ResearchTrial.record(
        kind="d34_experiment",
        subject="momentum:long",
        universe=universe,
        daily_returns=_strong_returns(60),
        source="fixture-long-window",
    )
    edge19 = ResearchTrial.record(
        kind="d34_experiment",
        subject="momentum:19",
        universe=universe,
        daily_returns=_strong_returns(19),
        source="fixture-19",
    )
    edge20 = ResearchTrial.record(
        kind="d34_experiment",
        subject="momentum:20",
        universe=universe,
        daily_returns=_strong_returns(20),
        source="fixture-20",
    )
    magic_long = ResearchTrial.record(
        kind="d34_experiment",
        subject="momentum:magic",
        universe=universe,
        daily_returns=_strong_returns(40),
        source="job-12345678:iteration-01-experiment-01",
    )
    ledger.append(short)
    ledger.append(long)
    ledger.append(edge19)
    ledger.append(edge20)
    ledger.append(magic_long)
    assert short.n_periods < 20
    assert edge19.n_periods == 19
    assert edge20.n_periods == 20
    assert long.n_periods >= 20
    family = ledger.trial_sharpes(universe=universe_digest(universe))
    assert family == [long.sharpe, edge20.sharpe, magic_long.sharpe]
    result = evaluate_candidate_dsr(
        ledger,
        universe=universe,
        daily_returns=_strong_returns(80),
    )
    assert result["n_trials"] == 3
    assert "job-12345678" not in Path(
        __import__("quant_system.research.trials", fromlist=["trials"]).__file__
    ).read_text(encoding="utf-8")


def test_dsr_fails_for_negative_sharpe(tmp_path: Path) -> None:
    result = deflated_sharpe_ratio(
        sharpe=-0.05, n_periods=200, skewness=0.0, kurtosis=3.0, trial_sharpes=[-0.05]
    )
    assert result["value"] < 0.5
    assert result["passed"] is False


def test_pipeline_backtest_appends_a_trial(tmp_path, monkeypatch) -> None:
    from quant_system.backtest.pipeline import run_backtest
    from quant_system.config.settings import DataSettings, Settings

    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "data"))
    from quant_system.config.settings import PaperAccountSettings

    settings = reload_settings()
    settings = settings.model_copy(
        update={"paper_account": PaperAccountSettings(commission_bps=2.0, slippage_bps=7.0)}
    )

    result = run_backtest(
        symbols=["SPY", "QQQ"],
        start="2024-01-02",
        end="2024-02-02",
        provider="sample",
        lookback=3,
        top_n=1,
        output_dir=tmp_path / "runs",
        settings=settings,
    )
    report = Path(result.report_path).read_text(encoding="utf-8")
    assert "2.0000 bps" in report

    ledger = TrialsLedger(Path(settings.data.data_dir) / "trials")
    rows = ledger.list()
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == "platform_backtest"
    assert row.subject == "cross_sectional_top_n"
    assert row.universe == ["QQQ", "SPY"]
    assert row.window_start == "2024-01-02"
    assert row.window_end == "2024-02-02"
    assert row.sharpe is not None and row.n_periods > 0
    assert row.source == result.source or row.source
    # R6: the trial cites the same as-of universe snapshot as the run result.
    assert row.metadata["universe_snapshot_digest"] == result.universe_snapshot_digest
    assert len(row.metadata["universe_snapshot_digest"]) == 64
    from quant_system.config.settings import PaperAccountSettings

    paper = PaperAccountSettings()
    assert paper.commission_bps == 1.0
    assert paper.slippage_bps == 5.0


def test_cost_sensitivity_fails_when_double_costs_eat_the_edge() -> None:
    from quant_system.research.trials import cost_sensitivity_verdict

    # 8%/yr edge, 12x annual turnover, 6bp roundtrip -> 1x drag 0.72%, 2x 1.44% -> passes
    strong = cost_sensitivity_verdict(annual_return=0.08, annual_turnover=12.0, cost_bps=6.0)
    assert strong["passed"] is True
    # 1%/yr edge, 50x turnover, 6bp -> 1x drag 0.3%, 2x 0.6% -> passes; 3%? make it fail:
    weak = cost_sensitivity_verdict(annual_return=0.01, annual_turnover=150.0, cost_bps=6.0)
    assert weak["passed"] is False
    assert weak["net_return_at_2x"] < 0


def test_date_aligned_correlation_pairs_days_not_positions() -> None:
    import datetime as dt
    import random

    import pytest

    from quant_system.research.trials import date_aligned_correlation

    rng = random.Random(3)
    values = [rng.gauss(0.001, 0.01) for _ in range(60)]
    dates = [(dt.date(2026, 1, 1) + dt.timedelta(days=index)).isoformat() for index in range(60)]

    # Same days, same values: a measured twin.
    assert date_aligned_correlation(values, dates, values, dates) == pytest.approx(1.0)

    # Identical sequence over a later window: position i pairs with position i
    # (fake twin ~1.0), but only 30 days are shared and on each shared day the
    # two series hold unrelated draws.
    shifted = [(dt.date(2026, 1, 31) + dt.timedelta(days=index)).isoformat() for index in range(60)]
    corr = date_aligned_correlation(values, dates, values, shifted)
    assert corr is not None and abs(corr) < 0.7

    # Barely overlapping windows are honestly unmeasurable.
    tiny_overlap = [
        (dt.date(2026, 2, 20) + dt.timedelta(days=index)).isoformat() for index in range(60)
    ]
    assert date_aligned_correlation(values, dates, values, tiny_overlap) is None


def _write_ledger_rows(root, trials):
    """Write valid ledger rows directly so a test can then damage one."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "trials.jsonl"
    path.write_text(
        "".join(json.dumps(t.model_dump(mode="json")) + "\n" for t in trials),
        encoding="utf-8",
    )
    return path


def _ledger_trials(run_ids, returns=None):
    return [
        ResearchTrial.record(
            kind="platform_backtest",
            subject="corruption-tolerance",
            universe=["SPY", "QQQ"],
            daily_returns=returns or [0.01, -0.005, 0.002],
            source=run_id,
            metadata={"run_id": run_id},
        )
        for run_id in run_ids
    ]


def test_ledger_skips_middle_corrupt_row_and_counts(tmp_path, caplog) -> None:
    trials = _ledger_trials(["row-1", "row-2", "row-3"])
    path = _write_ledger_rows(tmp_path / "trials", trials)

    lines = path.read_text(encoding="utf-8").splitlines()
    lines.insert(1, "{ this is not json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="quant_system.research.trials"):
        rows = TrialsLedger(tmp_path / "trials").list()

    assert [row.trial_id for row in rows] == [trial.trial_id for trial in trials]
    messages = [record.getMessage() for record in caplog.records]
    assert any("line 2" in message for message in messages)
    assert any("skipped 1 malformed" in message for message in messages)


def test_ledger_skips_middle_corrupt_row_for_sharpe_family(tmp_path, caplog) -> None:
    trials = _ledger_trials(["family-1", "family-2", "family-3"], returns=_strong_returns(30))
    path = _write_ledger_rows(tmp_path / "trials", trials)

    lines = path.read_text(encoding="utf-8").splitlines()
    lines.insert(1, "{ this is not json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="quant_system.research.trials"):
        sharpes = TrialsLedger(tmp_path / "trials").trial_sharpes(
            universe=universe_digest(["SPY", "QQQ"])
        )

    assert len(sharpes) == 3


def test_ledger_skips_truncated_last_row(tmp_path, caplog) -> None:
    trials = _ledger_trials(["tail-1", "tail-2", "tail-3"])
    path = _write_ledger_rows(tmp_path / "trials", trials)

    text = path.read_text(encoding="utf-8")
    path.write_text(text[: len(text) - 6], encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="quant_system.research.trials"):
        rows = TrialsLedger(tmp_path / "trials").list()

    assert [row.trial_id for row in rows] == [trial.trial_id for trial in trials[:2]]
    messages = [record.getMessage() for record in caplog.records]
    assert any("line 3" in message for message in messages)
    assert any("skipped 1 malformed" in message for message in messages)


def test_ledger_append_after_truncated_tail_keeps_new_row(tmp_path) -> None:
    trials = _ledger_trials(["keep-1", "keep-2", "keep-3"])
    path = _write_ledger_rows(tmp_path / "trials", trials)

    text = path.read_text(encoding="utf-8")
    path.write_text(text[: len(text) - 6], encoding="utf-8")

    ledger = TrialsLedger(tmp_path / "trials")
    fresh = _ledger_trials(["keep-4"])[0]
    ledger.append(fresh)

    # The new receipt must land on its own physical line, not fused to the
    # truncated bytes already at EOF.
    assert [row.trial_id for row in ledger.list()] == [
        trial.trial_id for trial in trials[:2]
    ] + [fresh.trial_id]


def test_ledger_rejects_unserializable_payload_before_any_write(tmp_path) -> None:
    ledger = TrialsLedger(tmp_path / "trials")
    ledger.append(_ledger_trials(["good-1"])[0])

    good = _ledger_trials(["good-2"])[0]
    bad = ResearchTrial.record(
        kind="platform_backtest",
        subject="corruption-tolerance",
        universe=["SPY", "QQQ"],
        daily_returns=[0.01, -0.005, 0.002],
        source="bad-blob",
        metadata={"blob": object()},
    )

    with pytest.raises(ValueError):
        ledger.append_many([good, bad])

    # The whole batch is rejected before the first byte: no half-written row.
    assert len((tmp_path / "trials" / "trials.jsonl").read_text().strip().splitlines()) == 1


def test_ledger_append_fsyncs_inside_the_exclusive_lock(tmp_path, monkeypatch) -> None:
    import fcntl

    ledger = TrialsLedger(tmp_path / "trials")
    observed: dict[str, object] = {}
    real_fsync = os.fsync

    def spy(fd):
        observed["fd"] = fd
        with ledger.path.open("r") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                observed["locked"] = True
            else:
                fcntl.flock(probe, fcntl.LOCK_UN)
                observed["locked"] = False
        return real_fsync(fd)

    monkeypatch.setattr(trials_module.os, "fsync", spy)
    ledger.append(_ledger_trials(["fsync-1"])[0])

    assert observed["locked"] is True
    assert isinstance(observed["fd"], int)
