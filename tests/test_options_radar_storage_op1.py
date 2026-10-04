from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from quant_system.options.models import OptionsScreenerCandidate
from quant_system.options.radar import OptionsRadarCandidate, OptionsRadarReport
from quant_system.options.radar_storage import RadarSnapshotStore, _candidate_to_json
from quant_system.options.seller_score import (
    evaluate_seller_recommendation,
    score_seller_contract,
)


def _candidate(index: int) -> OptionsRadarCandidate:
    strike = 400.0 + index
    quote_as_of = "2026-08-20 15:59:00"
    evaluation = evaluate_seller_recommendation(
        strategy_type="sell_put",
        strike=strike,
        underlying_price=450.0,
        mid=15.0,
        spread_pct=0.20 / 15.0,
        open_interest=500.0,
        delta=-0.20,
        days_to_expiry=29,
        implied_volatility=0.22,
        iv_rank=62.0,
        risk_free_rate=0.0387,
        run_date="2026-08-20",
        expiry="2026-09-18",
        earnings_date=None,
        is_etf=True,
        ex_dividend_date=None,
        dividend_per_share=None,
        quote_as_of=quote_as_of,
    )
    assert evaluation.hard_gate_passed is True
    assert evaluation.quote_as_of is not None
    quote_as_of = evaluation.quote_as_of
    seller_score = score_seller_contract(
        annualized_yield=evaluation.gross_annualized_yield,
        spread_pct=0.20 / 15.0,
        open_interest=500.0,
        volume=None,
        delta=-0.20,
        hv_iv_ratio=None,
        iv_rank=62.0,
    )
    option = OptionsScreenerCandidate(
        symbol=f"US.SPY260918P{int(strike * 1000):08d}",
        underlying="US.SPY",
        strategy_type="sell_put",
        option_type="PUT",
        expiry="2026-09-18",
        strike=strike,
        underlying_price=450.0,
        bid=14.9,
        ask=15.1,
        mid=15.0,
        open_interest=500.0,
        implied_volatility=0.22,
        delta=-0.20,
        days_to_expiry=29,
        annualized_yield=evaluation.gross_annualized_yield,
        spread_pct=0.20 / 15.0,
        iv_rank=62.0,
        rating="Strong",
        seller_score=seller_score,
        quote_as_of=quote_as_of,
    )
    return OptionsRadarCandidate(
        ticker="SPY",
        sector="ETF",
        strategy="sell_put",
        candidate=option,
        iv_rank=62.0,
        earnings_in_window=False,
        global_score=seller_score.composite,
        iv_history_samples=30,
        iv_rank_status="ready",
        gross_annualized_yield=evaluation.gross_annualized_yield,
        pop=evaluation.pop,
        otm_pct=evaluation.otm_pct,
        extrinsic_value=evaluation.extrinsic_value,
        breakeven=evaluation.breakeven,
        take_profit_50_price=evaluation.take_profit_50_price,
        manage_at_21_dte=evaluation.manage_at_21_dte,
        expected_value=evaluation.expected_value,
        excess_annualized_ev=evaluation.excess_annualized_ev,
        liquidity_factor=evaluation.liquidity_factor,
        recommendation_score=evaluation.recommendation_score,
        recommendation_score_model=evaluation.recommendation_score_model,
        hard_gate_passed=True,
        quote_as_of=quote_as_of,
    )


def _rewrite_bound_data(
    data_path: Path,
    meta_path: Path,
    payloads: list[dict],
) -> None:
    data = "".join(json.dumps(payload, sort_keys=True) + "\n" for payload in payloads).encode()
    data_path.write_bytes(data)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["data_sha256"] = sha256(data).hexdigest()
    meta["data_line_count"] = len(payloads)
    meta["candidate_count"] = len(payloads)
    meta_path.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")


