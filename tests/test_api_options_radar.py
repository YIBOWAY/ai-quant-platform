from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import OptionsRadarSettings, Settings
from quant_system.options.models import OptionsScreenerCandidate
from quant_system.options.radar import OptionsRadarCandidate, OptionsRadarReport
from quant_system.options.radar_storage import RadarSnapshotStore
from quant_system.options.seller_score import (
    evaluate_seller_recommendation,
    latest_us_market_session,
    score_seller_contract,
)


def test_api_diversifies_existing_concentrated_snapshot(tmp_path, monkeypatch) -> None:
    from dataclasses import replace

    from quant_system.api.routes import options_radar as route

    run_date = "2026-05-01"
    _write_sample_snapshot(tmp_path, run_date)
    report = RadarSnapshotStore(tmp_path).read(run_date)
    row = report.candidates[0]
    concentrated = replace(report, candidates=[
        *[replace(row, ticker="AAPL", recommendation_score=1.0 - i / 100) for i in range(10)],
        replace(row, ticker="SPY", recommendation_score=0.50),
    ])
    monkeypatch.setattr(RadarSnapshotStore, "read", lambda self, _: concentrated)
    monkeypatch.setattr(route, "_utc_now", lambda: datetime(2026, 5, 1, 21, 0, tzinfo=UTC))
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))

    payload = route.options_daily_scan(settings)
    assert [row["ticker"] for row in payload["candidates"]] == ["AAPL", "AAPL", "SPY"]
    assert payload["shortfall_count"] == 17
    assert payload["shortfall_reasons"]["ticker_concentration_limit"] == 8


def test_api_daily_scan_candidate_count_matches_visible_rows_and_shortfall(
    tmp_path,
) -> None:
    from quant_system.api.routes import options_radar as route
    from quant_system.options.radar_storage import RECOMMENDATION_LIMIT

    run_date = "2026-05-01"
    _write_sample_snapshot(tmp_path, run_date)
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))

    payload = route.options_daily_scan(settings)
    assert payload["candidate_count"] == len(payload["candidates"])
    assert payload["shortfall_count"] == max(RECOMMENDATION_LIMIT - len(payload["candidates"]), 0)

    filtered = route.options_daily_scan(settings, strategy="sell_put")
    assert filtered["candidate_count"] == len(filtered["candidates"])
    assert filtered["shortfall_count"] == max(
        RECOMMENDATION_LIMIT - len(filtered["candidates"]), 0
    )

    empty = route.options_daily_scan(settings, strategy="covered_call")
    assert empty["candidate_count"] == len(empty["candidates"])
    assert empty["shortfall_count"] == max(RECOMMENDATION_LIMIT - len(empty["candidates"]), 0)


def test_api_daily_scan_symbol_shortfall_matches_its_visible_rows(tmp_path) -> None:
    from quant_system.api.routes import options_radar as route
    from quant_system.options.radar_storage import RECOMMENDATION_LIMIT

    run_date = "2026-05-01"
    _write_sample_snapshot(tmp_path, run_date)
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))

    payload = route.options_daily_scan_symbol(settings, ticker="SPY")
    assert payload["candidate_count"] == len(payload["candidates"])
    assert payload["shortfall_count"] == max(RECOMMENDATION_LIMIT - len(payload["candidates"]), 0)


