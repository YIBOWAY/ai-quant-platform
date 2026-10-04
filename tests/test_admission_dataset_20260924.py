"""Artificial isolated panels validate the bounded contract, never market performance."""

import json

import exchange_calendars
import pandas as pd
import pytest

from quant_system.research import admission_activation as activation
from quant_system.research import admission_dataset_20260924 as dataset
from quant_system.research import admission_qualifier as qualifier
from tests.test_admission_qualification_flow import recipes


@pytest.fixture
def panel():
    dates = pd.to_datetime(
        exchange_calendars.get_calendar(
            "XNYS", start="2014-01-01", end="2027-01-01"
        ).sessions_in_range(dataset.HISTORY_START, dataset.END),
        utc=True,
    )
    frame = pd.MultiIndex.from_product(
        [dates, [*qualifier.CONTROL_SYMBOLS, "SPY"]], names=["timestamp", "symbol"]
    ).to_frame(index=False)
    return frame.assign(
        open=100.0,
        close=100.0,
        high=101.0,
        low=99.0,
        volume=1000.0,
        provider="futu",
        interval="1d",
        event_ts=frame.timestamp,
        knowledge_ts=frame.timestamp,
        price_adjustment="qfq",
    )


def test_exact_artificial_panel_has_no_missing_session(panel):
    audit = dataset._audit_frame(panel)
    assert audit["price_rows"] == 73725 and audit["evaluation_sessions"] == 2194
    assert audit["missing_sessions"] == 0


@pytest.mark.parametrize("change", ["missing", "duplicate", "provider", "price", "range", "time"])
def test_missing_or_substituted_data_cannot_be_qualified(panel, change):
    if change == "missing":
        panel = panel.iloc[:-1]
    elif change == "duplicate":
        panel.loc[0] = panel.loc[1]
    elif change == "provider":
        panel.loc[0, "provider"] = "sample"
    elif change == "price":
        panel.loc[0, "close"] = float("nan")
    elif change == "range":
        panel.loc[0, "high"] = 90.0
    else:
        panel.loc[0, "knowledge_ts"] = pd.NaT
    with pytest.raises(ValueError, match="september24_"):
        dataset._audit_frame(panel)


@pytest.mark.parametrize("change", [{"end": "2026-09-25"}, {"top_n": 6}, {"commission_bps": 0}])
def test_qualification_window_and_execution_semantics_cannot_expand(change):
    context = {**qualifier.CONTROL_CONTEXT, "end": "2026-09-24"}
    qualifier.require_supported_data_context(dataset.DATASET, context)
    with pytest.raises(ValueError, match="calibration_context_mismatch"):
        qualifier.require_supported_data_context(dataset.DATASET, {**context, **change})


def test_owner_recipe_selects_only_a_matching_bounded_control(tmp_path):
    from types import SimpleNamespace

    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    path = recipes(settings)
    recipe = json.loads(path.read_text())
    recipe["recipes"]["data"]["dataset"] = dataset.DATASET
    path.write_text(json.dumps(recipe))
    with pytest.raises(ValueError, match="data_control_scope_mismatch"):
        activation._owner_scope(settings)
    recipe["recipes"]["consumer"]["control_version"] = dataset.DATASET
    path.write_text(json.dumps(recipe))
    scope = activation._owner_scope(settings)
    assert scope["context"]["end"] == dataset.END
    assert scope["future_inputs_qualified"] is False
    assert activation._scope()["context"]["end"] == "2026-09-18"
    with pytest.raises(ValueError, match="dataset_scope_unsupported"):
        activation._scope("future-any-window")


def test_unrecognized_job_never_creates_frozen_input(tmp_path):
    source = tmp_path / (dataset.JOB_ID + ".json")
    source.write_text("{}")
    with pytest.raises(ValueError, match="original_job_changed"):
        dataset.freeze_inputs(source, tmp_path / "output")
    assert not (tmp_path / "output").exists()