def test_radar_snapshot_round_trips_op1_provenance_and_caps_top20(
    tmp_path: Path,
) -> None:
    candidates = [_candidate(index) for index in range(21)]
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=candidates,
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=0,
        shortfall_reasons={},
    )
    store = RadarSnapshotStore(tmp_path)

    data_path, _meta_path = store.write(report)
    loaded = store.read("2026-08-20")

    meta = json.loads(_meta_path.read_text(encoding="utf-8"))
    assert meta["data_file"] == data_path.name
    assert data_path.name == f"2026-08-20.{meta['snapshot_generation']}.jsonl"
    assert not (tmp_path / "2026-08-20.jsonl").exists()
    assert len(data_path.read_text(encoding="utf-8").splitlines()) == 20
    assert len(loaded.candidates) == 20
    assert loaded.provider == "futu"
    assert loaded.as_of == "2026-08-20T19:59:00Z"
    assert loaded.status == "available"
    assert loaded.risk_free_rate == 0.0387
    assert loaded.shortfall_count == 0
    assert loaded.shortfall_reasons == {}
    assert [item.recommendation_score for item in loaded.candidates] == pytest.approx(
        sorted(
            (item.recommendation_score for item in candidates if item.recommendation_score),
            reverse=True,
        )[:20]
    )
    first = loaded.candidates[0]
    assert first.hard_gate_passed is True
    assert first.recommendation_score_model == "seller_ev_liquidity_v1"
    assert first.quote_as_of == "2026-08-20T19:59:00Z"
    assert first.gross_annualized_yield is not None
    assert first.manage_at_21_dte == "2026-08-28"


def test_snapshot_writer_rejects_duplicate_candidate_identity_without_files(
    tmp_path: Path,
) -> None:
    candidate = _candidate(0)
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[candidate, candidate],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )

    with pytest.raises(ValueError, match="snapshot candidate identity duplicated"):
        RadarSnapshotStore(tmp_path).write(report)

    assert list(tmp_path.iterdir()) == []


def test_snapshot_writer_rejects_duplicate_identity_before_top20_cap(
    tmp_path: Path,
) -> None:
    unique = [replace(_candidate(index), recommendation_score=100.0 - index) for index in range(21)]
    duplicate_outside_cap = replace(unique[-1], recommendation_score=-100.0)
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[*unique, duplicate_outside_cap],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )

    with pytest.raises(ValueError, match="snapshot candidate identity duplicated"):
        RadarSnapshotStore(tmp_path).write(report)

    assert list(tmp_path.iterdir()) == []


