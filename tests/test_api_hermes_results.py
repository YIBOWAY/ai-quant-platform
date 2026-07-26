from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from quant_system.agent.candidate_pool import CandidatePool
from quant_system.api.server import create_app
from quant_system.config.settings import (
    DatabaseSettings,
    HermesArtifactSettings,
    Settings,
)
from quant_system.hermes.command_ledger import (
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
    HermesRunLink,
    HermesRunLinkPage,
    hermes_run_link_digest,
)
from quant_system.hermes.results_catalog import (
    HermesResultsCatalog,
    HermesResultSourceBudgetExceeded,
    _JsonReadBudget,
    _utc_timestamp,
    _validate_parquet_metadata,
)


def _client(
    tmp_path: Path,
    *,
    output_dir: Path | None = None,
    agent_output_dir: Path | None = None,
    settings: Settings | None = None,
) -> TestClient:
    isolated_settings = settings or Settings(
        hermes_artifacts=HermesArtifactSettings(feed_path=tmp_path / "missing-hqa-feed.json")
    )
    return TestClient(
        create_app(
            settings=isolated_settings,
            output_dir=output_dir or tmp_path,
            agent_output_dir=agent_output_dir or tmp_path / "empty-agent-output",
        )
    )


def _write_run(
    api_runs: Path,
    dirname: str,
    run_id: str,
    *,
    kind: str,
    status: str = "completed",
    created_at: str = "2026-07-15T01:00:00+00:00",
    request: dict | None = None,
) -> None:
    run_dir = api_runs / dirname / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "kind": kind,
                "status": status,
                "created_at": created_at,
                "source": "sample",
                "metrics": {"sharpe": 1.2},
                "request": request or {},
            }
        ),
        encoding="utf-8",
    )
    if kind == "backtest":
        artifact_dir = run_dir / "backtests"
        artifact_dir.mkdir()
        (artifact_dir / "metrics.json").write_text("{}", encoding="utf-8")
    elif kind == "factor":
        artifact_dir = run_dir / "factors"
        artifact_dir.mkdir()
        pq.write_table(
            pa.table({"placeholder": pa.array([], type=pa.int8())}),
            artifact_dir / "factor_results.parquet",
        )
    elif kind == "paper":
        artifact_dir = run_dir / "paper"
        artifact_dir.mkdir()
        pq.write_table(
            pa.table({"placeholder": pa.array([], type=pa.int8())}),
            artifact_dir / "orders.parquet",
        )
    elif kind == "replication":
        (run_dir / "result.json").write_text(
            json.dumps({"run_id": run_id, "metrics": {}}),
            encoding="utf-8",
        )