def _write_sample_snapshot(root: Path, run_date: str = "2026-05-03") -> None:
    quote_session = latest_us_market_session(date.fromisoformat(run_date))
    expiry = (quote_session + timedelta(days=47)).isoformat()
    quote_as_of = f"{quote_session.isoformat()} 15:59:00"
    evaluation = evaluate_seller_recommendation(
        strategy_type="sell_put",
        strike=450.0,
        underlying_price=500.0,
        mid=30.0,
        spread_pct=1.0 / 30.0,
        open_interest=500.0,
        delta=-0.24,
        days_to_expiry=47,
        implied_volatility=0.32,
        iv_rank=72.5,
        risk_free_rate=0.0387,
        run_date=run_date,
        expiry=expiry,
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
        spread_pct=1.0 / 30.0,
        open_interest=500.0,
        volume=None,
        delta=-0.24,
        hv_iv_ratio=None,
        iv_rank=72.5,
    )
    option = OptionsScreenerCandidate(
        symbol=(f"US.SPY{expiry[2:4]}{expiry[5:7]}{expiry[8:10]}P{int(450.0 * 1000):08d}"),
        underlying="US.SPY",
        strategy_type="sell_put",
        option_type="PUT",
        expiry=expiry,
        strike=450.0,
        underlying_price=500.0,
        bid=29.5,
        ask=30.5,
        mid=30.0,
        open_interest=500.0,
        implied_volatility=0.32,
        delta=-0.24,
        days_to_expiry=47,
        annualized_yield=evaluation.gross_annualized_yield,
        spread_pct=1.0 / 30.0,
        iv_rank=72.5,
        rating="Strong",
        seller_score=seller_score,
        quote_as_of=quote_as_of,
    )
    candidate = OptionsRadarCandidate(
        ticker="SPY",
        sector="ETF",
        strategy="sell_put",
        candidate=option,
        iv_rank=72.5,
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
    report = OptionsRadarReport(
        run_date=run_date,
        started_at=f"{run_date}T20:00:00Z",
        finished_at=f"{run_date}T20:01:00Z",
        universe_size=34,
        expected_universe_size=34,
        scanned_tickers=34,
        failed_tickers=[],
        candidates=[candidate],
        provider="futu",
        as_of=quote_as_of,
        status="available",
        risk_free_rate=0.0387,
        shortfall_count=19,
        shortfall_reasons={"eligible_contracts_below_limit": 19},
    )
    RadarSnapshotStore(root).write(report)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _bind_api_snapshot_data(root: Path, run_date: str, data: bytes) -> None:
    meta_path = root / f"{run_date}_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    data_path = root / meta["data_file"]
    data_path.write_bytes(data)
    meta["data_sha256"] = sha256(data).hexdigest()
    meta["data_line_count"] = len(data.splitlines())
    meta["candidate_count"] = len(data.splitlines())
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def test_api_options_daily_scan_lists_dates_and_returns_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_date = "2026-05-01"
    _write_sample_snapshot(tmp_path, run_date)
    monkeypatch.setattr(
        "quant_system.api.routes.options_radar._utc_now",
        lambda: datetime(2026, 5, 1, 21, 0, tzinfo=UTC),
    )
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    dates_response = client.get("/api/options/daily-scan/dates")
    snapshot_response = client.get(
        "/api/options/daily-scan",
        params={"date": run_date, "strategy": "sell_put", "top": 1},
    )

    assert dates_response.status_code == 200
    assert dates_response.json()["dates"] == [run_date]
    assert snapshot_response.status_code == 200
    payload = snapshot_response.json()
    assert payload["run_date"] == run_date
    assert len(payload["candidates"]) == 1
    candidate_payload = payload["candidates"][0]
    assert candidate_payload["strategy"] == "sell_put"
    assert candidate_payload["iv_history_samples"] == 30
    assert candidate_payload["iv_rank_status"] == "ready"
    assert "global_score" in candidate_payload
    assert "rating" not in candidate_payload
    assert "notes" not in candidate_payload
    assert payload["safety"]["live_trading_enabled"] is False


def test_api_options_daily_scan_defaults_to_latest_date(tmp_path: Path) -> None:
    run_date = "2026-05-02"
    older_date = "2026-05-01"
    _write_sample_snapshot(tmp_path, older_date)
    _write_sample_snapshot(tmp_path, run_date)
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/options/daily-scan")

    assert response.status_code == 200
    assert response.json()["run_date"] == run_date


def test_snapshot_freshness_uses_quote_session_not_run_date() -> None:
    from quant_system.api.routes.options_radar import _snapshot_freshness

    now = datetime(2026, 8, 22, 4, 0, tzinfo=UTC)

    stale = _snapshot_freshness(
        "2026-08-21",
        "2026-07-02 09:30:00",
        [],
        now=now,
    )
    weekend_fresh = _snapshot_freshness(
        "2026-08-22",
        "2026-08-21 15:59:00",
        [],
        now=now,
    )

    assert stale["is_stale"] is True
    assert stale["snapshot_age_days"] == 50
    assert weekend_fresh["is_stale"] is False
    assert weekend_fresh["snapshot_age_days"] == 0


def test_api_stale_snapshot_returns_zero_recommendations(tmp_path: Path) -> None:
    _write_sample_snapshot(tmp_path, "2026-05-01")
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(
        "/api/options/daily-scan",
        params={"date": "2026-05-01"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["is_stale"] is True
    assert payload["shortfall_reasons"]["snapshot_stale"] == 1
    assert payload["candidates"] == []


def test_api_stale_empty_snapshot_is_unavailable_for_list_and_symbol(
    tmp_path: Path,
) -> None:
    run_date = "2026-08-21"
    RadarSnapshotStore(tmp_path).write(
        OptionsRadarReport(
            run_date=run_date,
            started_at="2026-08-21T20:00:00Z",
            finished_at="2026-08-21T20:01:00Z",
            universe_size=34,
            expected_universe_size=34,
            scanned_tickers=34,
            failed_tickers=[],
            candidates=[],
            provider="futu",
            as_of="2026-07-02 09:30:00",
            status="empty",
            risk_free_rate=0.0387,
            shortfall_count=20,
            shortfall_reasons={"quote_stale": 1},
        )
    )
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    listing = client.get("/api/options/daily-scan", params={"date": run_date})
    symbol = client.get(
        "/api/options/daily-scan/symbol/SPY",
        params={"date": run_date},
    )

    for response in (listing, symbol):
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "unavailable"
        assert payload["is_stale"] is True
        assert payload["shortfall_reasons"]["snapshot_stale"] == 1
        assert payload["candidates"] == []


@pytest.mark.parametrize(
    "corruption",
    [
        "truncated_data",
        "non_object_data",
        "truncated_meta",
        "invalid_meta_type",
        "invalid_provider_type",
        "invalid_sector_type",
        "boolean_iv_rank",
        "twenty_one_rows",
        "duplicate_json_key",
        "ticker_underlying_mismatch",
        "symbol_underlying_mismatch",
        "quote_math_mismatch",
    ],
)
def test_api_corrupt_snapshot_variants_are_http_200_typed_unavailable(
    tmp_path: Path,
    corruption: str,
) -> None:
    run_date = "2026-05-01"
    _write_sample_snapshot(tmp_path, run_date)
    meta_path = tmp_path / f"{run_date}_meta.json"
    bound_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    data_path = tmp_path / bound_meta["data_file"]
    original = data_path.read_bytes()
    if corruption == "truncated_data":
        _bind_api_snapshot_data(tmp_path, run_date, b'{"ticker":')
    elif corruption == "non_object_data":
        _bind_api_snapshot_data(tmp_path, run_date, b"[]\n")
    elif corruption == "truncated_meta":
        meta_path.write_bytes(b"{")
    elif corruption == "invalid_meta_type":
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["universe_size"] = "bad"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    elif corruption == "invalid_provider_type":
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["provider"] = ["futu"]
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    elif corruption == "twenty_one_rows":
        _bind_api_snapshot_data(tmp_path, run_date, original * 21)
    elif corruption == "duplicate_json_key":
        duplicate = original.decode().replace("{", '{"ticker":"QQQ",', 1).encode()
        _bind_api_snapshot_data(tmp_path, run_date, duplicate)
    else:
        payload = json.loads(original)
        if corruption == "ticker_underlying_mismatch":
            payload["candidate"]["underlying"] = "US.QQQ"
        elif corruption == "symbol_underlying_mismatch":
            payload["candidate"]["symbol"] = "US.AAPL260619P450000"
        elif corruption == "invalid_sector_type":
            payload["sector"] = ["ETF"]
        elif corruption == "boolean_iv_rank":
            payload["iv_rank"] = True
            payload["candidate"]["iv_rank"] = True
        else:
            payload["candidate"]["mid"] = 29.0
        _bind_api_snapshot_data(
            tmp_path,
            run_date,
            (json.dumps(payload) + "\n").encode(),
        )
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/options/daily-scan", params={"date": run_date})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["shortfall_reasons"] == {"invalid_recommendation_snapshot": 1}
    assert payload["candidates"] == []


def test_api_options_daily_scan_status_reports_daily_task_file(tmp_path: Path) -> None:
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    missing = client.get("/api/options/daily-scan/status")
    assert missing.status_code == 200
    assert missing.json()["exists"] is False
    assert missing.json()["status"] is None

    status = {
        "status": "completed",
        "run_date": "2026-06-15",
        "provider": "futu",
        "strategies": ["sell_put", "covered_call"],
        "started_at": "2026-06-15T09:00:00+00:00",
        "finished_at": "2026-06-15T09:02:00+00:00",
        "steps": {"scan": {"candidate_count": 12}},
    }
    (tmp_path / "daily_task_status.json").write_text(
        json.dumps(status),
        encoding="utf-8",
    )

    response = client.get("/api/options/daily-scan/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["exists"] is True
    assert payload["status_path"].endswith("daily_task_status.json")
    assert payload["status"] == status


def test_api_options_daily_scan_status_projects_orphaned_active_task_as_interrupted(
    tmp_path: Path,
) -> None:
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    status_path = tmp_path / "daily_task_status.json"
    on_disk = {
        "status": "running",
        "terminal": False,
        "current_step": "scan",
        "target_session": "2026-08-24",
        "run_date": "2026-08-24",
        "trigger": "manual",
        "provider": "futu",
        "strategies": ["sell_put", "covered_call"],
        "queued_at": "2026-08-25T02:00:00Z",
        "started_at": "2026-08-25T02:00:01Z",
        "updated_at": "2026-08-25T02:01:00Z",
        "finished_at": None,
        "scanned_tickers": 4,
        "total_tickers": 34,
        "steps": {},
    }
    status_path.write_text(json.dumps(on_disk), encoding="utf-8")
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/options/daily-scan/status")

    assert response.status_code == 200
    projected = response.json()["status"]
    assert projected["status"] == "failed"
    assert projected["terminal"] is True
    assert projected["current_step"] == "failed"
    assert projected["failed_step"] == "scan"
    assert projected["error"] == "OptionsRadarScanInterrupted: no active scan lock"
    assert json.loads(status_path.read_text(encoding="utf-8")) == on_disk
    assert not (tmp_path / "options_radar_scan.lock").exists()


def test_api_options_daily_scan_status_keeps_active_state_while_lock_is_held(
    tmp_path: Path,
) -> None:
    from quant_system.options.scan_lock import options_radar_scan_lock

    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    status = {
        "status": "queued",
        "terminal": False,
        "current_step": "queued",
        "target_session": "2026-08-24",
    }
    (tmp_path / "daily_task_status.json").write_text(
        json.dumps(status), encoding="utf-8"
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    with options_radar_scan_lock(tmp_path):
        response = client.get("/api/options/daily-scan/status")

    assert response.status_code == 200
    assert response.json()["status"] == status


def test_api_options_status_returns_terminal_update_seen_during_lock_probe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_system.api.routes import options_radar as route

    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    status_path = tmp_path / "daily_task_status.json"
    running = {
        "status": "running",
        "terminal": False,
        "current_step": "scan",
        "target_session": "2026-08-24",
        "updated_at": "2026-08-25T02:01:00Z",
    }
    completed = {
        **running,
        "status": "completed",
        "terminal": True,
        "current_step": "completed",
        "updated_at": "2026-08-25T02:02:00Z",
        "finished_at": "2026-08-25T02:02:00Z",
    }
    status_path.write_text(json.dumps(running), encoding="utf-8")
    (tmp_path / "options_radar_scan.lock").write_bytes(b"\0")

    class CompletingProbe:
        def __enter__(self):
            status_path.write_text(json.dumps(completed), encoding="utf-8")
            return None

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        route,
        "options_radar_scan_lock",
        lambda _output_dir: CompletingProbe(),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/options/daily-scan/status")

    assert response.status_code == 200
    assert response.json()["status"] == completed


def test_api_startup_has_no_options_radar_canonical_writer() -> None:
    from quant_system.api import server as api_server

    assert "startup_catchup_enabled" not in OptionsRadarSettings.model_fields
    assert not hasattr(api_server, "_start_options_radar_startup_catchup")
    assert not hasattr(api_server, "_run_options_radar_startup_catchup")
    assert not hasattr(api_server, "_options_radar_startup_catchup_run_date")
    assert not hasattr(api_server, "_write_options_radar_startup_status")


def test_legacy_startup_catchup_env_cannot_write_or_start_options_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_system.api import server as api_server

    output_dir = tmp_path / "options-scans"
    monkeypatch.setenv("QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED", "true")
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=output_dir,
            provider="futu",
        )
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("API startup must not enter the options writer")

    class NoopThread:
        def join(self, timeout=None) -> None:
            return None

    monkeypatch.setattr(
        api_server,
        "_start_backtest_job_reconciliation",
        lambda _runner: NoopThread(),
    )
    monkeypatch.setattr(api_server.threading, "Thread", forbidden)

    with TestClient(create_app(settings=settings, output_dir=tmp_path)):
        pass

    assert not output_dir.exists()


def test_api_options_daily_scan_run_queues_fixed_canonical_futu_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_system.api.routes import options_radar as route
    from quant_system.options.radar import CURATED_RECOMMENDATION_TICKERS

    curated_path = tmp_path / "curated_wheel.csv"
    curated_path.write_text(
        "ticker,name,sector,exchange,source\n"
        + "".join(
            f"{ticker},{ticker},ETF,US,core_etf\n"
            for ticker in CURATED_RECOMMENDATION_TICKERS
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_run(*, settings, request, **_kwargs):
        captured["settings"] = settings
        captured["request"] = request

    monkeypatch.setattr(route, "run_options_daily_task", fake_run, raising=False)
    monkeypatch.setattr(
        route,
        "resolve_options_market_session",
        lambda: date(2026, 8, 24),
        raising=False,
    )
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=tmp_path,
            curated_universe_path=curated_path,
            risk_free_rate=0.04,
        )
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/options/daily-scan/run",
        json={
            "provider": "sample",
            "top": 1,
            "strategies": ["sell_put"],
            "run_date": "2099-01-03",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert {key: payload[key] for key in (
        "status",
        "terminal",
        "current_step",
        "target_session",
        "trigger",
        "queued_at",
        "started_at",
        "finished_at",
        "scanned_tickers",
        "total_tickers",
    )} == {
        "status": "queued",
        "terminal": False,
        "current_step": "queued",
        "target_session": "2026-08-24",
        "trigger": "manual",
        "queued_at": payload["queued_at"],
        "started_at": None,
        "finished_at": None,
        "scanned_tickers": 0,
        "total_tickers": 34,
    }
    request = captured["request"]
    assert request.provider == "futu"
    assert request.top == 34
    assert request.run_date == "2026-08-24"
    assert request.output_dir == tmp_path
    queued_status = json.loads(
        (tmp_path / "daily_task_status.json").read_text(encoding="utf-8")
    )
    assert queued_status["strategies"] == ["sell_put", "covered_call"]

    dates_response = client.get("/api/options/daily-scan/dates")
    assert dates_response.json()["dates"] == []


def test_product_daily_scan_post_returns_409_when_scan_lock_is_held(
    tmp_path: Path,
) -> None:
    from quant_system.options.scan_lock import options_radar_scan_lock

    output_dir = tmp_path / "canonical"
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=output_dir))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    with options_radar_scan_lock(output_dir):
        response = client.post("/api/options/daily-scan/run")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "options_scan_already_running"
    assert not (output_dir / "daily_task_status.json").exists()


@pytest.mark.parametrize(
    "request_kwargs",
    [
        {},
        {"content": b"{"},
        {"json": []},
        {"json": "not-an-object"},
    ],
)
def test_product_daily_scan_post_does_not_accept_body_as_scan_configuration(
    tmp_path: Path,
    monkeypatch,
    request_kwargs: dict,
) -> None:
    from quant_system.api.routes import options_radar as route

    output_dir = tmp_path / "canonical"
    output_dir.mkdir()
    (output_dir / "existing.jsonl").write_bytes(b"existing\n")
    captured = {}

    def fake_run(*, request, **_kwargs):
        captured["request"] = request

    monkeypatch.setattr(route, "run_options_daily_task", fake_run)
    monkeypatch.setattr(
        route,
        "resolve_options_market_session",
        lambda: date(2026, 8, 24),
    )
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=output_dir))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post("/api/options/daily-scan/run", **request_kwargs)

    assert response.status_code == 202
    assert captured["request"].provider == "futu"
    assert captured["request"].top == 34
    assert captured["request"].run_date == "2026-08-24"
    assert (output_dir / "existing.jsonl").read_bytes() == b"existing\n"


def test_api_options_daily_scan_symbol_returns_snapshot_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_date = "2026-05-01"
    _write_sample_snapshot(tmp_path, run_date)
    monkeypatch.setattr(
        "quant_system.api.routes.options_radar._utc_now",
        lambda: datetime(2026, 5, 1, 21, 0, tzinfo=UTC),
    )
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(
        "/api/options/daily-scan/symbol/SPY",
        params={"date": run_date},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "SPY"
    assert payload["run_date"] == run_date
    assert payload["candidates"]
    assert payload["candidates"][0]["ticker"] == "SPY"
    assert payload["safety"]["live_trading_enabled"] is False


def test_api_options_daily_scan_symbol_surfaces_unavailable_reason_and_provider(
    tmp_path: Path,
) -> None:
    _write_sample_snapshot(tmp_path, "2026-05-01")
    meta_path = tmp_path / "2026-05-01_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["contract_version"] = "options_recommendations/legacy"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(
        "/api/options/daily-scan/symbol/SPY",
        params={"date": "2026-05-01"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "futu"
    assert payload["status"] == "unavailable"
    assert payload["shortfall_reasons"] == {"legacy_snapshot_contract": 1}
    assert payload["universe_size"] == 34
    assert payload["scanned_tickers"] == 34
    assert payload["candidate_count"] == 0
    assert payload["candidates"] == []


def test_api_options_daily_scan_missing_date_returns_404(tmp_path: Path) -> None:
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/options/daily-scan", params={"date": "2026-05-03"})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "no_radar_snapshot"
    assert response.json()["safety"]["dry_run"] is True


def test_api_options_daily_scan_without_any_snapshot_is_typed_unavailable(
    tmp_path: Path,
) -> None:
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/options/daily-scan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["provider"] is None
    assert payload["as_of"] is None
    assert payload["shortfall_count"] == 20
    assert payload["shortfall_reasons"] == {"no_snapshot": 1}
    assert payload["candidates"] == []
    assert payload["safety"]["live_trading_enabled"] is False


def test_api_options_refresh_inputs_reject_sample_without_writes(tmp_path: Path) -> None:
    universe_path = tmp_path / "universe.csv"
    earnings_path = tmp_path / "earnings.csv"
    vix_path = tmp_path / "vix_history.csv"
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=tmp_path / "scans",
            universe_path=universe_path,
            curated_universe_path=universe_path,
            earnings_calendar_path=earnings_path,
            vix_history_path=vix_path,
        )
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    universe_response = client.post(
        "/api/options/refresh/universe",
        json={"source": "sample"},
    )
    earnings_response = client.post(
        "/api/options/refresh/earnings",
        json={"source": "sample", "top": 2, "today": "2099-01-03"},
    )
    vix_response = client.post(
        "/api/options/refresh/vix",
        json={"source": "sample", "lookback_days": 10, "end": "2099-01-10"},
    )

    for response in (universe_response, earnings_response, vix_response):
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "sample_options_input_withdrawn"
        assert response.json()["safety"]["live_trading_enabled"] is False
    assert not universe_path.exists()
    assert not earnings_path.exists()
    assert not vix_path.exists()
