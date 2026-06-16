from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_all_json_200_responses_publish_component_refs(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    non_ref_responses: list[tuple[str, str, dict]] = []
    for path, methods in openapi["paths"].items():
        for method, operation in methods.items():
            response = operation.get("responses", {}).get("200")
            if response is None:
                continue
            schema = response.get("content", {}).get("application/json", {}).get("schema")
            if schema is not None and "$ref" not in schema:
                non_ref_responses.append((method.upper(), path, schema))

    assert non_ref_responses == []


def test_read_only_market_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/health": "HealthResponse",
        "/api/symbols": "SymbolsResponse",
        "/api/ohlcv": "OHLCVResponse",
        "/api/market-data/history": "MarketDataHistoryResponse",
        "/api/benchmark": "BenchmarkResponse",
        "/api/agent/llm-config": "AgentLLMConfigResponse",
        "/api/options/daily-scan/dates": "OptionsDailyScanDatesResponse",
        "/api/options/daily-scan/status": "OptionsDailyScanStatusResponse",
        "/api/options/daily-scan": "OptionsDailyScanResponse",
        "/api/options/daily-scan/symbol/{ticker}": "OptionsDailyScanSymbolResponse",
        "/api/options/expirations": "OptionsExpirationsResponse",
        "/api/options/chain": "OptionsChainResponse",
        "/api/options/snapshot/{ticker}": "OptionsSnapshotResponse",
        "/api/options/tools/vol-surface/{ticker}": "OptionsVolSurfaceResponse",
        "/api/options/tools/vol-smile/{ticker}": "OptionsVolSmileResponse",
        "/api/options/tools/strategy/templates": "OptionsStrategyTemplatesResponse",
        "/api/options/tools/watchlist": "OptionsWatchlistResponse",
        "/api/prediction-market/markets": "PredictionMarketMarketsResponse",
        "/api/prediction-market/results/{run_id}": "PredictionMarketBacktestResultResponse",
        "/api/prediction-market/timeseries-backtest/{run_id}": (
            "PredictionMarketTimeseriesBacktestResultResponse"
        ),
        "/api/backtests": "BacktestsResponse",
        "/api/backtests/{run_id}": "BacktestDetailResponse",
        "/api/paper": "PaperRunsResponse",
        "/api/paper/account": "PaperAccountResponse",
        "/api/paper/account/ledger": "PaperLedgerResponse",
        "/api/agent/candidates": "AgentCandidatesResponse",
        "/api/agent/candidates/{candidate_id}": "AgentCandidateDetailResponse",
        "/api/experiments": "ExperimentsResponse",
        "/api/experiments/{experiment_id}": "ExperimentDetailResponse",
        "/api/factors": "FactorCatalogResponse",
        "/api/factors/lab": "FactorLabResponse",
        "/api/factors/runs": "FactorRunsResponse",
        "/api/factors/{run_id}": "FactorRunDetailResponse",
        "/api/replications/reversal-momentum/{run_id}": "ReversalMomentumReplicationDetailResponse",
        "/api/runs/recent": "RecentRunsResponse",
        "/api/settings": "SettingsResponse",
        "/api/strategies": "StrategyCatalogResponse",
        "/api/universes": "UniverseCatalogResponse",
        "/api/paper/{run_id}": "PaperRunDetailResponse",
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "data_provider" in components["HealthResponse"]["properties"]
    assert "futu_opend" in components["HealthResponse"]["properties"]
    assert "database" in components["HealthResponse"]["properties"]
    assert "metadata" in components["MarketDataHistoryResponse"]["properties"]
    assert "has_api_key" in components["AgentLLMConfigResponse"]["properties"]
    assert "dates" in components["OptionsDailyScanDatesResponse"]["properties"]
    assert "status" in components["OptionsDailyScanStatusResponse"]["properties"]
    assert "candidates" in components["OptionsDailyScanResponse"]["properties"]
    assert "candidate_count" in components["OptionsDailyScanSymbolResponse"]["properties"]
    assert "expirations" in components["OptionsExpirationsResponse"]["properties"]
    assert "contracts" in components["OptionsChainResponse"]["properties"]
    assert "atm_iv" in components["OptionsSnapshotResponse"]["properties"]
    assert "surface" in components["OptionsVolSurfaceResponse"]["properties"]
    assert "smile" in components["OptionsVolSmileResponse"]["properties"]
    assert "templates" in components["OptionsStrategyTemplatesResponse"]["properties"]
    assert "watchlist" in components["OptionsWatchlistResponse"]["properties"]
    assert "markets" in components["PredictionMarketMarketsResponse"]["properties"]
    assert "result" in components["PredictionMarketBacktestResultResponse"]["properties"]
    assert (
        "report_url"
        in components["PredictionMarketTimeseriesBacktestResultResponse"]["properties"]
    )
    assert "backtests" in components["BacktestsResponse"]["properties"]
    assert "BacktestRunTimingsResponse" in components
    assert "data_fetch" in components["BacktestRunTimingsResponse"]["properties"]
    assert "timings_ms" in components["BacktestRunResponse"]["properties"]
    assert "benchmark" in components["BacktestDetailResponse"]["properties"]
    assert "paper_runs" in components["PaperRunsResponse"]["properties"]
    assert "positions" in components["PaperAccountResponse"]["properties"]
    assert "reserved_cash" in components["PaperAccountResponse"]["properties"]
    assert "available_cash" in components["PaperAccountResponse"]["properties"]
    assert "reserved_quantity" in components["PendingAccountOrderResponse"]["properties"]
    assert "entries" in components["PaperLedgerResponse"]["properties"]
    assert "candidates" in components["AgentCandidatesResponse"]["properties"]
    assert "source_preview" in components["AgentCandidateDetailResponse"]["properties"]
    assert "experiments" in components["ExperimentsResponse"]["properties"]
    assert "runs" in components["ExperimentDetailResponse"]["properties"]
    assert "folds" in components["ExperimentDetailResponse"]["properties"]
    assert "source" in components["OHLCVResponse"]["properties"]
    assert "source" in components["BenchmarkResponse"]["properties"]
    assert "factors" in components["FactorCatalogResponse"]["properties"]
    assert "cross_sectional" in components["FactorLabResponse"]["properties"]
    assert "timing" in components["FactorLabResponse"]["properties"]
    assert "FactorLabGuardrailsResponse" in components
    assert "walk_forward" in components["FactorLabGuardrailsResponse"]["properties"]
    assert "FactorLabCacheResponse" in components
    assert "key" in components["FactorLabCacheResponse"]["properties"]
    assert "runs" in components["FactorRunsResponse"]["properties"]
    assert "information_coefficients" in components["FactorRunDetailResponse"]["properties"]
    assert "quantile_returns" in components["FactorRunDetailResponse"]["properties"]
    assert "result" in components["ReversalMomentumReplicationDetailResponse"]["properties"]
    assert "risk_breaches" in components["PaperRunDetailResponse"]["properties"]
    assert "runs" in components["RecentRunsResponse"]["properties"]
    assert components["SettingsResponse"]["type"] == "object"
    assert "strategies" in components["StrategyCatalogResponse"]["properties"]
    assert "universes" in components["UniverseCatalogResponse"]["properties"]

    artifact_response = openapi["paths"][
        "/api/prediction-market/timeseries-backtest/{run_id}/artifacts/{artifact_name}"
    ]["get"]["responses"]["200"]
    assert "application/json" not in artifact_response.get("content", {})


def test_prediction_market_post_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/prediction-market/scan": "PredictionMarketScanResponse",
        "/api/prediction-market/collect": "PredictionMarketCollectResponse",
        "/api/prediction-market/dry-arbitrage": "PredictionMarketDryArbitrageResponse",
        "/api/prediction-market/backtest": "PredictionMarketBacktestRunResponse",
        "/api/prediction-market/timeseries-backtest": (
            "PredictionMarketTimeseriesBacktestRunResponse"
        ),
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "candidate_id" in components["PredictionMarketCandidateResponse"]["properties"]
    assert "candidates" in components["PredictionMarketScanResponse"]["properties"]
    assert "iteration_count" in components["PredictionMarketCollectResponse"]["properties"]
    assert "proposed_trades" in components[
        "PredictionMarketDryArbitrageResponse"
    ]["properties"]
    assert "metrics" in components["PredictionMarketBacktestRunResponse"]["properties"]
    assert "history_dir" in components[
        "PredictionMarketTimeseriesBacktestRunResponse"
    ]["properties"]


def test_agent_post_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/agent/tasks": "AgentTaskResponse",
        "/api/agent/candidates/{candidate_id}/review": "AgentReviewResponse",
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "metadata" in components["AgentTaskResponse"]["properties"]
    assert "registration" in components["AgentReviewResponse"]["properties"]


def test_options_radar_post_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/options/refresh/universe": "OptionsRefreshResponse",
        "/api/options/refresh/earnings": "OptionsRefreshResponse",
        "/api/options/refresh/vix": "OptionsRefreshResponse",
        "/api/options/daily-scan/run": "OptionsDailyScanRunResponse",
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "row_count" in components["OptionsRefreshResponse"]["properties"]
    assert "output_path" in components["OptionsRefreshResponse"]["properties"]
    assert "candidate_count" in components["OptionsDailyScanRunResponse"]["properties"]
    assert "data_path" in components["OptionsDailyScanRunResponse"]["properties"]


def test_options_screener_post_route_publishes_response_model(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    response_schema = openapi["paths"]["/api/options/screener"]["post"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/OptionsScreenerResult"}

    components = openapi["components"]["schemas"]
    assert "candidates" in components["OptionsScreenerResult"]["properties"]
    assert "assumptions" in components["OptionsScreenerResult"]["properties"]
    assert "rating" in components["OptionsScreenerCandidate"]["properties"]


def test_options_local_tools_post_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/options/tools/greeks": "OptionsGreeksResponse",
        "/api/options/tools/implied-volatility": "OptionsImpliedVolatilityResponse",
        "/api/options/tools/simulate": "OptionsSimulationResponse",
        "/api/options/tools/strategy/build": "OptionsStrategyBuildResponse",
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "delta" in components["OptionsGreeksResponse"]["properties"]
    assert "charm" in components["OptionsGreeksResponse"]["properties"]
    assert (
        "implied_volatility"
        in components["OptionsImpliedVolatilityResponse"]["properties"]
    )
    assert "pnl_at_expiry" in components["OptionsSimulationResponse"]["properties"]
    assert "scenarios" in components["OptionsSimulationResponse"]["properties"]
    assert "template_id" in components["OptionsStrategyBuildResponse"]["properties"]
    assert "legs" in components["OptionsStrategyBuildResponse"]["properties"]


def test_options_local_research_post_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/options/tools/score-contracts": "OptionsContractScoreResponse",
        "/api/options/tools/strategy/rank": "OptionsStrategyRankResponse",
        "/api/options/tools/bull-put-signal": "OptionsBullPutSignalResponse",
        "/api/options/tools/fear-score": "OptionsFearScoreResponse",
        "/api/options/tools/iv-rank": "OptionsIvRankResponse",
        "/api/options/tools/market-sentiment": "OptionsMarketSentimentResponse",
        "/api/options/tools/earnings-crush": "OptionsEarningsCrushResponse",
        "/api/options/tools/hedge-advisor": "OptionsHedgeAdvisorResponse",
        "/api/options/tools/unusual-activity": "OptionsUnusualActivityResponse",
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "ranked_contracts" in components["OptionsContractScoreResponse"]["properties"]
    assert "rankings" in components["OptionsStrategyRankResponse"]["properties"]
    assert "selected_spread" in components["OptionsBullPutSignalResponse"]["properties"]
    assert "fear_score" in components["OptionsFearScoreResponse"]["properties"]
    assert "iv_percentile" in components["OptionsIvRankResponse"]["properties"]
    assert "sentiment_score" in components["OptionsMarketSentimentResponse"]["properties"]
    assert "average_crush_pct" in components["OptionsEarningsCrushResponse"]["properties"]
    assert "structures" in components["OptionsHedgeAdvisorResponse"]["properties"]
    assert "events" in components["OptionsUnusualActivityResponse"]["properties"]


def test_options_monitoring_post_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/options/tools/watchlist": "OptionsWatchlistResponse",
        "/api/options/tools/alerts/evaluate": "OptionsAlertsEvaluationResponse",
        "/api/options/tools/health-check": "OptionsResearchHealthCheckResponse",
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "watchlist" in components["OptionsWatchlistResponse"]["properties"]
    assert (
        "triggered_alerts"
        in components["OptionsAlertsEvaluationResponse"]["properties"]
    )
    assert "health_score" in components["OptionsResearchHealthCheckResponse"]["properties"]
    assert "missing_thesis" in components["OptionsResearchHealthCheckResponse"]["properties"]


def test_research_run_post_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/factors/run": "FactorRunResponse",
        "/api/backtests/run": "BacktestRunResponse",
        "/api/experiments/run": "ExperimentRunResponse",
        "/api/replications/reversal-momentum/run": (
            "ReversalMomentumReplicationRunResponse"
        ),
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "signal_count" in components["FactorRunResponse"]["properties"]
    assert "trade_count" in components["BacktestRunResponse"]["properties"]
    assert "best_run_id" in components["ExperimentRunResponse"]["properties"]
    assert (
        "monthly_returns"
        in components["ReversalMomentumReplicationRunResponse"]["properties"]
    )
    assert "artifact_path" in components[
        "ReversalMomentumReplicationRunResponse"
    ]["properties"]


def test_paper_post_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/paper/run": "PaperRunResponse",
        "/api/paper/account/reset": "PaperAccountResponse",
        "/api/paper/account/kill-switch": "PaperAccountResponse",
        "/api/paper/account/orders": "PaperAccountOrderResponse",
        "/api/paper/account/orders/process": "PaperAccountOrdersProcessResponse",
        "/api/paper/account/orders/{order_id}/cancel": "PaperAccountOrderResponse",
        "/api/paper/account/rebalance": "PaperAccountRebalanceResponse",
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "execution_status" in components["PaperRunResponse"]["properties"]
    assert "order" in components["PaperAccountOrderResponse"]["properties"]
    assert "orders" in components["PaperAccountOrdersProcessResponse"]["properties"]
    assert "rebalance" in components["PaperAccountRebalanceResponse"]["properties"]