def test_hermes_results_lists_run_references_without_copying_detail(tmp_path) -> None:
    api_runs = tmp_path / "api_runs"
    _write_run(
        api_runs,
        "backtests",
        "backtest-20260715T010000Z-aaaaaaaa",
        kind="backtest",
        request={
            "strategy_id": "cross_sectional_top_n",
            "symbols": ["SPY", "QQQ"],
            "start": "2026-01-02",
            "end": "2026-06-30",
            "provider": "sample",
        },
    )

    client = _client(tmp_path)
    response = client.get("/api/hermes/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["total"] == 1
    assert payload["limit"] == 20
    assert payload["offset"] == 0
    assert payload["has_more"] is False
    assert payload["items"] == [
        {
            "kind": "backtest",
            "resource_id": "backtest-20260715T010000Z-aaaaaaaa",
            "display_title": "cross_sectional_top_n · SPY, QQQ",
            "summary": "2026-01-02 → 2026-06-30 · provider sample",
            "status": "completed",
            "occurred_at": "2026-07-15T01:00:00Z",
            "source": "platform_runs",
            "authority": "platform_run_artifact",
            "freshness": "not_applicable",
            "read_status": "available",
            "detail_href": ("/api/hermes/results/backtest/backtest-20260715T010000Z-aaaaaaaa"),
            "original_href": ("/api/backtests/backtest-20260715T010000Z-aaaaaaaa"),
            "run_links": None,
        }
    ]
    assert "metrics" not in payload["items"][0]


def test_hermes_results_searches_bounded_human_projection(tmp_path) -> None:
    api_runs = tmp_path / "api_runs"
    _write_run(
        api_runs,
        "backtests",
        "backtest-20260715T010000Z-a11a11a1",
        kind="backtest",
        request={
            "strategy_id": "momentum_rotation",
            "symbols": ["AAPL", "MSFT", "NVDA", "AMD"],
            "start": "2026-01-01",
            "end": "2026-07-01",
            "provider": "futu",
        },
    )

    response = _client(tmp_path).get("/api/hermes/results", params={"search": "MOMENTUM_ROTATION"})

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["display_title"] == "momentum_rotation · AAPL, MSFT, NVDA +1"
    assert item["summary"] == "2026-01-01 → 2026-07-01 · provider futu"


def test_hermes_results_bounds_projection_fields_without_losing_evidence(
    tmp_path,
) -> None:
    api_runs = tmp_path / "api_runs"
    _write_run(
        api_runs,
        "backtests",
        "backtest-20260715T010000Z-b22b22b2",
        kind="backtest",
        request={
            "strategy_id": "x" * 5_000,
            "symbols": ["SPY"],
            "provider": "y" * 5_000,
        },
    )

    response = _client(tmp_path).get("/api/hermes/results")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert len(item["display_title"]) <= 256
    assert item["summary"] is None or len(item["summary"]) <= 1_000


def test_hermes_results_covers_every_authoritative_run_kind(tmp_path) -> None:
    api_runs = tmp_path / "api_runs"
    fixtures = {
        "backtest": ("backtests", "backtest-20260715T010000Z-a0000001"),
        "factor": ("factors", "factor-20260715T020000Z-a0000002"),
        "paper": ("paper", "paper-20260715T030000Z-a0000003"),
        "replication": (
            "replications",
            "replication-20260715T040000Z-a0000004",
        ),
    }
    for hour, (kind, (dirname, run_id)) in enumerate(fixtures.items(), start=1):
        _write_run(
            api_runs,
            dirname,
            run_id,
            kind=kind,
            created_at=f"2026-07-15T{hour:02d}:00:00+00:00",
        )
    client = _client(tmp_path)

    response = client.get("/api/hermes/results", params={"source": "platform_runs"})

    assert response.status_code == 200
    by_kind = {item["kind"]: item for item in response.json()["items"]}
    assert set(by_kind) == set(fixtures)
    assert by_kind["backtest"]["original_href"].startswith("/api/backtests/")
    assert by_kind["factor"]["original_href"].startswith("/api/factors/")
    assert by_kind["paper"]["original_href"].startswith("/api/paper/")
    assert by_kind["replication"]["original_href"].startswith(
        "/api/replications/reversal-momentum/"
    )


def test_hermes_result_detail_rereads_the_authoritative_run(tmp_path) -> None:
    run_id = "factor-20260715T020000Z-bbbbbbbb"
    api_runs = tmp_path / "api_runs"
    _write_run(api_runs, "factors", run_id, kind="factor")
    client = _client(tmp_path)

    first = client.get(f"/api/hermes/results/factor/{run_id}")
    assert first.status_code == 200
    assert first.json()["resource"]["metadata"]["metrics"] == {"sharpe": 1.2}

    metadata_path = api_runs / "factors" / run_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["metrics"] = {"sharpe": 2.4}
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    second = client.get(f"/api/hermes/results/factor/{run_id}")
    assert second.status_code == 200
    payload = second.json()
    assert payload["read_status"] == "degraded"
    assert payload["item"]["read_status"] == "available"
    assert payload["item"]["resource_id"] == run_id
    assert payload["resource"]["metadata"]["metrics"] == {"sharpe": 2.4}
    assert payload["resource"]["detail_mode"] == "bounded_manifest"
    assert {entry["path"] for entry in payload["resource"]["artifacts"]} == {
        "metadata.json",
        "factors/factor_results.parquet",
    }
    assert payload["warnings"] == [
        {
            "source": "platform_run_links",
            "code": "exact_links_not_configured",
            "kind": None,
            "resource_id": None,
        }
    ]


def test_hermes_results_keeps_valid_runs_visible_when_one_run_is_corrupt(
    tmp_path,
) -> None:
    api_runs = tmp_path / "api_runs"
    _write_run(
        api_runs,
        "factors",
        "factor-20260715T020000Z-bbbbbbbb",
        kind="factor",
    )
    broken_id = "backtest-20260715T030000Z-cccccccc"
    broken_dir = api_runs / "backtests" / broken_id
    broken_dir.mkdir(parents=True)
    (broken_dir / "metadata.json").write_text("{not-json", encoding="utf-8")

    client = _client(tmp_path)
    response = client.get("/api/hermes/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["total"] == 2
    by_id = {item["resource_id"]: item for item in payload["items"]}
    assert by_id[broken_id]["read_status"] == "corrupt"
    assert by_id[broken_id]["freshness"] == "unknown"
    assert by_id["factor-20260715T020000Z-bbbbbbbb"]["read_status"] == "available"
    sources = {source["source"]: source for source in payload["sources"]}
    assert sources["platform_runs"] == {
        "source": "platform_runs",
        "read_status": "degraded",
        "item_count": 2,
    }
    assert sources["platform_experiments"]["read_status"] == "empty"
    assert {
        "source": "platform_runs",
        "code": "result_corrupt",
        "kind": "backtest",
        "resource_id": broken_id,
    } in payload["warnings"]


def test_hermes_results_has_bounded_pagination_and_exact_filters(tmp_path) -> None:
    api_runs = tmp_path / "api_runs"
    for hour, suffix, status in ((1, "aaaaaaaa", "completed"), (2, "bbbbbbbb", "failed")):
        _write_run(
            api_runs,
            "backtests",
            f"backtest-20260715T{hour:02d}0000Z-{suffix}",
            kind="backtest",
            status=status,
            created_at=f"2026-07-15T{hour:02d}:00:00+00:00",
        )
    _write_run(
        api_runs,
        "factors",
        "factor-20260715T030000Z-cccccccc",
        kind="factor",
        created_at="2026-07-15T03:00:00+00:00",
    )
    client = _client(tmp_path)

    page = client.get(
        "/api/hermes/results",
        params={
            "kind": "backtest",
            "source": "platform_runs",
            "search": "BACKTEST-20260715",
            "limit": 1,
            "offset": 1,
        },
    )
    assert page.status_code == 200
    payload = page.json()
    assert payload["total"] == 2
    assert payload["has_more"] is False
    assert payload["items"][0]["resource_id"].endswith("aaaaaaaa")

    failed = client.get("/api/hermes/results", params={"status": "FAILED"})
    assert failed.status_code == 200
    assert [item["status"] for item in failed.json()["items"]] == ["failed"]

    assert client.get("/api/hermes/results?limit=101").status_code == 422
    assert client.get("/api/hermes/results?offset=10001").status_code == 422


def test_hermes_results_includes_experiments_and_rereads_experiment_detail(
    tmp_path,
) -> None:
    experiment_id = "experiment-20260715T040000Z-dddddddd"
    experiment_dir = tmp_path / "experiments" / experiment_id
    experiment_dir.mkdir(parents=True)
    (experiment_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": experiment_id,
                "kind": "experiment",
                "status": "completed",
                "created_at": "2026-07-15T04:00:00+00:00",
                "source": "sample",
            }
        ),
        encoding="utf-8",
    )
    summary_path = experiment_dir / "agent_summary.json"
    summary_path.write_text(
        json.dumps({"best_run_id": "run-001"}),
        encoding="utf-8",
    )
    (experiment_dir / "experiment_config.json").write_text(
        json.dumps({"experiment_name": "first"}),
        encoding="utf-8",
    )
    client = _client(tmp_path)

    listing = client.get("/api/hermes/results", params={"source": "platform_experiments"})
    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["kind"] == "experiment"
    assert item["resource_id"] == experiment_id
    assert item["authority"] == "platform_experiment_artifact"
    assert item["original_href"] == f"/api/experiments/{experiment_id}"

    (experiment_dir / "experiment_config.json").write_text(
        json.dumps({"experiment_name": "second"}),
        encoding="utf-8",
    )
    detail = client.get(f"/api/hermes/results/experiment/{experiment_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["read_status"] == "degraded"
    assert payload["item"]["read_status"] == "available"
    assert (
        payload["resource"]["reference_json"]["experiment_config.json"]["experiment_name"]
        == "second"
    )


def test_hermes_results_includes_verified_candidates_and_validated_detail(
    tmp_path,
) -> None:
    agent_output_dir = tmp_path / "agent-output"
    artifact = CandidatePool(agent_output_dir).write_candidate(
        task_id="task-wave3e",
        goal="bounded momentum factor",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="class ProposedFactor:\n    pass\n",
        universe=["SPY", "QQQ"],
    )
    client = _client(
        tmp_path,
        output_dir=tmp_path / "platform",
        agent_output_dir=agent_output_dir,
    )

    listing = client.get("/api/hermes/results", params={"source": "platform_candidates"})
    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["kind"] == "factor_candidate"
    assert item["resource_id"] == artifact.candidate_id
    assert item["status"] == "pending"
    assert item["authority"] == "platform_candidate_repository"
    assert item["freshness"] == "not_applicable"
    assert item["original_href"] == f"/api/agent/candidates/{artifact.candidate_id}"

    detail = client.get(f"/api/hermes/results/factor_candidate/{artifact.candidate_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["read_status"] == "degraded"
    assert payload["item"]["read_status"] == "available"
    assert payload["resource"]["metadata"]["goal"] == "bounded momentum factor"
    assert payload["resource"]["manifest_digest"] == artifact.manifest_digest


def test_hermes_results_includes_hqa_artifacts_and_rereads_validated_feed(
    tmp_path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    artifact_id = "portfolio-risk:9b32027c89f395f39cba368a"
    feed_path = tmp_path / "hqa" / "manifest.v1.json"
    feed_path.parent.mkdir(parents=True)
    manifest = {
        "schema_version": "1.0",
        "read_status": "available",
        "as_of": now,
        "items": [
            {
                "id": artifact_id,
                "kind": "portfolio_risk",
                "occurred_at": now,
                "quality": "available",
                "status": "available",
                "data": {
                    "account_id": "default",
                    "currency": "USD",
                    "gross_value": 100.0,
                    "gross_pct_equity": 0.1,
                    "largest_symbol": "AAPL",
                    "top1_gross_pct": 1.0,
                    "historical_status": "available",
                    "benchmark": "SPY",
                    "betas": [],
                    "reason_codes": [],
                    "limitations": [],
                },
            }
        ],
        "sources": [
            {
                "kind": "portfolio_risk",
                "status": "available",
                "latest_at": now,
                "reason_code": None,
            },
            {
                "kind": "prediction",
                "status": "empty",
                "latest_at": None,
                "reason_code": None,
            },
            {
                "kind": "market_foresight",
                "status": "empty",
                "latest_at": None,
                "reason_code": None,
            },
        ],
        "warnings": [],
    }
    feed_path.write_text(json.dumps(manifest), encoding="utf-8")
    settings = Settings(
        hermes_artifacts=HermesArtifactSettings(
            feed_path=feed_path,
            freshness_budget_seconds=3600,
        )
    )
    client = _client(
        tmp_path,
        settings=settings,
        output_dir=tmp_path / "platform",
    )

    listing = client.get("/api/hermes/results", params={"source": "hqa_artifact_feed"})
    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["kind"] == "portfolio_risk"
    assert item["resource_id"] == artifact_id
    assert item["freshness"] == "fresh"
    assert item["authority"] == "hqa_artifact_manifest"
    assert item["original_href"] == "/api/hermes/artifacts"

    manifest["items"][0]["status"] = "reviewed"
    feed_path.write_text(json.dumps(manifest), encoding="utf-8")
    detail = client.get(f"/api/hermes/results/portfolio_risk/{artifact_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["read_status"] == "degraded"
    assert payload["item"]["read_status"] == "available"
    assert payload["resource"]["status"] == "reviewed"
    assert payload["resource"]["data"]["gross_value"] == 100.0

    old = (
        (datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2))
        .isoformat()
        .replace("+00:00", "Z")
    )
    manifest["as_of"] = old
    manifest["items"][0]["occurred_at"] = old
    manifest["sources"][0]["latest_at"] = old
    feed_path.write_text(json.dumps(manifest), encoding="utf-8")
    stale = client.get("/api/hermes/results", params={"source": "hqa_artifact_feed"}).json()
    assert stale["read_status"] == "degraded"
    assert stale["items"][0]["freshness"] == "stale"
    assert "feed_stale" in {warning["code"] for warning in stale["warnings"]}


def test_hqa_list_reports_truncation_without_hiding_exact_detail(
    tmp_path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    now_text = now.isoformat().replace("+00:00", "Z")
    newest_id = "portfolio-risk:0000"
    older_id = "portfolio-risk:1000"
    risk_data = {
        "account_id": "default",
        "currency": "USD",
        "gross_value": 100.0,
        "gross_pct_equity": 0.1,
        "largest_symbol": "AAPL",
        "top1_gross_pct": 1.0,
        "historical_status": "available",
        "benchmark": "SPY",
        "betas": [],
        "reason_codes": [],
        "limitations": [],
    }
    feed_path = tmp_path / "hqa" / "manifest.v1.json"
    feed_path.parent.mkdir(parents=True)
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now_text,
                "items": [
                    {
                        "id": f"portfolio-risk:{index:04d}",
                        "kind": "portfolio_risk",
                        "occurred_at": (now - timedelta(seconds=index))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "quality": "available",
                        "status": "available",
                        "data": risk_data,
                    }
                    for index in range(1001)
                ],
                "sources": [
                    {
                        "kind": "portfolio_risk",
                        "status": "available",
                        "latest_at": now_text,
                        "reason_code": None,
                    },
                    {
                        "kind": "prediction",
                        "status": "empty",
                        "latest_at": None,
                        "reason_code": None,
                    },
                    {
                        "kind": "market_foresight",
                        "status": "empty",
                        "latest_at": None,
                        "reason_code": None,
                    },
                ],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = _client(
        tmp_path,
        settings=Settings(
            hermes_artifacts=HermesArtifactSettings(
                feed_path=feed_path,
                freshness_budget_seconds=3600,
            )
        ),
    )

    listing = client.get(
        "/api/hermes/results",
        params={"source": "hqa_artifact_feed", "limit": 1},
    )

    assert listing.status_code == 200
    payload = listing.json()
    assert [item["resource_id"] for item in payload["items"]] == [newest_id]
    assert payload["read_status"] == "degraded"
    assert payload["total"] is None
    assert payload["total_is_exact"] is False
    assert {
        "source": "hqa_artifact_feed",
        "code": "source_scan_limit_exceeded",
        "kind": None,
        "resource_id": None,
    } in payload["warnings"]

    detail = client.get(f"/api/hermes/results/portfolio_risk/{older_id}")

    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["read_status"] == "degraded"
    assert detail_payload["item"]["read_status"] == "available"
    assert detail_payload["item"]["resource_id"] == older_id
    assert detail_payload["resource"]["id"] == older_id


def test_hermes_results_exposes_only_exact_ledger_run_links(
    tmp_path,
    monkeypatch,
) -> None:
    experiment_id = "experiment-20260715T050000Z-eeeeeeee"
    experiment_dir = tmp_path / "experiments" / experiment_id
    experiment_dir.mkdir(parents=True)
    (experiment_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": experiment_id,
                "kind": "experiment",
                "status": "completed",
                "created_at": "2026-07-15T05:00:00+00:00",
                "title": "AAPL momentum",
                "ticker": "AAPL",
            }
        ),
        encoding="utf-8",
    )
    observed_at = datetime(2026, 7, 15, 5, 1, tzinfo=UTC)
    command_id = UUID("00000000-0000-0000-0000-000000000011")
    link = HermesRunLink(
        link_id=UUID("00000000-0000-0000-0000-000000000010"),
        command_id=command_id,
        platform_resource_type="experiment",
        platform_resource_id=experiment_id,
        relation="output",
        hermes_session_id="hermes-session-exact",
        resolved_hermes_session_id="hermes-session-exact-tip",
        hermes_run_id="hermes-run-exact",
        link_digest=hermes_run_link_digest(
            command_id=command_id,
            platform_resource_type="experiment",
            platform_resource_id=experiment_id,
            relation="output",
            hermes_session_id="hermes-session-exact",
            resolved_hermes_session_id="hermes-session-exact-tip",
            hermes_run_id="hermes-run-exact",
            source_event_id="event-exact-001",
        ),
        source_event_id="event-exact-001",
        observed_at=observed_at,
        created_at=observed_at,
    )
    calls: list[tuple[str, str]] = []

    def fake_links(
        _self,
        *,
        resources: tuple[tuple[str, str], ...],
        limit_per_resource: int = 100,
    ) -> dict[tuple[str, str], HermesRunLinkPage]:
        assert limit_per_resource in {3, 100}
        calls.extend(resources)
        return {
            resource: HermesRunLinkPage(
                links=(link,) if resource == ("experiment", experiment_id) else (),
                has_more=False,
            )
            for resource in resources
        }

    monkeypatch.setattr(HermesCommandLedger, "list_run_links_for_resources", fake_links)
    settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url="postgresql://unused:unused@127.0.0.1:1/unused",
        ),
        hermes_artifacts=HermesArtifactSettings(feed_path=tmp_path / "missing-hqa-feed.json"),
    )
    client = _client(tmp_path, settings=settings)

    response = client.get(
        "/api/hermes/results",
        params={"source": "platform_experiments"},
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert calls == [("experiment", experiment_id)]
    assert item["run_links"] == [
        {
                "command_id": "00000000-0000-0000-0000-000000000011",
                "relation": "output",
                "hermes_session_id": "hermes-session-exact",
                "resolved_hermes_session_id": "hermes-session-exact-tip",
                "hermes_run_id": "hermes-run-exact",
            "link_digest": link.link_digest,
            "source_event_id": "event-exact-001",
            "observed_at": "2026-07-15T05:01:00Z",
        }
    ]

    calls.clear()
    detail = client.get(f"/api/hermes/results/experiment/{experiment_id}")
    assert detail.status_code == 200
    assert calls == [("experiment", experiment_id)]
    assert detail.json()["item"]["run_links"] == item["run_links"]


def test_hermes_result_routes_reject_unsafe_ids_and_have_no_mutation_surface(
    tmp_path,
) -> None:
    client = _client(tmp_path)

    assert client.get("/api/hermes/results/factor/bad$id").status_code == 422
    assert client.get("/api/hermes/results/not_a_kind/safe-id").status_code == 422
    assert client.post("/api/hermes/results", json={}).status_code == 405


def test_hermes_results_does_not_publish_an_unsafe_filesystem_resource_id(
    tmp_path,
) -> None:
    unsafe_id = "factor-bad$id"
    _write_run(
        tmp_path / "api_runs",
        "factors",
        unsafe_id,
        kind="factor",
    )
    client = _client(tmp_path)

    response = client.get("/api/hermes/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["total"] is None
    assert payload["total_is_exact"] is False
    assert {
        "source": "platform_runs",
        "code": "invalid_resource_id",
        "kind": "factor",
        "resource_id": unsafe_id,
    } in payload["warnings"]


def test_hermes_results_isolates_an_unavailable_hqa_feed_from_platform_runs(
    tmp_path,
) -> None:
    run_id = "factor-20260715T060000Z-ffffffff"
    _write_run(tmp_path / "api_runs", "factors", run_id, kind="factor")
    feed_path = tmp_path / "corrupt-hqa-feed.json"
    feed_path.write_text("{not-json", encoding="utf-8")
    settings = Settings(hermes_artifacts=HermesArtifactSettings(feed_path=feed_path))
    client = _client(tmp_path, settings=settings)

    response = client.get("/api/hermes/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert [item["resource_id"] for item in payload["items"]] == [run_id]
    sources = {source["source"]: source for source in payload["sources"]}
    assert sources["platform_runs"]["read_status"] == "available"
    assert sources["hqa_artifact_feed"]["read_status"] == "unavailable"
    assert {
        "source": "hqa_artifact_feed",
        "code": "feed_corrupt",
        "kind": None,
        "resource_id": None,
    } in payload["warnings"]


def test_hermes_results_keeps_results_when_exact_link_authority_is_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    run_id = "factor-20260715T070000Z-11111111"
    _write_run(tmp_path / "api_runs", "factors", run_id, kind="factor")

    def unavailable_links(_self, **_kwargs):
        raise HermesCommandLedgerUnavailable("database unavailable")

    monkeypatch.setattr(
        HermesCommandLedger,
        "list_run_links_for_resources",
        unavailable_links,
    )
    settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url="postgresql://unused:unused@127.0.0.1:1/unused",
        ),
        hermes_artifacts=HermesArtifactSettings(feed_path=tmp_path / "missing-hqa-feed.json"),
    )
    client = _client(tmp_path, settings=settings)

    response = client.get("/api/hermes/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["items"][0]["resource_id"] == run_id
    assert payload["items"][0]["run_links"] is None
    link_source = next(
        source for source in payload["sources"] if source["source"] == "platform_run_links"
    )
    assert link_source["read_status"] == "unavailable"
    assert payload["warnings"][-1] == {
        "source": "platform_run_links",
        "code": "exact_links_unavailable",
        "kind": "factor",
        "resource_id": run_id,
    }


def test_hermes_result_detail_distinguishes_missing_and_corrupt(tmp_path) -> None:
    corrupt_id = "factor-20260715T080000Z-22222222"
    corrupt_dir = tmp_path / "api_runs" / "factors" / corrupt_id
    corrupt_dir.mkdir(parents=True)
    (corrupt_dir / "metadata.json").write_text("{not-json", encoding="utf-8")
    client = _client(tmp_path)

    missing = client.get("/api/hermes/results/factor/factor-20260715T090000Z-33333333")
    corrupt = client.get(f"/api/hermes/results/factor/{corrupt_id}")

    assert missing.status_code == 200
    assert missing.json()["read_status"] == "missing"
    assert missing.json()["resource"] is None
    assert missing.json()["warnings"][0]["code"] == "result_not_found"
    assert corrupt.status_code == 200
    assert corrupt.json()["read_status"] == "corrupt"
    assert corrupt.json()["resource"] is None
    assert corrupt.json()["warnings"][0]["code"] == "result_corrupt"


def test_hermes_results_rejects_a_mismatched_exact_link_row(
    tmp_path,
    monkeypatch,
) -> None:
    run_id = "factor-20260715T100000Z-44444444"
    _write_run(tmp_path / "api_runs", "factors", run_id, kind="factor")
    observed_at = datetime(2026, 7, 15, 10, 1, tzinfo=UTC)
    mismatched = HermesRunLink(
        link_id=UUID("00000000-0000-0000-0000-000000000020"),
        command_id=UUID("00000000-0000-0000-0000-000000000021"),
        platform_resource_type="factor",
        platform_resource_id="different-factor-id",
        relation="output",
        hermes_session_id="hermes-session-mismatch",
        hermes_run_id="hermes-run-mismatch",
        link_digest="b" * 64,
        source_event_id="event-mismatch-001",
        observed_at=observed_at,
        created_at=observed_at,
    )
    monkeypatch.setattr(
        HermesCommandLedger,
        "list_run_links_for_resources",
        lambda _self, *, resources, **_kwargs: {
            resource: HermesRunLinkPage(links=(mismatched,), has_more=False)
            for resource in resources
        },
    )
    settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url="postgresql://unused:unused@127.0.0.1:1/unused",
        ),
        hermes_artifacts=HermesArtifactSettings(feed_path=tmp_path / "missing-hqa-feed.json"),
    )
    client = _client(tmp_path, settings=settings)

    response = client.get("/api/hermes/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["items"][0]["run_links"] is None
    assert payload["warnings"][-1] == {
        "source": "platform_run_links",
        "code": "exact_link_integrity_failed",
        "kind": "factor",
        "resource_id": run_id,
    }


def test_hermes_results_does_not_follow_a_symlinked_run_directory(tmp_path) -> None:
    outside_id = "factor-20260715T110000Z-55555555"
    outside = tmp_path / "outside" / outside_id
    outside.mkdir(parents=True)
    (outside / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": outside_id,
                "kind": "factor",
                "status": "completed",
                "created_at": "2026-07-15T11:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    factor_root = tmp_path / "api_runs" / "factors"
    factor_root.mkdir(parents=True)
    (factor_root / outside_id).symlink_to(outside, target_is_directory=True)
    client = _client(tmp_path)

    response = client.get("/api/hermes/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["items"] == []
    assert {
        "source": "platform_runs",
        "code": "symlink_resource_rejected",
        "kind": "factor",
        "resource_id": outside_id,
    } in payload["warnings"]


def test_hermes_result_detail_does_not_follow_a_nested_result_symlink(tmp_path) -> None:
    run_id = "replication-20260715T120000Z-66666666"
    api_runs = tmp_path / "api_runs"
    _write_run(api_runs, "replications", run_id, kind="replication")
    result_path = api_runs / "replications" / run_id / "result.json"
    outside = tmp_path / "outside-result.json"
    outside.write_text(
        json.dumps({"run_id": run_id, "secret": "must-not-be-read"}),
        encoding="utf-8",
    )
    result_path.unlink()
    result_path.symlink_to(outside)
    client = _client(tmp_path)

    response = client.get(f"/api/hermes/results/replication/{run_id}")

    assert response.status_code == 200
    assert response.json()["read_status"] == "corrupt"
    assert response.json()["resource"] is None
    assert response.json()["warnings"][0]["code"] == "result_corrupt"


def test_hermes_results_isolates_status_outside_the_response_bound(tmp_path) -> None:
    run_id = "factor-20260715T130000Z-77777777"
    _write_run(
        tmp_path / "api_runs",
        "factors",
        run_id,
        kind="factor",
        status="x" * 129,
    )
    client = _client(tmp_path)

    response = client.get("/api/hermes/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    item = next(item for item in payload["items"] if item["resource_id"] == run_id)
    assert item["status"] == "unknown"
    assert item["read_status"] == "corrupt"


def test_hermes_results_isolates_invalid_verified_candidate_timestamp(
    tmp_path,
    monkeypatch,
) -> None:
    agent_output_dir = tmp_path / "agent-output"
    artifact = CandidatePool(agent_output_dir).write_candidate(
        task_id="task-invalid-created-at",
        goal="invalid timestamp isolation",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="class ProposedFactor:\n    pass\n",
        universe=["SPY"],
    )
    original_list = CandidatePool.list_for_read

    def invalid_created_at(self, **kwargs):
        return [
            item.model_copy(update={"created_at": "not-a-timestamp"})
            for item in original_list(self, **kwargs)
        ]

    monkeypatch.setattr(CandidatePool, "list_for_read", invalid_created_at)
    client = _client(
        tmp_path,
        output_dir=tmp_path / "platform",
        agent_output_dir=agent_output_dir,
    )

    response = client.get("/api/hermes/results", params={"source": "platform_candidates"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["items"][0]["resource_id"] == artifact.candidate_id
    assert payload["items"][0]["read_status"] == "corrupt"


def test_hermes_result_detail_bounds_source_warnings(tmp_path, monkeypatch) -> None:
    artifact_id = "risk-warning-bound"
    now = "2026-07-15T14:00:00Z"
    feed = {
        "read_status": "degraded",
        "items": [
            {
                "id": artifact_id,
                "kind": "portfolio_risk",
                "occurred_at": now,
                "quality": "available",
                "status": "available",
                "data": {},
            }
        ],
        "warnings": [
            {"source": "portfolio_risk", "code": f"warning_{index}"} for index in range(25)
        ],
    }
    monkeypatch.setattr(HermesResultsCatalog, "_artifact_feed", lambda _self: feed)
    client = _client(tmp_path)

    response = client.get(f"/api/hermes/results/portfolio_risk/{artifact_id}")

    assert response.status_code == 200
    warnings = response.json()["warnings"]
    assert len(warnings) == 20
    assert warnings[-1]["code"] == "warnings_truncated"


@pytest.mark.parametrize("source", ["platform_runs", "platform_experiments"])
def test_hermes_results_refuses_symlinked_source_roots(tmp_path, source) -> None:
    outside = tmp_path / "outside"
    if source == "platform_runs":
        _write_run(
            outside,
            "factors",
            "factor-20260715T130000Z-77777777",
            kind="factor",
        )
        (tmp_path / "api_runs").symlink_to(outside, target_is_directory=True)
    else:
        experiment_id = "experiment-20260715T130000Z-77777777"
        experiment_dir = outside / experiment_id
        experiment_dir.mkdir(parents=True)
        (experiment_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "run_id": experiment_id,
                    "kind": "experiment",
                    "status": "completed",
                    "created_at": "2026-07-15T13:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "experiments").symlink_to(outside, target_is_directory=True)

    response = _client(tmp_path).get("/api/hermes/results", params={"source": source})

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    source_state = next(item for item in payload["sources"] if item["source"] == source)
    assert source_state["read_status"] == "unavailable"
    assert {
        "source": source,
        "code": "symlink_source_rejected",
        "kind": None,
        "resource_id": None,
    } in payload["warnings"]


def test_hermes_results_isolates_recursive_json_to_one_run(tmp_path) -> None:
    api_runs = tmp_path / "api_runs"
    _write_run(
        api_runs,
        "factors",
        "factor-20260715T140000Z-88888888",
        kind="factor",
    )
    recursive_id = "backtest-20260715T140100Z-99999999"
    recursive_dir = api_runs / "backtests" / recursive_id
    recursive_dir.mkdir(parents=True)
    deeply_nested = "[" * 10_000 + "0" + "]" * 10_000
    (recursive_dir / "metadata.json").write_text(
        '{"run_id":"' + recursive_id + '","kind":"backtest","nested":' + deeply_nested + "}",
        encoding="utf-8",
    )

    response = _client(tmp_path).get("/api/hermes/results")

    assert response.status_code == 200
    by_id = {item["resource_id"]: item for item in response.json()["items"]}
    assert by_id[recursive_id]["read_status"] == "corrupt"
    assert by_id["factor-20260715T140000Z-88888888"]["read_status"] == "available"


def test_utc_timestamp_falls_back_when_filesystem_timestamp_overflows() -> None:
    fake_path = SimpleNamespace(stat=lambda: SimpleNamespace(st_mtime=10**1000))

    assert (
        _utc_timestamp(None, fallback_path=fake_path, resource_id="opaque")
        == "1970-01-01T00:00:00Z"
    )


def test_hermes_results_maps_unbounded_hqa_warning_code_to_stable_code(
    tmp_path, monkeypatch
) -> None:
    feed = {
        "read_status": "unavailable",
        "items": [],
        "warnings": [{"source": "manifest", "code": "x" * 5_000}],
    }
    monkeypatch.setattr(HermesResultsCatalog, "_artifact_feed", lambda _self: feed)

    listing = _client(tmp_path).get("/api/hermes/results", params={"source": "hqa_artifact_feed"})
    detail = _client(tmp_path).get("/api/hermes/results/portfolio_risk/missing-risk")

    assert listing.status_code == 200
    assert listing.json()["warnings"][0]["code"] == "source_warning_invalid"
    assert detail.status_code == 200
    assert detail.json()["warnings"][0]["code"] == "source_warning_invalid"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "replication-20260715T150000Z-not-this-run"),
        ("kind", "backtest"),
    ],
)
def test_hermes_results_rejects_mismatched_replication_result_identity(
    tmp_path, field, value
) -> None:
    run_id = "replication-20260715T150000Z-aaaaaaaa"
    api_runs = tmp_path / "api_runs"
    _write_run(api_runs, "replications", run_id, kind="replication")
    result_path = api_runs / "replications" / run_id / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result[field] = value
    result_path.write_text(json.dumps(result), encoding="utf-8")
    client = _client(tmp_path)

    listing = client.get("/api/hermes/results", params={"source": "platform_runs"})
    detail = client.get(f"/api/hermes/results/replication/{run_id}")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["read_status"] == "corrupt"
    assert detail.status_code == 200
    assert detail.json()["read_status"] == "corrupt"


def test_hermes_candidate_detail_never_reads_legacy_review_or_audit_symlinks(
    tmp_path,
) -> None:
    agent_output_dir = tmp_path / "agent-output"
    artifact = CandidatePool(agent_output_dir).write_candidate(
        task_id="task-safe-projection",
        goal="safe projection",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="class ProposedFactor:\n    pass\n",
    )
    outside = tmp_path / "outside-secret"
    outside.write_text("DO_NOT_EXPOSE", encoding="utf-8")
    (artifact.path.parent / "reviews.jsonl").symlink_to(outside)
    audit_dir = agent_output_dir / "agent" / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "unsafe.jsonl").symlink_to(outside)

    response = _client(
        tmp_path,
        output_dir=tmp_path / "platform",
        agent_output_dir=agent_output_dir,
    ).get(f"/api/hermes/results/factor_candidate/{artifact.candidate_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["item"]["read_status"] == "available"
    assert payload["resource"]["audit"] == []
    assert payload["resource"]["reviews"] == []
    assert "DO_NOT_EXPOSE" not in json.dumps(payload)


def test_hermes_candidate_legacy_unbound_is_visible_but_not_authoritative(
    tmp_path,
) -> None:
    agent_output_dir = tmp_path / "agent-output"
    artifact = CandidatePool(agent_output_dir).write_candidate(
        task_id="task-legacy-unbound",
        goal="legacy unbound",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="class ProposedFactor:\n    pass\n",
    )
    (artifact.path.parent / "approved.lock").write_text("{}", encoding="utf-8")
    client = _client(
        tmp_path,
        output_dir=tmp_path / "platform",
        agent_output_dir=agent_output_dir,
    )

    listing = client.get("/api/hermes/results", params={"source": "platform_candidates"})
    detail = client.get(f"/api/hermes/results/factor_candidate/{artifact.candidate_id}")

    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["read_status"] == "degraded"
    assert item["status"] == "legacy_unbound"
    assert detail.status_code == 200
    assert detail.json()["read_status"] == "degraded"
    assert detail.json()["resource"]["approval_enabled"] is False
    assert detail.json()["warnings"][0]["code"] == "candidate_legacy_unbound"


def test_empty_experiment_directory_is_never_reported_completed(tmp_path) -> None:
    experiment_id = "experiment-20260715T160000Z-bbbbbbbb"
    (tmp_path / "experiments" / experiment_id).mkdir(parents=True)
    client = _client(tmp_path)

    listing = client.get("/api/hermes/results", params={"source": "platform_experiments"})
    detail = client.get(f"/api/hermes/results/experiment/{experiment_id}")

    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["status"] == "unknown"
    assert item["read_status"] == "missing"
    assert detail.status_code == 200
    assert detail.json()["read_status"] == "missing"


def test_symlinked_only_experiment_artifact_is_reported_corrupt(tmp_path) -> None:
    experiment_id = "experiment-20260715T160100Z-bbbbbbbc"
    experiment_dir = tmp_path / "experiments" / experiment_id
    experiment_dir.mkdir(parents=True)
    outside = tmp_path / "outside-runs.parquet"
    outside.write_bytes(b"not-authoritative")
    (experiment_dir / "runs.parquet").symlink_to(outside)
    client = _client(tmp_path)

    listing = client.get("/api/hermes/results", params={"source": "platform_experiments"})
    detail = client.get(f"/api/hermes/results/experiment/{experiment_id}")

    assert listing.status_code == 200
    payload = listing.json()
    assert payload["items"][0]["resource_id"] == experiment_id
    assert payload["items"][0]["read_status"] == "corrupt"
    assert {
        "source": "platform_experiments",
        "code": "result_corrupt",
        "kind": "experiment",
        "resource_id": experiment_id,
    } in payload["warnings"]
    assert detail.status_code == 200
    assert detail.json()["read_status"] == "corrupt"


def test_candidate_nested_metadata_attribute_error_is_isolated(tmp_path, monkeypatch) -> None:
    agent_output_dir = tmp_path / "agent-output"
    artifact = CandidatePool(agent_output_dir).write_candidate(
        task_id="task-bad-metadata-object",
        goal="bad metadata object",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="class ProposedFactor:\n    pass\n",
    )
    original_list = CandidatePool.list_for_read

    def invalid_created_at(self, **kwargs):
        return [
            item.model_copy(update={"created_at": "not-a-timestamp"})
            for item in original_list(self, **kwargs)
        ]

    monkeypatch.setattr(CandidatePool, "list_for_read", invalid_created_at)

    response = _client(
        tmp_path,
        output_dir=tmp_path / "platform",
        agent_output_dir=agent_output_dir,
    ).get("/api/hermes/results")

    assert response.status_code == 200
    item = next(
        item for item in response.json()["items"] if item["resource_id"] == artifact.candidate_id
    )
    assert item["read_status"] == "corrupt"


def test_backtest_detail_does_not_materialize_unrelated_nested_metadata(tmp_path) -> None:
    run_id = "backtest-20260715T170000Z-cccccccc"
    api_runs = tmp_path / "api_runs"
    _write_run(api_runs, "backtests", run_id, kind="backtest")
    metadata_path = api_runs / "backtests" / run_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["benchmark"] = "not-an-object"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    response = _client(tmp_path).get(f"/api/hermes/results/backtest/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["item"]["read_status"] == "available"
    assert payload["resource"]["detail_mode"] == "bounded_manifest"
    assert payload["resource"]["metadata"]["benchmark"] == "not-an-object"


def test_disabled_database_marks_exact_link_authority_unavailable(tmp_path) -> None:
    run_id = "factor-20260715T180000Z-dddddddd"
    _write_run(tmp_path / "api_runs", "factors", run_id, kind="factor")

    response = _client(tmp_path).get("/api/hermes/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["items"][0]["run_links"] is None
    link_source = next(
        source for source in payload["sources"] if source["source"] == "platform_run_links"
    )
    assert link_source["read_status"] == "unavailable"
    assert payload["warnings"][-1] == {
        "source": "platform_run_links",
        "code": "exact_links_not_configured",
        "kind": None,
        "resource_id": None,
    }


def test_exact_run_links_report_truncation_instead_of_silent_partial_truth(
    tmp_path, monkeypatch
) -> None:
    run_id = "factor-20260715T190000Z-eeeeeeee"
    _write_run(tmp_path / "api_runs", "factors", run_id, kind="factor")
    observed_at = datetime(2026, 7, 15, 19, 1, tzinfo=UTC)
    command_id = UUID("00000000-0000-0000-0000-000000000022")
    link = HermesRunLink(
        link_id=UUID("00000000-0000-0000-0000-000000000021"),
        command_id=command_id,
        platform_resource_type="factor",
        platform_resource_id=run_id,
        relation="output",
        hermes_session_id="session-with-many-links",
        resolved_hermes_session_id="session-with-many-links-tip",
        hermes_run_id="run-with-many-links",
        link_digest=hermes_run_link_digest(
            command_id=command_id,
            platform_resource_type="factor",
            platform_resource_id=run_id,
            relation="output",
            hermes_session_id="session-with-many-links",
            resolved_hermes_session_id="session-with-many-links-tip",
            hermes_run_id="run-with-many-links",
            source_event_id=None,
        ),
        source_event_id=None,
        observed_at=observed_at,
        created_at=observed_at,
    )

    def many_links(_self, **kwargs):
        assert kwargs["limit_per_resource"] == 3
        return {
            resource: HermesRunLinkPage(links=(link,) * 3, has_more=True)
            for resource in kwargs["resources"]
        }

    monkeypatch.setattr(HermesCommandLedger, "list_run_links_for_resources", many_links)
    settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url="postgresql://unused:unused@127.0.0.1:1/unused",
        ),
        hermes_artifacts=HermesArtifactSettings(feed_path=tmp_path / "missing-hqa-feed.json"),
    )

    response = _client(tmp_path, settings=settings).get("/api/hermes/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["items"][0]["run_links"] is None
    assert payload["warnings"][-1] == {
        "source": "platform_run_links",
        "code": "exact_links_truncated",
        "kind": "factor",
        "resource_id": run_id,
    }


def test_exact_run_links_are_loaded_in_one_batch_for_the_result_page(tmp_path, monkeypatch) -> None:
    run_ids = [
        "factor-20260715T191000Z-e0000001",
        "factor-20260715T192000Z-e0000002",
        "factor-20260715T193000Z-e0000003",
    ]
    for index, run_id in enumerate(run_ids, start=1):
        _write_run(
            tmp_path / "api_runs",
            "factors",
            run_id,
            kind="factor",
            created_at=f"2026-07-15T19:{index}0:00+00:00",
        )
    calls: list[tuple[tuple[str, str], ...]] = []

    def batch_links(_self, *, resources, limit_per_resource=100):
        assert limit_per_resource == 3
        calls.append(resources)
        return {resource: HermesRunLinkPage(links=(), has_more=False) for resource in resources}

    monkeypatch.setattr(
        HermesCommandLedger,
        "list_run_links_for_resources",
        batch_links,
    )
    settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url="postgresql://unused:unused@127.0.0.1:1/unused",
        ),
        hermes_artifacts=HermesArtifactSettings(feed_path=tmp_path / "missing-hqa-feed.json"),
    )

    response = _client(tmp_path, settings=settings).get(
        "/api/hermes/results",
        params={"source": "platform_runs", "limit": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(calls) == 1
    assert len(calls[0]) == 3
    assert set(calls[0]) == {("factor", run_id) for run_id in run_ids}
    assert all(item["run_links"] == [] for item in payload["items"])


def test_platform_run_source_scan_is_bounded_and_explicitly_degraded(tmp_path, monkeypatch) -> None:
    api_runs = tmp_path / "api_runs"
    _write_run(
        api_runs,
        "factors",
        "factor-20260715T200000Z-f0000001",
        kind="factor",
    )
    _write_run(
        api_runs,
        "factors",
        "factor-20260715T200100Z-f0000002",
        kind="factor",
    )
    monkeypatch.setattr(
        "quant_system.hermes.results_catalog._MAX_SOURCE_ENTRIES",
        1,
    )

    response = _client(tmp_path).get("/api/hermes/results", params={"source": "platform_runs"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] is None
    assert payload["total_is_exact"] is False
    assert {
        "source": "platform_runs",
        "code": "source_scan_limit_exceeded",
        "kind": "factor",
        "resource_id": None,
    } in payload["warnings"]


def test_experiment_source_scan_limit_does_not_publish_a_partial_catalog(
    tmp_path, monkeypatch
) -> None:
    for index in range(2):
        experiment_id = f"experiment-20260715T201{index}00Z-e000000{index}"
        experiment_dir = tmp_path / "experiments" / experiment_id
        experiment_dir.mkdir(parents=True)
        (experiment_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "run_id": experiment_id,
                    "kind": "experiment",
                    "status": "completed",
                    "created_at": f"2026-07-15T20:1{index}:00+00:00",
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr("quant_system.hermes.results_catalog._MAX_SOURCE_ENTRIES", 1)

    payload = (
        _client(tmp_path)
        .get("/api/hermes/results", params={"source": "platform_experiments"})
        .json()
    )

    assert payload["total"] is None
    assert payload["total_is_exact"] is False
    source = next(
        source for source in payload["sources"] if source["source"] == "platform_experiments"
    )
    assert source == {
        "source": "platform_experiments",
        "read_status": "unavailable",
        "item_count": 0,
    }
    assert {
        "source": "platform_experiments",
        "code": "source_scan_limit_exceeded",
        "kind": "experiment",
        "resource_id": None,
    } in payload["warnings"]


def test_candidate_source_scan_limit_does_not_verify_or_publish_a_partial_pool(
    tmp_path, monkeypatch
) -> None:
    agent_output_dir = tmp_path / "agent-output"
    pool = CandidatePool(agent_output_dir)
    for index in range(2):
        pool.write_candidate(
            task_id=f"task-candidate-bound-{index}",
            goal=f"bounded candidate {index}",
            artifact_type="factor",
            filename=f"factor_{index}.py.candidate",
            content=f"class ProposedFactor{index}:\n    pass\n",
        )
    monkeypatch.setattr(
        "quant_system.hermes.results_catalog._MAX_CANDIDATE_SOURCE_ENTRIES",
        1,
    )

    payload = (
        _client(
            tmp_path,
            agent_output_dir=agent_output_dir,
        )
        .get("/api/hermes/results", params={"source": "platform_candidates"})
        .json()
    )

    assert payload["total"] is None
    assert payload["total_is_exact"] is False
    source = next(
        source for source in payload["sources"] if source["source"] == "platform_candidates"
    )
    assert source == {
        "source": "platform_candidates",
        "read_status": "unavailable",
        "item_count": 0,
    }
    assert {
        "source": "platform_candidates",
        "code": "source_scan_limit_exceeded",
        "kind": "factor_candidate",
        "resource_id": None,
    } in payload["warnings"]


def test_result_detail_rejects_an_oversized_aggregate_resource(tmp_path, monkeypatch) -> None:
    run_id = "factor-20260715T210000Z-f1111111"
    _write_run(tmp_path / "api_runs", "factors", run_id, kind="factor")
    monkeypatch.setattr(
        "quant_system.hermes.results_catalog._bounded_run_resource",
        lambda *_args, **_kwargs: {"payload": "x" * (1024 * 1024 + 1)},
    )

    response = _client(tmp_path).get(f"/api/hermes/results/factor/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["item"]["resource_id"] == run_id
    assert payload["resource"] is None
    assert payload["warnings"][0]["code"] == "resource_payload_too_large"


@pytest.mark.parametrize(
    ("kind", "dirname"),
    [
        ("backtest", "backtests"),
        ("factor", "factors"),
        ("paper", "paper"),
    ],
)
def test_completed_run_without_its_completion_artifact_is_never_available(
    tmp_path,
    kind,
    dirname,
) -> None:
    run_id = f"{kind}-20260715T220000Z-a1111111"
    run_dir = tmp_path / "api_runs" / dirname / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "kind": kind,
                "status": "completed",
                "created_at": "2026-07-15T22:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    client = _client(tmp_path)

    listing = client.get("/api/hermes/results", params={"kind": kind}).json()
    detail = client.get(f"/api/hermes/results/{kind}/{run_id}").json()

    assert listing["items"][0]["status"] == "unknown"
    assert listing["items"][0]["read_status"] == "missing"
    assert "completion_artifact_missing" in {warning["code"] for warning in listing["warnings"]}
    assert detail["read_status"] == "missing"
    assert detail["resource"] is None


def test_run_without_explicit_status_is_degraded_not_completed(tmp_path) -> None:
    run_id = "factor-20260715T221000Z-a2222222"
    api_runs = tmp_path / "api_runs"
    _write_run(api_runs, "factors", run_id, kind="factor")
    metadata_path = api_runs / "factors" / run_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("status")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    payload = (
        _client(tmp_path)
        .get(
            "/api/hermes/results",
            params={"kind": "factor"},
        )
        .json()
    )

    assert payload["items"][0]["status"] == "unknown"
    assert payload["items"][0]["read_status"] == "degraded"
    assert "run_status_missing" in {warning["code"] for warning in payload["warnings"]}


def test_source_filter_does_not_read_or_report_an_irrelevant_broken_source(tmp_path) -> None:
    run_id = "factor-20260715T222000Z-a3333333"
    _write_run(tmp_path / "api_runs", "factors", run_id, kind="factor")
    feed_path = tmp_path / "broken-feed.json"
    feed_path.write_text("{not-json", encoding="utf-8")
    settings = Settings(hermes_artifacts=HermesArtifactSettings(feed_path=feed_path))

    payload = (
        _client(tmp_path, settings=settings)
        .get(
            "/api/hermes/results",
            params={"source": "platform_runs"},
        )
        .json()
    )

    assert [item["resource_id"] for item in payload["items"]] == [run_id]
    assert {source["source"] for source in payload["sources"]} == {
        "platform_runs",
        "platform_run_links",
    }
    assert not any(warning["source"] == "hqa_artifact_feed" for warning in payload["warnings"])


def test_kind_filter_skips_other_run_kind_roots(tmp_path) -> None:
    run_id = "backtest-20260715T223000Z-a4444444"
    _write_run(tmp_path / "api_runs", "backtests", run_id, kind="backtest")
    outside = tmp_path / "outside-factors"
    outside.mkdir()
    (tmp_path / "api_runs" / "factors").symlink_to(outside, target_is_directory=True)

    payload = (
        _client(tmp_path)
        .get(
            "/api/hermes/results",
            params={"kind": "backtest"},
        )
        .json()
    )

    assert [item["resource_id"] for item in payload["items"]] == [run_id]
    assert payload["total"] == 1
    assert payload["total_is_exact"] is True
    assert not any(warning.get("kind") == "factor" for warning in payload["warnings"])


def test_run_detail_projects_large_parquet_metadata_without_loading_rows(tmp_path) -> None:
    run_id = "factor-20260715T224000Z-a5555555"
    api_runs = tmp_path / "api_runs"
    _write_run(api_runs, "factors", run_id, kind="factor")
    artifact_path = api_runs / "factors" / run_id / "factors" / "factor_results.parquet"
    original = artifact_path.read_bytes()
    footer_size = int.from_bytes(original[-8:-4], byteorder="little")
    footer_and_trailer = original[-(footer_size + 8) :]
    target_size = 512 * 1024 * 1024
    with artifact_path.open("wb") as handle:
        handle.write(b"PAR1")
        handle.seek(target_size - len(footer_and_trailer))
        handle.write(footer_and_trailer)

    payload = _client(tmp_path).get(f"/api/hermes/results/factor/{run_id}").json()

    assert payload["item"]["read_status"] == "available"
    artifact = next(
        item
        for item in payload["resource"]["artifacts"]
        if item["path"] == "factors/factor_results.parquet"
    )
    assert artifact["size_bytes"] == target_size


def test_completed_run_with_invalid_parquet_is_corrupt_not_available(tmp_path) -> None:
    run_id = "factor-20260715T225000Z-a6666666"
    api_runs = tmp_path / "api_runs"
    _write_run(api_runs, "factors", run_id, kind="factor")
    artifact_path = api_runs / "factors" / run_id / "factors" / "factor_results.parquet"
    artifact_path.write_bytes(b"")
    client = _client(tmp_path)

    listing = client.get("/api/hermes/results", params={"kind": "factor"}).json()
    detail = client.get(f"/api/hermes/results/factor/{run_id}").json()

    assert listing["items"][0]["read_status"] == "corrupt"
    assert detail["read_status"] == "corrupt"
    assert detail["resource"] is None


def test_unknown_total_preserves_pagination_over_safely_observed_items(tmp_path) -> None:
    for index in range(25):
        _write_run(
            tmp_path / "api_runs",
            "factors",
            f"factor-20260715T23{index:02d}00Z-b{index:07d}",
            kind="factor",
            created_at=f"2026-07-15T23:{index:02d}:00+00:00",
        )
    feed_path = tmp_path / "broken-feed.json"
    feed_path.write_text("{not-json", encoding="utf-8")
    settings = Settings(hermes_artifacts=HermesArtifactSettings(feed_path=feed_path))

    payload = (
        _client(tmp_path, settings=settings)
        .get(
            "/api/hermes/results",
            params={"limit": 20},
        )
        .json()
    )

    assert payload["total"] is None
    assert payload["total_is_exact"] is False
    assert payload["has_more"] is True
    assert len(payload["items"]) == 20


def test_result_json_swap_to_symlink_is_rejected_at_open_time(
    tmp_path,
    monkeypatch,
) -> None:
    run_id = "factor-20260716T000000Z-c1111111"
    api_runs = tmp_path / "api_runs"
    _write_run(api_runs, "factors", run_id, kind="factor")
    metadata_path = api_runs / "factors" / run_id / "metadata.json"
    secret_path = tmp_path / "secret.json"
    secret_path.write_text(json.dumps({"secret": "must-not-leak"}), encoding="utf-8")
    original_open = os.open
    swapped = False

    def swap_before_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "metadata.json" and not swapped:
            swapped = True
            metadata_path.unlink()
            metadata_path.symlink_to(secret_path)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_before_open)

    payload = _client(tmp_path).get(f"/api/hermes/results/factor/{run_id}").json()

    assert payload["read_status"] == "corrupt"
    assert payload["resource"] is None
    assert "must-not-leak" not in json.dumps(payload)


def test_result_json_replacement_after_read_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    run_id = "factor-20260716T000500Z-c2222222"
    api_runs = tmp_path / "api_runs"
    _write_run(api_runs, "factors", run_id, kind="factor")
    metadata_path = api_runs / "factors" / run_id / "metadata.json"
    replacement_path = metadata_path.with_suffix(".replacement")
    replacement_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "kind": "factor",
                "status": "completed",
                "request": {"factor_id": "replacement"},
            }
        ),
        encoding="utf-8",
    )
    original_pread = os.pread
    swapped = False

    def swap_after_read(fd: int, length: int, offset: int) -> bytes:
        nonlocal swapped
        payload = original_pread(fd, length, offset)
        if not swapped and offset == 0 and b'"run_id"' in payload:
            swapped = True
            os.replace(replacement_path, metadata_path)
        return payload

    monkeypatch.setattr(os, "pread", swap_after_read)

    payload = _client(tmp_path).get(f"/api/hermes/results/factor/{run_id}").json()

    assert swapped is True
    assert payload["read_status"] == "corrupt"
    assert payload["resource"] is None


def test_source_json_budget_degrades_without_scanning_the_entire_source(
    tmp_path,
    monkeypatch,
) -> None:
    for index in range(3):
        _write_run(
            tmp_path / "api_runs",
            "factors",
            f"factor-20260716T001{index}00Z-d{index:07d}",
            kind="factor",
        )
    monkeypatch.setattr(
        "quant_system.hermes.results_catalog._MAX_SOURCE_REFERENCE_JSON_BYTES",
        250,
    )

    payload = (
        _client(tmp_path)
        .get(
            "/api/hermes/results",
            params={"source": "platform_runs"},
        )
        .json()
    )

    assert payload["total"] is None
    assert payload["total_is_exact"] is False
    assert "source_read_budget_exceeded" in {warning["code"] for warning in payload["warnings"]}


def test_parquet_footer_metadata_charges_the_shared_source_budget(tmp_path) -> None:
    run_id = "factor-20260716T002000Z-e1111111"
    api_runs = tmp_path / "api_runs"
    _write_run(api_runs, "factors", run_id, kind="factor")
    artifact_path = api_runs / "factors" / run_id / "factors" / "factor_results.parquet"

    with pytest.raises(HermesResultSourceBudgetExceeded):
        _validate_parquet_metadata(
            artifact_path,
            budget=_JsonReadBudget(remaining_bytes=1),
        )


def test_candidate_catalog_limit_fails_before_candidate_verification(
    tmp_path,
    monkeypatch,
) -> None:
    pool = CandidatePool(tmp_path / "agent-output")
    for index in range(2):
        pool.write_candidate(
            task_id=f"task-{index}",
            goal=f"bounded candidate {index}",
            artifact_type="factor",
            filename="factor.py.candidate",
            content=f"VALUE = {index}\n",
        )
    monkeypatch.setattr(
        "quant_system.hermes.results_catalog._MAX_CANDIDATE_SOURCE_ENTRIES",
        1,
    )

    def fail_if_verified(*_args, **_kwargs):
        raise AssertionError(
            "candidate verification must not start after a preflight limit failure"
        )

    monkeypatch.setattr(CandidatePool, "_read_item_at", fail_if_verified)

    payload = (
        _client(
            tmp_path,
            agent_output_dir=tmp_path / "agent-output",
        )
        .get(
            "/api/hermes/results",
            params={"source": "platform_candidates"},
        )
        .json()
    )

    assert payload["total"] is None
    assert payload["total_is_exact"] is False
    assert payload["items"] == []
    assert "source_scan_limit_exceeded" in {warning["code"] for warning in payload["warnings"]}
