import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from quant_system.research.wide_universe import file_digest

spec = importlib.util.spec_from_file_location(
    "prepare_wide", Path(__file__).parents[1] / "scripts/prepare_phase2_wide_inputs.py"
)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def test_tiingo_availability_start_is_not_claimed_as_listing_date(tmp_path):
    old = tmp_path / "old"
    (old / "meta").mkdir(parents=True)
    pd.DataFrame({"date": pd.date_range("2014-01-02", periods=3), "adjClose": 10.0}).to_parquet(
        old / "A.parquet"
    )
    (old / "meta/A.json").write_text(
        json.dumps(
            {"ticker": "A", "name": "Company A", "exchangeCode": "NYSE", "startDate": "2010-01-01"}
        )
    )
    result = prepare.select_symbol_source("A", old, tmp_path / "new", tmp_path / "futu", {})
    assert result["source"] == "tiingo"
    assert result["listing_date"] is None
    assert result["data_available_from"] == "2010-01-01"


def test_reused_etf_metadata_does_not_win_over_identified_futu_stock(tmp_path):
    old, futu = tmp_path / "old", tmp_path / "futu"
    (old / "meta").mkdir(parents=True)
    futu.mkdir()
    pd.DataFrame({"date": pd.date_range("2014-01-02", periods=3), "adjClose": 10.0}).to_parquet(
        old / "A.parquet"
    )
    (old / "meta/A.json").write_text(
        json.dumps({"ticker": "A", "name": "A DAILY ETF", "exchangeCode": "NYSE"})
    )
    pd.DataFrame({"timestamp": pd.date_range("2014-01-02", periods=3), "close": 20.0}).to_parquet(
        futu / "A.parquet"
    )
    (futu / "A.metadata.json").write_text(
        json.dumps(
            {
                "status": "available",
                "sha256": file_digest(futu / "A.parquet"),
                "metadata": {
                    "code": "US.A",
                    "stock_id": 123,
                    "stock_type": "STOCK",
                    "exchange_type": "US_NYSE",
                    "listing_date": "2000-01-01",
                    "delisting": False,
                },
            }
        )
    )
    result = prepare.select_symbol_source("A", old, tmp_path / "new", futu, {})
    assert result["source"] == "futu"
    assert result["listing_date"] == "2000-01-01"
    assert any(x["reason"] == "metadata_reused_etf" for x in result["rejected"])


def test_known_issuer_aliases_are_deduplicated_without_changing_input():
    original = pd.DataFrame(
        [
            {"month_end": "2016-01-29", "entity_id": "K", "ticker_as_of": "KORS"},
            {"month_end": "2016-01-29", "entity_id": "C", "ticker_as_of": "CPRI"},
        ]
    )
    review = {
        "KORS": {
            "successor": "CPRI",
            "effective_date": "2019-01-02",
            "urls": ["https://www.sec.gov/source"],
        }
    }
    overlay, actions = prepare.build_membership_overlay(original, review)
    assert len(original) == 2
    assert len(overlay) == 1
    assert overlay.iloc[0].ticker_as_of == "KORS"
    assert actions[0]["reason"] == "official_same_issuer_duplicate_snapshot"


def test_futu_reit_type_exception_requires_named_evidence_and_1970_is_unknown(tmp_path):
    futu = tmp_path / "futu"
    futu.mkdir()
    pd.DataFrame({"timestamp": ["2016-01-04"], "close": [10.0]}).to_parquet(futu / "AMT.parquet")
    (futu / "AMT.metadata.json").write_text(
        json.dumps(
            {
                "status": "available",
                "sha256": file_digest(futu / "AMT.parquet"),
                "metadata": {
                    "code": "US.AMT",
                    "stock_id": 1,
                    "stock_type": "ETF",
                    "exchange_type": "US_NYSE",
                    "listing_date": "1970-01-01",
                    "delisting": False,
                },
            }
        )
    )
    assert (
        prepare.select_symbol_source("AMT", tmp_path / "old", tmp_path / "new", futu, {})["source"]
        is None
    )
    accepted = prepare.select_symbol_source(
        "AMT", tmp_path / "old", tmp_path / "new", futu, {}, equity_identity_symbols={"AMT"}
    )
    assert accepted["source"] == "futu"
    assert accepted["listing_date"] is None


def test_official_rename_uses_one_existing_successor_file_without_splicing(tmp_path):
    futu = tmp_path / "futu"
    futu.mkdir()
    pd.DataFrame({"timestamp": ["2016-01-04"], "close": [10.0]}).to_parquet(futu / "META.parquet")
    (futu / "META.metadata.json").write_text(
        json.dumps(
            {
                "status": "available",
                "sha256": file_digest(futu / "META.parquet"),
                "metadata": {
                    "code": "US.META",
                    "stock_id": 2,
                    "stock_type": "STOCK",
                    "exchange_type": "US_NASDAQ",
                    "listing_date": "2012-05-18",
                    "delisting": False,
                },
            }
        )
    )
    accepted = prepare.select_symbol_source(
        "FB", tmp_path / "old", tmp_path / "new", futu, {"FB": {"successor": "META"}}
    )
    assert accepted["source_symbol"] == "META"
    assert accepted["file"] == futu / "META.parquet"


