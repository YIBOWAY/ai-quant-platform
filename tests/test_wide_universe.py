import hashlib
import json

import pandas as pd
import pytest

from quant_system.research.wide_universe import build_fetch_plan, load_wide_universe


def test_fetch_plan_uses_all_members_not_departed_code_inventory(tmp_path):
    membership = tmp_path / "members.csv"
    pd.DataFrame(
        [
            {"month_end": "2015-12-31", "entity_id": "E:A", "ticker_as_of": "A"},
            {"month_end": "2016-01-31", "entity_id": "E:A", "ticker_as_of": "A"},
            {"month_end": "2016-01-31", "entity_id": "E:B", "ticker_as_of": "B"},
        ]
    ).to_csv(membership, index=False)
    plan = build_fetch_plan(membership, [tmp_path], start="2016-01-01", end="2016-01-31")
    assert {r["symbol"] for r in plan["requests"]} == {"A", "B", "SPY"}
    assert plan["member_symbol_count"] == 2
    assert plan["membership_sha256"] == hashlib.sha256(membership.read_bytes()).hexdigest()
    assert all(r["request_start"] < "2015-01-01" for r in plan["requests"])
    assert all(r["request_end"] > "2016-02-20" for r in plan["requests"])


def _inputs(tmp_path, *, missing=False):
    days = pd.date_range("2015-12-01", "2016-02-29", freq="B", tz="UTC")
    frame = pd.DataFrame(
        {
            "date": days,
            "open": 100.0,
            "adjOpen": 10.0,
            "adjHigh": 11.0,
            "adjLow": 9.0,
            "adjClose": 10.0,
            "adjVolume": 50.0,
        }
    )
    frame.to_parquet(tmp_path / "A.parquet")
    pd.DataFrame(
        [
            {"month_end": "2015-12-31", "entity_id": "E:A", "ticker_as_of": "A"},
            {"month_end": "2016-01-31", "entity_id": "E:A", "ticker_as_of": "A"},
        ]
    ).to_csv(tmp_path / "members.csv", index=False)
    pd.DataFrame({"date": days}).to_csv(tmp_path / "calendar.csv", index=False)

    def descriptor(name):
        return {"path": name, "sha256": hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()}

    manifest = {
        "schema_version": "qs.wide_inputs/v1",
        "provider": "tiingo",
        "adjustment": "tiingo_adjusted_ohlcv",
        "usage_restrictions": ["fixture"],
        "signal_window": ["2016-01-01", "2016-01-29"],
        "membership": descriptor("members.csv"),
        "calendar": descriptor("calendar.csv"),
        "prices": {} if missing else {"A": descriptor("A.parquet")},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path, manifest


def test_loader_uses_adjusted_ohlc_and_preserves_missing_prices(tmp_path):
    path, _ = _inputs(tmp_path)
    result = load_wide_universe(path, mode="diagnostic")
    assert set(result.ohlcv.open) == {10.0}
    assert result.report["authority"] == "diagnostic_only"
    assert not result.report["formal_ready"]
    assert len(result.membership) == 21
    with pytest.raises(ValueError, match="formal_inputs_blocked"):
        load_wide_universe(path, mode="formal")


def test_tampered_price_fails_before_reading(tmp_path):
    path, _ = _inputs(tmp_path)
    with (tmp_path / "A.parquet").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="digest_mismatch"):
        load_wide_universe(path)


def test_duplicate_entity_is_rejected_even_if_tickers_differ(tmp_path):
    path, manifest = _inputs(tmp_path)
    members = pd.read_csv(tmp_path / "members.csv")
    duplicate = members.copy()
    duplicate["ticker_as_of"] = "ALIAS"
    pd.concat([members, duplicate]).to_csv(tmp_path / "members.csv", index=False)
    manifest["membership"]["sha256"] = hashlib.sha256(
        (tmp_path / "members.csv").read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="duplicate_membership_entity"):
        load_wide_universe(path)