def test_existing_v2_snapshot_does_not_require_new_screener_only_fields(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    for field in (
        "earnings_in_window",
        "ex_dividend_date",
        "ex_dividend_in_window",
        "dividend_per_share",
        "extrinsic_value",
        "gross_annualized_yield",
        "pop",
        "otm_pct",
        "breakeven",
        "take_profit_50_price",
        "manage_at_21_dte",
        "expected_value",
        "excess_annualized_ev",
        "liquidity_factor",
        "recommendation_score",
        "recommendation_score_model",
        "hard_gate_passed",
        "recommendation_rejection_reasons",
    ):
        payload["candidate"].pop(field, None)
    _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "available"
    assert len(loaded.candidates) == 1


def test_snapshot_write_binds_generation_exact_sha_and_line_count(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )

    data_path, meta_path = RadarSnapshotStore(tmp_path).write(report)
    data = data_path.read_bytes()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    assert isinstance(meta["snapshot_generation"], str)
    assert meta["snapshot_generation"]
    assert meta["data_sha256"] == sha256(data).hexdigest()
    assert meta["data_line_count"] == 1
    assert meta["candidate_count"] == 1


def test_snapshot_read_rejects_twenty_first_line_before_top20_truncation(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(index) for index in range(20)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=0,
        shortfall_reasons={},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, _meta_path = store.write(report)
    data_path.write_bytes(
        data_path.read_bytes()
        + (json.dumps(_candidate_to_json("2026-08-20", _candidate(20))) + "\n").encode()
    )

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_snapshot_rejects_ticker_underlying_mismatch_even_with_valid_sha(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["candidate"]["underlying"] = "US.QQQ"
    _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_snapshot_rejects_contract_symbol_underlying_mismatch_with_valid_sha(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["candidate"]["symbol"] = "US.AAPL260918P000400"
    _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


@pytest.mark.parametrize(
    "forged_symbol",
    (
        "US.SPY261218P00400000",
        "US.SPY260918C00400000",
        "US.SPY260918P00999000",
    ),
)
def test_snapshot_rejects_contract_symbol_field_mismatch_with_valid_sha(
    tmp_path: Path,
    forged_symbol: str,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["candidate"]["symbol"] = forged_symbol
    _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_snapshot_rejects_non_curated_ticker_with_valid_sha(tmp_path: Path) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["ticker"] = "FAKE"
    payload["candidate"]["underlying"] = "US.FAKE"
    payload["candidate"]["symbol"] = "US.FAKE260918P000400"
    _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


def test_snapshot_sector_non_string_is_typed_unavailable(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["sector"] = ["ETF"]
    _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


@pytest.mark.parametrize(
    "override",
    [
        {"mid": 14.8},
        {"spread_pct": 0.001},
        {"bid": 15.2, "ask": 15.1},
    ],
)
def test_snapshot_rejects_bid_ask_mid_spread_inconsistency_with_valid_sha(
    tmp_path: Path,
    override: dict,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["candidate"].update(override)
    _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


@pytest.mark.parametrize(
    ("target", "raw"),
    [
        ("data", b'{"ticker":'),
        ("data", b"[]\n"),
        ("data", b"\xff\n"),
        ("meta", b"{"),
        ("meta", b"[]"),
        ("meta", b"\xff"),
    ],
)
def test_snapshot_invalid_data_or_meta_is_typed_unavailable(
    tmp_path: Path,
    target: str,
    raw: bytes,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    if target == "data":
        data_path.write_bytes(raw)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["data_sha256"] = sha256(raw).hexdigest()
        meta["data_line_count"] = 1
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    else:
        meta_path.write_bytes(raw)

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


@pytest.mark.parametrize("target", ["data", "meta"])
def test_snapshot_rejects_duplicate_json_object_keys(
    tmp_path: Path,
    target: str,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    if target == "data":
        data = (
            data_path.read_text(encoding="utf-8")
            .replace(
                "{",
                '{"ticker":"QQQ",',
                1,
            )
            .encode()
        )
        data_path.write_bytes(data)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["data_sha256"] = sha256(data).hexdigest()
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    else:
        meta = meta_path.read_text(encoding="utf-8").replace(
            "{",
            '{"run_date":"2099-01-01",',
            1,
        )
        meta_path.write_text(meta, encoding="utf-8")

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("universe_size", "bad"),
        ("candidate_count", True),
        ("failed_tickers", [["SPY"]]),
        ("shortfall_reasons", {"bad": -1}),
        ("provider", ["futu"]),
        ("status", ["available"]),
    ],
)
def test_snapshot_corrupt_meta_field_types_are_typed_unavailable(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    _data_path, meta_path = store.write(report)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta[field] = value
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


@pytest.mark.parametrize("target", ["meta", "row"])
def test_snapshot_rejects_meta_row_or_requested_run_date_mismatch(
    tmp_path: Path,
    target: str,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    if target == "meta":
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["run_date"] = "2026-08-19"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    else:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        payload["run_date"] = "2026-08-19"
        _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


def test_snapshot_rejects_duplicate_candidate_identity_with_valid_sha(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=18,
        shortfall_reasons={"eligible_contracts_below_limit": 18},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    _rewrite_bound_data(data_path, meta_path, [payload, payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


def test_snapshot_rejects_case_variant_duplicate_identity_with_valid_sha(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    variant = {**payload, "ticker": "spy"}
    _rewrite_bound_data(data_path, meta_path, [payload, variant])
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["shortfall_count"] = 18
    meta["shortfall_reasons"]["eligible_contracts_below_limit"] = 18
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


@pytest.mark.parametrize("missing", ["data", "meta"])
def test_snapshot_partial_pair_is_typed_unavailable(
    tmp_path: Path,
    missing: str,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    (data_path if missing == "data" else meta_path).unlink()

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_snapshot_meta_commit_failure_never_exposes_new_data_as_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def report(candidate: OptionsRadarCandidate) -> OptionsRadarReport:
        return OptionsRadarReport(
            run_date="2026-08-20",
            started_at="2026-08-20T20:00:00Z",
            finished_at="2026-08-20T20:20:00Z",
            universe_size=34,
            expected_universe_size=34,
            scanned_tickers=34,
            failed_tickers=[],
            candidates=[candidate],
            provider="futu",
            as_of="2026-08-20 15:59:00",
            status="available",
            risk_free_rate=0.0387,
            shortfall_count=19,
            shortfall_reasons={"eligible_contracts_below_limit": 19},
        )

    store = RadarSnapshotStore(tmp_path)
    _data_path, meta_path = store.write(report(_candidate(0)))
    original_replace = Path.replace

    def fail_meta_replace(source: Path, target: Path):
        if Path(target) == meta_path:
            raise OSError("injected meta commit failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_meta_replace)
    with pytest.raises(OSError, match="injected meta commit failure"):
        store.write(report(_candidate(1)))

    loaded = store.read("2026-08-20")

    assert loaded.status == "available"
    assert len(loaded.candidates) == 1
    assert loaded.candidates[0].candidate.strike == _candidate(0).candidate.strike


def test_same_day_snapshot_rejects_older_as_of_and_keeps_current_generation(
    tmp_path: Path,
) -> None:
    def report(*, candidate: OptionsRadarCandidate, as_of: str) -> OptionsRadarReport:
        return OptionsRadarReport(
            run_date="2026-08-20",
            started_at="2026-08-20T20:00:00Z",
            finished_at="2026-08-20T20:20:00Z",
            universe_size=34,
            expected_universe_size=34,
            scanned_tickers=34,
            failed_tickers=[],
            candidates=[candidate],
            provider="futu",
            as_of=as_of,
            status="available",
            risk_free_rate=0.0387,
            shortfall_count=19,
            shortfall_reasons={"eligible_contracts_below_limit": 19},
        )

    store = RadarSnapshotStore(tmp_path)
    first_data, meta_path = store.write(
        report(candidate=_candidate(0), as_of="2026-08-20 15:59:00")
    )
    first_meta = meta_path.read_bytes()

    with pytest.raises(ValueError, match="snapshot_as_of_regression"):
        store.write(report(candidate=_candidate(1), as_of="2026-08-20 15:58:00"))

    assert meta_path.read_bytes() == first_meta
    assert first_data.exists()
    loaded = store.read("2026-08-20")
    assert loaded.status == "available"
    assert loaded.candidates[0].candidate.strike == _candidate(0).candidate.strike


@pytest.mark.parametrize(
    "data_file",
    [
        "../outside.jsonl",
        "/tmp/outside.jsonl",
        "2026-08-20.wrong-generation.jsonl",
    ],
)
def test_snapshot_rejects_unsafe_or_generation_mismatched_data_pointer(
    tmp_path: Path,
    data_file: str,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    store = RadarSnapshotStore(tmp_path)
    _data_path, meta_path = store.write(report)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["data_file"] = data_file
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    loaded = store.read(report.run_date)

    assert loaded.status == "unavailable"
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_snapshot_preserves_successful_candidates_from_partial_scan(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=33,
        failed_tickers=[("BRK.B", "FutuProviderError:connection_failed")],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"universe_scan_incomplete": 1},
    )
    store = RadarSnapshotStore(tmp_path)
    store.write(report)

    loaded = store.read("2026-08-20")

    assert loaded.status == "available"
    assert len(loaded.candidates) == 1
    assert loaded.scanned_tickers == 33
    assert loaded.failed_tickers == [("BRK.B", "FutuProviderError:connection_failed")]
    assert loaded.shortfall_reasons["universe_scan_incomplete"] == 1


@pytest.mark.parametrize(
    ("scanned_tickers", "failed_tickers"),
    [
        (
            33,
            [
                ["BRK.B", "FutuProviderError:connection_failed"],
                ["BRK.B", "FutuProviderError:connection_failed"],
            ],
        ),
        (33, [["NOT_CURATED", "FutuProviderError:connection_failed"]]),
        (32, [["BRK.B", "FutuProviderError:connection_failed"]]),
    ],
)
def test_snapshot_rejects_forged_partial_coverage_metadata(
    tmp_path: Path,
    scanned_tickers: int,
    failed_tickers: list[list[str]],
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=33,
        failed_tickers=[("BRK.B", "FutuProviderError:connection_failed")],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"universe_scan_incomplete": 1},
    )
    store = RadarSnapshotStore(tmp_path)
    _data_path, meta_path = store.write(report)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["scanned_tickers"] = scanned_tickers
    meta["failed_tickers"] = failed_tickers
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    loaded = store.read(report.run_date)

    assert loaded.status == "unavailable"
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_snapshot_rejects_candidate_ticker_also_listed_as_failed(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=33,
        failed_tickers=[("BRK.B", "FutuProviderError:connection_failed")],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"universe_scan_incomplete": 1},
    )
    store = RadarSnapshotStore(tmp_path)
    _data_path, meta_path = store.write(report)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["failed_tickers"] = [["SPY", "FutuProviderError:connection_failed"]]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    loaded = store.read(report.run_date)

    assert loaded.status == "unavailable"
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_snapshot_writer_requires_bound_expected_universe_size(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=33,
        expected_universe_size=34,
        scanned_tickers=33,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )

    with pytest.raises(ValueError, match="expected_universe_size_required"):
        RadarSnapshotStore(tmp_path).write(report)

    assert list(tmp_path.iterdir()) == []


def test_snapshot_rejects_forged_shortfall_metadata(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=0,
        shortfall_reasons={},
    )
    store = RadarSnapshotStore(tmp_path)
    _data_path, meta_path = store.write(report)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["shortfall_count"] == 19
    assert meta["shortfall_reasons"]["eligible_contracts_below_limit"] == 19
    meta["shortfall_count"] = 0
    meta["shortfall_reasons"] = {}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


def test_radar_snapshot_legacy_contract_reads_typed_unavailable(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-19",
        started_at="2026-08-19T20:00:00Z",
        finished_at="2026-08-19T20:20:00Z",
        universe_size=100,
        expected_universe_size=100,
        scanned_tickers=100,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-19 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )
    store = RadarSnapshotStore(tmp_path)
    _data_path, meta_path = store.write(report)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("contract_version", None)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    loaded = store.read("2026-08-19")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.as_of is None
    assert loaded.shortfall_count == 20
    assert loaded.shortfall_reasons == {"legacy_snapshot_contract": 1}


def test_radar_snapshot_missing_required_true_input_reads_unavailable(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, _meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["candidate"]["days_to_expiry"] = None
    data_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_radar_snapshot_rechecks_numeric_hard_gates_instead_of_trusting_flag(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, _meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["candidate"].update(
        {
            "mid": 0.01,
            "spread_pct": 0.90,
            "open_interest": 1,
            "delta": -0.90,
            "days_to_expiry": 100,
        }
    )
    payload["hard_gate_passed"] = True
    data_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_radar_snapshot_rejects_conflicting_duplicate_contract_fields(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )
    store = RadarSnapshotStore(tmp_path)

    for field, value in (
        ("iv_rank", None),
        ("strategy", "covered_call"),
        ("quote_as_of", "2026-08-20 15:58:00"),
    ):
        data_path, _meta_path = store.write(report)
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        payload[field] = value
        data_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

        loaded = store.read("2026-08-20")

        assert loaded.status == "unavailable"
        assert loaded.candidates == []


def test_radar_snapshot_rejects_status_and_row_count_mismatch(tmp_path: Path) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )
    store = RadarSnapshotStore(tmp_path)
    _data_path, meta_path = store.write(report)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["status"] = "empty"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_radar_snapshot_recomputes_derived_ev_fields_from_raw_inputs(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, _meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["expected_value"] = 999.0
    payload["excess_annualized_ev"] = 999.0
    payload["recommendation_score"] = 999.0 * payload["liquidity_factor"]
    data_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []
    assert loaded.shortfall_reasons == {"invalid_recommendation_snapshot": 1}


def test_radar_snapshot_rejects_boolean_iv_rank_with_valid_sha(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["iv_rank"] = True
    payload["candidate"]["iv_rank"] = True
    _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("gamma", True),
        ("historical_volatility", True),
        ("avg_daily_volume", True),
        ("trend_pass", 1),
    ],
)
def test_radar_snapshot_rejects_invalid_ancillary_option_field_types(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["candidate"][field] = value
    _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


def test_radar_snapshot_rejects_forged_legacy_global_score_with_valid_sha(
    tmp_path: Path,
) -> None:
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    payload["global_score"] = 100.0
    _rewrite_bound_data(data_path, meta_path, [payload])

    loaded = store.read("2026-08-20")

    assert loaded.status == "unavailable"
    assert loaded.candidates == []


def test_radar_snapshot_accepts_older_raw_watermark_with_mixed_timestamp_forms(
    tmp_path: Path,
) -> None:
    base = _candidate(0)
    quote_as_of = "2026-08-20T20:00:00Z"
    candidate = replace(
        base,
        candidate=base.candidate.model_copy(update={"quote_as_of": quote_as_of}),
        quote_as_of=quote_as_of,
    )
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[candidate],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
    )

    RadarSnapshotStore(tmp_path).write(report)
    loaded = RadarSnapshotStore(tmp_path).read("2026-08-20")

    assert loaded.status == "available"
    assert len(loaded.candidates) == 1
    assert loaded.as_of == "2026-08-20T19:59:00Z"


@pytest.mark.parametrize("score_delta, expected", [(1e-14, "available"), (1e-7, "unavailable")])
def test_snapshot_score_recomputation_tolerates_only_roundoff(
    tmp_path: Path,
    score_delta: float,
    expected: str,
) -> None:
    """A JSON roundtrip must not erase a generation for a one-ULP score gap."""
    report = OptionsRadarReport(
        run_date="2026-08-20",
        started_at="2026-08-20T20:00:00Z",
        finished_at="2026-08-20T20:20:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[_candidate(0)],
        provider="futu",
        as_of="2026-08-20 15:59:00",
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={},
    )
    store = RadarSnapshotStore(tmp_path)
    data_path, meta_path = store.write(report)
    payloads = [json.loads(line) for line in data_path.read_text().splitlines()]
    payloads[0]["candidate"]["seller_score"]["composite"] += score_delta
    _rewrite_bound_data(data_path, meta_path, payloads)
    assert store.read("2026-08-20").status == expected