def test_ticker_reuse_does_not_merge_new_qnity_with_old_iqvia():
    original = pd.DataFrame(
        [
            {"month_end": "2017-09-29", "entity_id": "IQV-ISSUER", "ticker_as_of": "Q"},
            {"month_end": "2017-09-29", "entity_id": "IQV-ISSUER", "ticker_as_of": "IQV"},
            {"month_end": "2025-11-28", "entity_id": "QNITY-ISSUER", "ticker_as_of": "Q"},
            {"month_end": "2025-11-28", "entity_id": "IQV-ISSUER", "ticker_as_of": "IQV"},
        ]
    )
    mapping = {
        "Q": {
            "successor": "IQV",
            "effective_date": "2017-11-15",
            "source_entity_ids": ["IQV-ISSUER"],
            "successor_entity_ids": ["IQV-ISSUER"],
        }
    }
    overlay, actions = prepare.build_membership_overlay(original, mapping)
    assert len(overlay[overlay.month_end == "2025-11-28"]) == 2
    assert len(actions) == 1
    assert (
        overlay[(overlay.month_end == "2025-11-28") & (overlay.ticker_as_of == "Q")]
        .iloc[0]
        .entity_id
        == "QNITY-ISSUER"
    )


@pytest.mark.parametrize(
    ("observed_first", "observed_last", "expected"),
    [
        # Membership era starts after the last observed price.
        ("2016-09-01", "2020-01-02", "price_history_starts_after_membership"),
        # Symmetric case: the whole membership era predates the observed prices, so the
        # member contributes zero usable data.
        ("2010-01-04", "2015-11-30", "price_history_ends_before_membership"),
        ("2015-01-02", "2016-12-30", None),
        ("2015-06-01", "2016-06-30", None),
        # One overlapping session is enough to stay loaded.
        ("2015-12-31", "2016-06-30", None),
    ],
)
def test_membership_price_window_is_checked_in_both_directions(
    observed_first, observed_last, expected
):
    assert (
        prepare.membership_price_window_mismatch(
            "VIAC", observed_first, observed_last, "2015-12-31", "2016-08-31"
        )
        == expected
    )


def test_benchmark_membership_column_is_not_a_membership_era():
    assert (
        prepare.membership_price_window_mismatch(
            "SPY", "2020-01-02", "2020-01-03", "2016-01-01", "2016-08-31"
        )
        is None
    )


def test_same_issuer_dual_class_tickers_are_registered_and_not_folded():
    overlay = pd.DataFrame(
        [
            {
                "month_end": "2026-08-31",
                "entity_id": "E:CIK0001652044:GOOGL",
                "source_entity_id": "E:CIK0001652044:GOOGL",
                "ticker_as_of": "GOOGL",
            },
            {
                "month_end": "2026-08-31",
                "entity_id": "E:CIK0001652044:GOOG",
                "source_entity_id": "E:CIK0001652044:GOOG",
                "ticker_as_of": "GOOG",
            },
            {
                "month_end": "2026-08-31",
                "entity_id": "E:CIK0000320193",
                "source_entity_id": "E:CIK0000320193",
                "ticker_as_of": "AAPL",
            },
            {
                "month_end": "2026-07-31",
                "entity_id": "E:CIK0001564708:NWS",
                "source_entity_id": "E:CIK0001564708:NWS",
                "ticker_as_of": "NWS",
            },
        ]
    )
    before = overlay.copy()
    entries = prepare.same_issuer_dual_class_registrations(overlay)
    assert entries == [
        {"month_end": "2026-08-31", "issuer": "E:CIK0001652044", "tickers": ["GOOG", "GOOGL"]}
    ]
    assert overlay.equals(before)
    assert prepare.issuer_prefix("E:CIK0001652044:GOOG") == "E:CIK0001652044"
    assert prepare.issuer_prefix("E:CIK0000320193") == "E:CIK0000320193"


def test_non_cik_entity_ids_are_not_merged_into_one_fake_issuer():
    # Real membership ids outside the CIK scheme (E:X:<slug>, lineage markers) share no
    # issuer, so they must never be registered as classes of one company.
    overlay = pd.DataFrame(
        [
            {
                "month_end": "2016-01-29",
                "entity_id": "E:X:aaba",
                "source_entity_id": "E:X:aaba",
                "ticker_as_of": "AABA",
            },
            {
                "month_end": "2016-01-29",
                "entity_id": "E:X:aamrq",
                "source_entity_id": "E:X:aamrq",
                "ticker_as_of": "AAMRQ",
            },
            {
                "month_end": "2016-01-29",
                "entity_id": "E:OFFICIAL_LINEAGE:KORS",
                "source_entity_id": "E:CIK0001346896",
                "ticker_as_of": "KORS",
            },
        ]
    )
    assert prepare.same_issuer_dual_class_registrations(overlay) == []
    assert prepare.issuer_prefix("E:X:aaba") == "E:X:aaba"
    assert prepare.issuer_prefix("E:OFFICIAL_LINEAGE:KORS") == "E:OFFICIAL_LINEAGE:KORS"