def test_identity_period_does_not_rewrite_membership_and_is_right_open(tmp_path):
    path, manifest = _inputs(tmp_path)
    for key, row in {
        "entity_periods": {"entity_id": "E:A", "listed_from": "2010-01-01", "listed_to": None},
        "ticker_periods": {
            "entity_id": "E:A",
            "ticker": "A",
            "valid_from": "2010-01-01",
            "valid_to": "2016-01-29",
        },
    }.items():
        file = tmp_path / f"{key}.csv"
        pd.DataFrame([row]).to_csv(file, index=False)
        manifest[key] = {"path": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
    path.write_text(json.dumps(manifest))
    result = load_wide_universe(path)
    assert "identity_period_mismatch" in result.report["blocking_reasons"]
    assert result.membership.signal_ts.max() == pd.Timestamp("2016-01-28", tz="UTC")
    assert result.report["identity_excluded_rows"] == 1


def test_price_warmup_cannot_precede_the_actual_listed_entity(tmp_path):
    path, manifest = _inputs(tmp_path)
    file = tmp_path / "entities.csv"
    pd.DataFrame([{"entity_id": "E:A", "listed_from": "2016-01-04", "listed_to": None}]).to_csv(
        file, index=False
    )
    manifest["entity_periods"] = {
        "path": file.name,
        "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
    }
    path.write_text(json.dumps(manifest))
    result = load_wide_universe(path)
    assert result.ohlcv.timestamp.min() == pd.Timestamp("2016-01-04", tz="UTC")
    assert result.report["inventory"][0]["outside_entity_period_rows"] > 0


def test_missing_prices_remain_in_full_membership_denominator(tmp_path):
    path, _ = _inputs(tmp_path, missing=True)
    result = load_wide_universe(path)
    month = result.report["monthly_coverage"][0]
    assert month["expected_rows"] == 21
    assert month["observed_rows"] == 0
    assert result.report["universe_total"] == result.report["loaded"] + result.report["skipped"]


def test_explicit_mixed_panel_keeps_each_symbols_native_adjusted_basis(tmp_path):
    path, manifest = _inputs(tmp_path)
    file = tmp_path / "SPY.parquet"
    pd.DataFrame(
        {
            "timestamp": pd.date_range("2015-12-01", "2016-02-29", freq="B"),
            "symbol": "SPY",
            "open": 210.0,
            "high": 211.0,
            "low": 209.0,
            "close": 210.0,
            "volume": 999.0,
            "price_adjustment": "qfq",
        }
    ).to_parquet(file)
    cross = tmp_path / "cross-source-check.json"
    cross.write_text(json.dumps({"scope": "synthetic format fixture only"}))
    manifest.update(
        provider="mixed_explicit",
        adjustment="per_symbol_explicit",
        cross_source_check={
            "path": cross.name,
            "sha256": hashlib.sha256(cross.read_bytes()).hexdigest(),
        },
    )
    manifest["prices"]["A"].update(source="tiingo", adjustment="tiingo_adjusted_ohlcv")
    manifest["prices"]["SPY"] = {
        "path": file.name,
        "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        "source": "futu",
        "adjustment": "futu_qfq",
    }
    path.write_text(json.dumps(manifest))
    result = load_wide_universe(path)
    assert set(result.ohlcv[result.ohlcv.symbol == "A"].open) == {10.0}
    assert set(result.ohlcv[result.ohlcv.symbol == "SPY"].open) == {210.0}
    assert result.report["provider"] == "mixed_explicit"
    assert result.report["source_groups"]["futu"]["symbols"] == 1
    assert "cross_source_equivalence_not_universal" in result.report["known_source_limits"]


def test_raw_futu_prices_cannot_be_claimed_as_qfq(tmp_path):
    path, manifest = _inputs(tmp_path)
    file = tmp_path / "A.parquet"
    raw = pd.read_parquet(file).rename(columns={"date": "timestamp"})
    raw["price_adjustment"] = "none"
    raw.to_parquet(file)
    manifest.update(provider="futu", adjustment="futu_qfq")
    manifest["prices"]["A"]["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="futu_qfq_evidence_required"):
        load_wide_universe(path)


def test_duplicate_manifest_price_maps_cannot_silently_replace_source(tmp_path):
    path, _ = _inputs(tmp_path)
    path.write_text(path.read_text()[:-1] + ', "prices": {}}')
    with pytest.raises(ValueError, match="duplicate_manifest_key:prices"):
        load_wide_universe(path)


def test_research_eligibility_is_not_mislabeled_as_listing_date(tmp_path):
    path, manifest = _inputs(tmp_path)
    evidence = tmp_path / "identity-evidence.json"
    evidence.write_text(json.dumps({"A": {"source": "provider", "listing_date": None}}))
    identity = tmp_path / "research-identity.csv"
    pd.DataFrame(
        [
            {
                "entity_id": "E:A",
                "ticker": "A",
                "eligible_not_before": "2015-12-15",
                "eligible_not_after": None,
                "identity_status": "provider_stock_identity",
                "listing_date": None,
                "listing_status": "unknown",
                "ticker_validity_status": "not_independently_verified",
            }
        ]
    ).to_csv(identity, index=False)
    manifest["research_identity"] = {
        "path": identity.name,
        "sha256": hashlib.sha256(identity.read_bytes()).hexdigest(),
    }
    manifest["identity_evidence"] = {
        "path": evidence.name,
        "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
    }
    path.write_text(json.dumps(manifest))
    result = load_wide_universe(path)
    assert result.ohlcv.timestamp.min() == pd.Timestamp("2015-12-15", tz="UTC")
    assert "entity_periods_unverified" not in result.report["blocking_reasons"]
    assert (
        "historical_listing_or_ticker_periods_partially_unknown"
        in result.report["known_source_limits"]
    )
    assert result.report["identity_scope"] == "research_eligibility_only"
    assert not result.report["admission_authority"]


def test_duplicate_raw_bars_fail_closed(tmp_path):
    path, manifest = _inputs(tmp_path)
    file = tmp_path / "A.parquet"
    frame = pd.read_parquet(file)
    pd.concat([frame, frame.iloc[:1]]).to_parquet(file)
    manifest["prices"]["A"]["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="duplicate_price_rows"):
        load_wide_universe(path)


def test_same_price_file_cannot_double_count_an_entity_under_two_names(tmp_path):
    path, manifest = _inputs(tmp_path)
    file = tmp_path / "members.csv"
    members = pd.read_csv(file)
    other = members.assign(entity_id="E:OTHER", ticker_as_of="OTHER")
    pd.concat([members, other]).to_csv(file, index=False)
    manifest["membership"]["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    manifest["prices"]["OTHER"] = manifest["prices"]["A"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="duplicate_price_identity"):
        load_wide_universe(path)


def test_formal_gate_uses_month_end_width_and_monthly_coverage_not_daily_width(tmp_path):
    path, manifest = _inputs(tmp_path)
    days = pd.date_range("2016-01-01", "2016-01-29", freq="B", tz="UTC")
    member_rows, entity_rows, ticker_rows = [], [], []
    manifest["prices"] = {}
    for number in range(300):
        symbol = f"S{number:03}"
        for month in ("2015-12-31", "2016-01-31"):
            member_rows.append({"month_end": month, "entity_id": symbol, "ticker_as_of": symbol})
        entity_rows.append({"entity_id": symbol, "listed_from": "2000-01-01", "listed_to": None})
        ticker_rows.append(
            {"entity_id": symbol, "ticker": symbol, "valid_from": "2000-01-01", "valid_to": None}
        )
        frame = pd.DataFrame(
            {
                "date": days,
                "adjOpen": number + 10.0,
                "adjHigh": number + 11.0,
                "adjLow": number + 9.0,
                "adjClose": number + 10.0,
                "adjVolume": 100.0,
            }
        )
        if number < 20:
            frame = frame.iloc[1:]
        file = tmp_path / f"{symbol}.parquet"
        frame.to_parquet(file)
        manifest["prices"][symbol] = {
            "path": file.name,
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        }
    for key, filename, rows in [
        ("membership", "members.csv", member_rows),
        ("entity_periods", "entities.csv", entity_rows),
        ("ticker_periods", "tickers.csv", ticker_rows),
    ]:
        file = tmp_path / filename
        pd.DataFrame(rows).to_csv(file, index=False)
        manifest[key] = {"path": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
    path.write_text(json.dumps(manifest))
    result = load_wide_universe(path, mode="formal")
    assert result.report["formal_ready"]
    assert result.report["monthly_coverage"][0]["observed_min"] == 280
    assert result.report["monthly_coverage"][0]["month_end_observed"] == 300
    assert "independent_membership_completeness_unverified" in result.report["known_source_limits"]
    assert not result.report["admission_authority"]


def _monthly_inputs(tmp_path, *, snapshots, signal_window):
    sessions = pd.date_range("2015-11-02", "2016-03-31", freq="B", tz="UTC")
    pd.DataFrame(
        {
            "date": sessions,
            "open": 100.0,
            "adjOpen": 10.0,
            "adjHigh": 11.0,
            "adjLow": 9.0,
            "adjClose": 10.0,
            "adjVolume": 50.0,
        }
    ).to_parquet(tmp_path / "A.parquet")
    pd.DataFrame(
        [{"month_end": month, "entity_id": "E:A", "ticker_as_of": "A"} for month in snapshots]
    ).to_csv(tmp_path / "members.csv", index=False)
    pd.DataFrame({"date": sessions}).to_csv(tmp_path / "calendar.csv", index=False)

    def descriptor(name):
        return {"path": name, "sha256": hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()}

    manifest = {
        "schema_version": "qs.wide_inputs/v1",
        "provider": "tiingo",
        "adjustment": "tiingo_adjusted_ohlcv",
        "usage_restrictions": ["fixture"],
        "signal_window": list(signal_window),
        "membership": descriptor("members.csv"),
        "calendar": descriptor("calendar.csv"),
        "prices": {"A": descriptor("A.parquet")},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_membership_snapshot_older_than_45_days_is_refused(tmp_path):
    path = _monthly_inputs(
        tmp_path, snapshots=["2015-11-30"], signal_window=["2016-01-01", "2016-01-29"]
    )
    with pytest.raises(ValueError, match="membership_snapshot_missing_or_stale"):
        load_wide_universe(path)


def test_monthly_snapshot_within_45_days_is_accepted(tmp_path):
    # A missing December snapshot leaves a 32-43 day lag, which normal monthly use can
    # produce; only the stale snapshot itself is refused.
    path = _monthly_inputs(
        tmp_path, snapshots=["2015-12-31"], signal_window=["2016-02-01", "2016-02-12"]
    )
    result = load_wide_universe(path)
    assert not result.membership.empty
    assert set(result.membership.symbol) == {"A"}
