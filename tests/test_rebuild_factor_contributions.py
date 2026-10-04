"""Synthetic stock panels test bindings, exclusions and archived-statistic matching."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant_system.factors.evaluation import build_price_frame, prepare_evaluation_frames
from quant_system.factors.scorecard import _daily_ic_block
from quant_system.research import factor_contributions as subject


@pytest.fixture
def panel_fixture():
    days = pd.bdate_range("2024-01-02", periods=12, tz="UTC")
    rows, signals, identities = [], [], []
    for k, symbol in enumerate(["A", "B", "C", "D"]):
        for n, day in enumerate(days):
            if symbol == "A" and n == 3:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": day,
                    "open": 100 + 5 * k + n * (k + 1) + 0.3 * n * n,
                }
            )
            if n < 6 or n == 11:
                signals.append(
                    {
                        "symbol": symbol,
                        "signal_ts": day,
                        "factor_id": "artificial",
                        "value": k + 0.1 * n,
                    }
                )
                identities.append(
                    {"symbol": symbol, "signal_ts": day, "entity_id": "entity-" + symbol}
                )
    prices, values, membership = map(pd.DataFrame, [rows, signals, identities])
    prepared = prepare_evaluation_frames(values, prices, horizons=(1,))[1]
    frame = build_price_frame(prices)
    daily, _ = _daily_ic_block(
        prepared, factor_id="artificial", horizon=1, price_basis="open_to_open"
    )
    valid = prepared[prepared.exclusion_reason.isna()]
    coverage = {
        "valid_rows": len(valid),
        "valid_signal_days": valid.signal_ts.nunique(),
        "label_tail_insufficient": int(prepared.return_end_ts.isna().sum()),
        "excluded_by_reason": {
            str(k): int(v) for k, v in prepared.exclusion_reason.dropna().value_counts().items()
        },
        "first_valid_signal": valid.signal_ts.min().isoformat(),
        "last_valid_signal": valid.signal_ts.max().isoformat(),
    }
    return prepared, membership, frame.calendar, daily, coverage


def test_panel_reproduces_original_correlations_counts_gaps_and_tail(panel_fixture):
    prepared, membership, calendar, reference, coverage = panel_fixture
    before = prepared.copy(deep=True)
    panel = subject.build_panel(
        prepared, membership, factor_id="artificial", horizon=1, label_calendar=calendar
    )
    actual, receipt = subject.reconcile_panel(panel, reference, coverage)
    assert receipt["status"] == "matched_original"
    assert list(panel.columns) == subject.PANEL_COLUMNS
    assert len(panel) == 27
    assert len(panel[panel.eligible]) == 21
    assert panel.exclusion_reason.value_counts().to_dict() == {
        "entry_open_missing": 5,
        "exit_open_missing": 1,
    }
    assert panel.return_end_ts.isna().sum() == 4
    assert actual.loc[actual.signal_ts == calendar[-1], "n"].iloc[0] == 0
    assert receipt["max_abs_pearson_difference"] < 1e-12
    assert receipt["max_abs_rankic_difference"] < 1e-12
    pd.testing.assert_frame_equal(prepared, before)
    expected = prepared.set_index(["symbol", "signal_ts"]).value
    assert panel.set_index(["symbol", "signal_ts"]).value.sort_index().equals(expected.sort_index())


@pytest.mark.parametrize(
    "tamper",
    ["entry", "exit", "calendar", "identity", "duplicate_signal", "duplicate_entity", "exclusion"],
)
def test_bad_source_identity_dates_duplicates_or_exclusions_fail(panel_fixture, tamper):
    prepared, membership, calendar, _, _ = panel_fixture
    prepared, membership = prepared.copy(), membership.copy()
    if tamper == "entry":
        prepared.loc[0, "entry_ts"] = calendar[0]
    elif tamper == "exit":
        prepared.loc[0, "return_end_ts"] = calendar[1]
    elif tamper == "calendar":
        calendar = calendar.delete(2)
    elif tamper == "identity":
        membership = membership.iloc[1:]
    elif tamper == "duplicate_signal":
        prepared = pd.concat([prepared, prepared.iloc[:1]], ignore_index=True)
    elif tamper == "duplicate_entity":
        membership.loc[membership.symbol.eq("B"), "entity_id"] = "entity-A"
    else:
        prepared.loc[prepared.exclusion_reason.isna(), "exclusion_reason"] = "fabricated_exclusion"
    with pytest.raises(ValueError, match="contribution_"):
        subject.build_panel(
            prepared, membership, factor_id="artificial", horizon=1, label_calendar=calendar
        )


@pytest.mark.parametrize("tamper", ["correlation", "missingness", "count", "day", "coverage"])
def test_original_receipt_mismatch_cannot_be_marked_matched(panel_fixture, tamper):
    prepared, membership, calendar, reference, coverage = panel_fixture
    panel = subject.build_panel(
        prepared, membership, factor_id="artificial", horizon=1, label_calendar=calendar
    )
    reference, coverage = reference.copy(), dict(coverage)
    if tamper == "correlation":
        reference.loc[0, "ic"] += 0.1
    elif tamper == "missingness":
        reference.loc[0, "rank_ic"] = np.nan
    elif tamper == "count":
        reference.loc[0, "n"] += 1
    elif tamper == "day":
        reference = reference.iloc[1:]
    else:
        coverage["valid_rows"] += 1
    with pytest.raises(ValueError, match="contribution_reference"):
        subject.reconcile_panel(panel, reference, coverage)


def test_source_files_and_imports_cannot_be_substituted(tmp_path):
    archive, run = tmp_path / "archive", tmp_path / "frozen"
    (archive / "src").mkdir(parents=True)
    run.mkdir()
    code = archive / "src/old.py"
    code.write_text("# sealed original code fixture\n")
    artifact = run / "scorecard.json"
    artifact.write_text("{}")
    manifest = run / "output-digests.json"
    manifest.write_text("{}")
    price = tmp_path / "input"
    price.write_bytes(b"sealed input identity fixture")
    plan = {
        "archive_root": str(archive),
        "archive_source_files": {"src/old.py": subject.file_sha(code)},
        "source_run_dir": str(run),
        "source_output_manifest_sha256": subject.file_sha(manifest),
        "source_files": {"scorecard.json": subject.file_sha(artifact)},
        "referenced_input_files": {str(price): subject.file_sha(price)},
    }
    subject.verify_files(plan)
    subject.assert_module_origins([SimpleNamespace(__file__=str(code))], archive)
    with pytest.raises(ValueError, match="wrong_import_source"):
        subject.assert_module_origins([json], archive)
    code.write_text("# changed\n")
    with pytest.raises(ValueError, match="archived_source_changed"):
        subject.verify_files(plan)
    code.write_text("# sealed original code fixture\n")
    price.write_bytes(b"changed input")
    with pytest.raises(ValueError, match="frozen_input_changed"):
        subject.verify_files(plan)


def test_missing_asset_or_factor_warmup_rows_cannot_be_removed(panel_fixture):
    prepared, membership, calendar, _, _ = panel_fixture
    values = prepared[["factor_id", "symbol", "signal_ts", "value"]].copy()
    expected = {
        "expected_member_signal_rows": len(membership),
        "eligible_factor_rows": len(values),
        "warmup_or_missing_input_rows": 0,
    }
    item = {"factor_id": "artificial", "frequency": "daily"}
    subject.reconcile_factor_values(values, membership, calendar, item=item, expected=expected)
    with pytest.raises(ValueError, match="factor_coverage_mismatch"):
        subject.reconcile_factor_values(
            values.iloc[1:], membership, calendar, item=item, expected=expected
        )


def test_constant_cross_section_is_not_fabricated_as_a_perfect_correlation(panel_fixture):
    prepared, membership, calendar, _, _ = panel_fixture
    prepared = prepared.copy()
    prepared["value"] = 0.3
    panel = subject.build_panel(
        prepared, membership, factor_id="artificial", horizon=1, label_calendar=calendar
    )
    daily = subject.daily_correlations(panel)
    assert daily.ic.isna().all() and daily.rank_ic.isna().all()
    assert daily.n.max() == 4


def test_original_unobserved_inner_join_rows_are_explicitly_preserved(panel_fixture):
    prepared, membership, calendar, _, _ = panel_fixture
    raw = prepared[["symbol", "signal_ts", "factor_id", "value"]].copy()
    missing = {"symbol": "A", "signal_ts": calendar[3], "factor_id": "artificial", "value": 123.45}
    raw = pd.concat([raw, pd.DataFrame([missing])], ignore_index=True)
    membership = pd.concat(
        [
            membership,
            pd.DataFrame(
                [
                    {
                        "symbol": "A",
                        "signal_ts": calendar[3],
                        "entity_id": "entity-A",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    observed = pd.DataFrame(True, index=calendar, columns=["A", "B", "C", "D"])
    observed.loc[calendar[3], "A"] = False
    unmatched, audit = subject.preserve_original_join(
        raw,
        prepared,
        membership,
        observed,
        factor_id="artificial",
        horizon=1,
    )
    assert audit["original_factor_value_rows"] == 28
    assert audit["matched_rows"] == 27 and audit["unmatched_rows"] == 1
    assert audit["partition_complete"] is True
    assert unmatched.iloc[0]["value"] == 123.45
    assert unmatched.iloc[0]["entity_id"] == "entity-A"
    assert unmatched.iloc[0]["signal_ts"] == calendar[3]
    assert unmatched.iloc[0]["exclusion_reason"] == "original_loaded_signal_bar_not_observed"
    assert unmatched.eligible.eq(False).all()


@pytest.mark.parametrize(
    "tamper", ["unknown_drop", "invented_row", "raw_value", "duplicate_raw", "unmatched_entity"]
)
def test_no_other_row_loss_or_identity_change_can_hide_as_original_inner_join(
    panel_fixture, tamper
):
    prepared, membership, calendar, _, _ = panel_fixture
    raw = prepared[["symbol", "signal_ts", "factor_id", "value"]].copy()
    observed = pd.DataFrame(True, index=calendar, columns=["A", "B", "C", "D"])
    observed.loc[calendar[3], "A"] = False
    if tamper == "unknown_drop":
        prepared = prepared.iloc[1:]
    elif tamper == "invented_row":
        raw = raw.iloc[1:]
    elif tamper == "raw_value":
        prepared = prepared.copy()
        prepared.loc[0, "value"] += 0.1
    elif tamper == "duplicate_raw":
        raw = pd.concat([raw, raw.iloc[:1]])
    else:
        raw = pd.concat(
            [
                raw,
                pd.DataFrame(
                    [
                        {
                            "symbol": "A",
                            "signal_ts": calendar[3],
                            "factor_id": "artificial",
                            "value": 12.0,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    with pytest.raises(ValueError, match="contribution_"):
        subject.preserve_original_join(
            raw, prepared, membership, observed, factor_id="artificial", horizon=1
        )


def test_explicitly_reused_receipt_keeps_its_original_generator_and_plan(tmp_path):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts/rebuild_factor_contributions.py"
    spec = importlib.util.spec_from_file_location("contribution_runner_test", script)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    out = tmp_path / "out"
    (out / "receipts").mkdir(parents=True)
    for name in ["panel.parquet", "daily.parquet"]:
        (out / name).write_bytes(b"explicit artificial hash fixture")
    task = {"factor_id": "artificial", "horizon": 1}
    original = {
        "plan_digest": "old-plan",
        "implementation": {"script_sha256": "old", "helper_sha256": "old"},
        "status": "matched_original",
        "task": task,
        "panel": {"path": "panel.parquet", "sha256": subject.file_sha(out / "panel.parquet")},
        "daily": {"path": "daily.parquet", "sha256": subject.file_sha(out / "daily.parquet")},
    }
    path = out / "receipts/artificial-h1.json"
    subject.write_new_json(path, original)
    plan = {
        "plan_digest": "new-plan",
        "tasks": [task],
        "reuse_verified_partitions": {
            "receipts": {
                "artificial-h1": {
                    "receipt_sha256": subject.file_sha(path),
                    "plan_digest": "old-plan",
                    "implementation": original["implementation"],
                },
            }
        },
    }
    before = path.read_bytes()
    read = runner._read_completed(out, plan, {"script_sha256": "new", "helper_sha256": "new"})
    assert read["artificial-h1"] == original and path.read_bytes() == before
    changed = dict(original)
    changed["plan_digest"] = "new-plan"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="resume_binding_changed"):
        runner._read_completed(out, plan, {"script_sha256": "new", "helper_sha256": "new"})
