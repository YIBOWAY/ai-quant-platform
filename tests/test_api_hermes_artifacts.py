import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import HermesArtifactSettings, Settings
from quant_system.hermes.models import HermesArtifactFeedResponse


def _risk_data() -> dict:
    return {
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


def _prediction_data() -> dict:
    return {
        "prediction_id": "2026-07-12-001",
        "state": "open",
        "symbol": "AAPL",
        "direction": "up",
        "confidence": 0.6,
        "horizon_date": "2026-07-19",
        "rationale": "bounded rationale",
        "outcome_return": None,
        "direction_brier": None,
    }


def _foresight_data() -> dict:
    return {
        "run_id": "foresight-run-001",
        "summary": "AAPL up through 2026-07-19",
        "candidate_count": 1,
        "candidates": [
            {
                "id": "mfp_candidate_001",
                "symbol": "AAPL",
                "direction": "up",
                "confidence": 0.6,
                "horizon_date": "2026-07-19",
                "falsifier": "Return is not positive.",
                "rationale": "bounded rationale",
                "entry_session_date": "2026-07-11",
                "entry_close": 100.0,
                "provider": "futu",
                "adjustment": "qfq",
                "proposal_only": True,
                "requires_human_confirmation": True,
                "trading_allowed": False,
            }
        ],
    }


def _sources(**overrides: dict) -> list[dict]:
    rows = []
    for kind in ("portfolio_risk", "prediction", "market_foresight"):
        row = {
            "kind": kind,
            "status": "empty",
            "latest_at": None,
            "reason_code": None,
        }
        row.update(overrides.get(kind, {}))
        rows.append(row)
    return rows


def _sources_v11(**overrides: dict) -> list[dict]:
    rows = []
    for kind in (
        "portfolio_risk",
        "prediction",
        "market_foresight",
        "weekly_review",
        "opportunity_summary",
        "automation_status",
    ):
        row = {
            "kind": kind,
            "status": "empty",
            "latest_at": None,
            "reason_code": None,
        }
        row.update(overrides.get(kind, {}))
        rows.append(row)
    return rows


def _weekly_review_data(now: str) -> dict:
    parsed_now = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC)
    now = parsed_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    period_start = (parsed_now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    week_year, week_number, _ = parsed_now.astimezone(
        ZoneInfo("Asia/Shanghai")
    ).isocalendar()
    return {
        "week_id": f"{week_year:04d}-W{week_number:02d}",
        "period_start": period_start,
        "period_end": now,
        "safety_alert_count": 1,
        "unique_signal_count": 3,
        "review_draft_count": 2,
        "review_confirmed_count": 1,
        "prediction_created_count": 2,
        "prediction_scored_count": 1,
        "prediction_hit_count": 1,
        "mean_direction_brier": 0.09,
        "opportunity_observed_count": 4,
        "opportunity_missed_count": 1,
        "opportunity_coverage_unknown_count": 1,
        "limitations": ["read_only_research_summary"],
        "proposal_only": True,
        "trading_allowed": False,
    }


def _opportunity_summary_data(now: str) -> dict:
    parsed_now = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC)
    now = parsed_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "window_start": (parsed_now - timedelta(days=7)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "window_end": now,
        "total_count": 4,
        "resolution_counts": {
            "open": 1,
            "deferred": 0,
            "acted": 1,
            "action_failed": 0,
            "declined": 0,
            "missed": 1,
            "expired_coverage_unknown": 1,
            "not_actionable": 0,
            "unknown": 0,
        },
        "miss_reason_counts": {
            "no_decision": 1,
            "act_without_action": 0,
            "defer_expired": 0,
        },
        "proposal_only": True,
        "trading_allowed": False,
    }


def _automation_status_data(now: str) -> dict:
    parsed_now = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC)
    now = parsed_now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "checked_at": now,
        "overall_status": "degraded",
        "jobs": [
            {
                "job_id": "daily_close",
                "expected_schedule": "30 6 * * *",
                "timezone": "Asia/Shanghai",
                "freshness_budget_seconds": 108000,
                "last_attempt_at": now,
                "last_success_at": now,
                "fresh_until": (
                    parsed_now + timedelta(seconds=108000)
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": "fresh",
                "reason_code": None,
                "last_run_id": "daily-close-001",
                "notification_status": "not_required",
            },
            {
                "job_id": "weekly",
                "expected_schedule": "0 9 * * 0",
                "timezone": "Asia/Shanghai",
                "freshness_budget_seconds": 691200,
                "last_attempt_at": None,
                "last_success_at": None,
                "fresh_until": None,
                "status": "never_run",
                "reason_code": "never_run",
                "last_run_id": None,
                "notification_status": "not_required",
            },
            {
                "job_id": "freshness",
                "expected_schedule": "17 */2 * * *",
                "timezone": "Asia/Shanghai",
                "freshness_budget_seconds": 10800,
                "last_attempt_at": None,
                "last_success_at": None,
                "fresh_until": None,
                "status": "never_run",
                "reason_code": "never_run",
                "last_run_id": None,
                "notification_status": "not_required",
            },
            {
                "job_id": "notification_drain",
                "expected_schedule": "*/15 * * * *",
                "timezone": "Asia/Shanghai",
                "freshness_budget_seconds": 1800,
                "last_attempt_at": None,
                "last_success_at": None,
                "fresh_until": None,
                "status": "never_run",
                "reason_code": "never_run",
                "last_run_id": None,
                "notification_status": "not_required",
            },
        ],
        "proposal_only": True,
        "trading_allowed": False,
    }


def _manifest_v11(now: str) -> dict:
    now = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    items = [
        {
            "id": "weekly-2026-W28",
            "kind": "weekly_review",
            "occurred_at": now,
            "quality": "available",
            "status": "available",
            "data": _weekly_review_data(now),
        },
        {
            "id": "opportunities-2026-W28",
            "kind": "opportunity_summary",
            "occurred_at": now,
            "quality": "available",
            "status": "available",
            "data": _opportunity_summary_data(now),
        },
        {
            "id": "automation-latest",
            "kind": "automation_status",
            "occurred_at": now,
            "quality": "degraded",
            "status": "degraded",
            "data": _automation_status_data(now),
        },
    ]
    return {
        "schema_version": "1.1",
        "read_status": "available",
        "as_of": now,
        "items": items,
        "sources": _sources_v11(
            weekly_review={"status": "available", "latest_at": now},
            opportunity_summary={"status": "available", "latest_at": now},
            automation_status={"status": "available", "latest_at": now},
        ),
        "warnings": [],
    }


def test_hermes_artifacts_missing_feed_is_empty_and_read_only(tmp_path) -> None:
    feed_path = tmp_path / "not-built" / "manifest.json"
    settings = Settings(
        hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path / "platform"))

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert payload["read_status"] == "empty"
    assert payload["as_of"] is None
    assert payload["items"] == []
    assert payload["sources"] == []
    assert payload["warnings"] == [
        {"source": "artifact_feed", "code": "feed_not_built"}
    ]
    assert feed_path.parent.exists() is False


def test_hermes_artifacts_returns_newest_valid_items_with_limit(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now.isoformat().replace("+00:00", "Z"),
                "items": [
                    {
                        "id": "risk-older",
                        "kind": "portfolio_risk",
                        "occurred_at": (now - timedelta(minutes=5))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "quality": "available",
                        "status": "available",
                        "data": _risk_data(),
                    },
                    {
                        "id": "foresight-newer",
                        "kind": "market_foresight",
                        "occurred_at": (now - timedelta(minutes=1))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "quality": "available",
                        "status": "candidate",
                        "data": _foresight_data(),
                    },
                ],
                "sources": _sources(
                    portfolio_risk={
                        "status": "available",
                        "latest_at": (now - timedelta(minutes=5))
                        .isoformat()
                        .replace("+00:00", "Z"),
                    },
                    market_foresight={
                        "status": "available",
                        "latest_at": now.isoformat().replace("+00:00", "Z"),
                    },
                ),
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    manifest_before = feed_path.read_bytes()
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts?limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "available"
    assert [item["id"] for item in payload["items"]] == ["foresight-newer"]
    assert payload["sources"] == _sources(
        portfolio_risk={
            "status": "available",
            "latest_at": (now - timedelta(minutes=5))
            .isoformat()
            .replace("+00:00", "Z"),
        },
        market_foresight={
            "status": "available",
            "latest_at": now.isoformat().replace("+00:00", "Z"),
        },
    )
    assert payload["warnings"] == []
    assert feed_path.read_bytes() == manifest_before


def test_hermes_artifacts_reads_strict_schema_v11_with_six_sources(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    now_text = now.isoformat().replace("+00:00", "Z")
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(_manifest_v11(now_text)),
        encoding="utf-8",
    )
    manifest_before = feed_path.read_bytes()
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.1"
    assert payload["read_status"] == "available"
    assert {item["kind"] for item in payload["items"]} == {
        "weekly_review",
        "opportunity_summary",
        "automation_status",
    }
    assert payload["sources"] == _sources_v11(
        weekly_review={"status": "available", "latest_at": now_text},
        opportunity_summary={"status": "available", "latest_at": now_text},
        automation_status={"status": "available", "latest_at": now_text},
    )
    assert feed_path.read_bytes() == manifest_before


def test_schema_v11_accepts_truthful_queued_notification_state() -> None:
    manifest = _manifest_v11("2026-07-12T01:00:00Z")
    manifest["items"][2]["data"]["jobs"][0]["notification_status"] = "queued"

    validated = HermesArtifactFeedResponse.model_validate(manifest)

    assert validated.items[2].root.data.jobs[0].notification_status == "queued"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest["sources"].pop(),
        lambda manifest: manifest["items"][0]["data"].update(
            {"prediction_hit_count": 2}
        ),
        lambda manifest: manifest["items"][1]["data"][
            "resolution_counts"
        ].update({"open": 2}),
        lambda manifest: manifest["items"][1]["data"][
            "miss_reason_counts"
        ].update({"no_decision": 0}),
        lambda manifest: manifest["items"][2]["data"]["jobs"].append(
            manifest["items"][2]["data"]["jobs"][0].copy()
        ),
        lambda manifest: manifest["items"][2]["data"]["jobs"].pop(),
        lambda manifest: manifest["items"][0]["data"].update(
            {"private_path": "/Users/private/weekly.json"}
        ),
        lambda manifest: manifest["items"][0]["data"].update(
            {"week_id": "week 28"}
        ),
        lambda manifest: manifest["items"][0]["data"].update(
            {"limitations": [f"limitation_{index}" for index in range(21)]}
        ),
        lambda manifest: manifest["items"][0]["data"].update(
            {"safety_alert_count": True}
        ),
        lambda manifest: manifest["items"][0]["data"].update(
            {"mean_direction_brier": True}
        ),
        lambda manifest: manifest["items"][1]["data"].update(
            {"proposal_only": 1, "trading_allowed": 0}
        ),
        lambda manifest: manifest["items"][0]["data"].update(
            {"period_start": 123}
        ),
        lambda manifest: manifest["items"][2]["data"].update(
            {"checked_at": 123}
        ),
    ],
    ids=(
        "wrong-source-set",
        "weekly-hit-count",
        "resolution-sum",
        "miss-reason-sum",
        "duplicate-job",
        "incomplete-job-set",
        "extra-payload-key",
        "invalid-week-id",
        "too-many-limitations",
        "boolean-count",
        "boolean-brier",
        "numeric-safety-flags",
        "numeric-period-timestamp",
        "numeric-checked-at",
    ),
)
def test_hermes_artifacts_rejects_inconsistent_schema_v11_payloads(
    mutate,
    tmp_path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    manifest = _manifest_v11(now)
    mutate(manifest)
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(json.dumps(manifest), encoding="utf-8")
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]
    assert "/Users/private" not in response.text


def test_weekly_missed_count_may_refer_to_an_opportunity_observed_before_window(
    tmp_path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    manifest = _manifest_v11(now)
    weekly = manifest["items"][0]["data"]
    weekly["opportunity_observed_count"] = 0
    weekly["opportunity_missed_count"] = 1
    weekly["opportunity_coverage_unknown_count"] = 0
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(json.dumps(manifest), encoding="utf-8")
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "available"


def test_hermes_artifacts_rejects_non_finite_schema_v11_numbers(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    manifest_text = json.dumps(_manifest_v11(now)).replace(
        '"mean_direction_brier": 0.09',
        '"mean_direction_brier": NaN',
    )
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(manifest_text, encoding="utf-8")
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


def test_hermes_artifacts_rejects_nested_schema_v11_future_timestamp(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    manifest = _manifest_v11(now.isoformat())
    manifest["items"][2]["data"]["checked_at"] = (
        now + timedelta(minutes=10)
    ).isoformat().replace("+00:00", "Z")
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(json.dumps(manifest), encoding="utf-8")
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(
                    feed_path=feed_path,
                    max_future_clock_skew_seconds=60,
                ),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_clock_skew"}
    ]


def test_hermes_artifacts_allows_schedule_aware_future_fresh_until(
    tmp_path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    manifest = _manifest_v11(now.isoformat())
    manifest["items"][2]["data"]["jobs"][0]["fresh_until"] = (
        now + timedelta(days=3)
    ).isoformat().replace("+00:00", "Z")
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(json.dumps(manifest), encoding="utf-8")
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(
                    feed_path=feed_path,
                    max_future_clock_skew_seconds=60,
                ),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["schema_version"] == "1.1"
    assert response.json()["read_status"] == "available"


def test_hermes_artifacts_marks_an_old_manifest_degraded(tmp_path) -> None:
    old = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "empty",
                "as_of": old.isoformat().replace("+00:00", "Z"),
                "items": [],
                "sources": _sources(),
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(
                    feed_path=feed_path,
                    freshness_budget_seconds=60,
                ),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "degraded"
    assert payload["warnings"] == [
        {"source": "artifact_feed", "code": "feed_stale"}
    ]


def test_hermes_artifacts_marks_partial_source_failures_degraded(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "degraded",
                "as_of": now.isoformat().replace("+00:00", "Z"),
                "items": [],
                "sources": _sources(
                    prediction={
                        "status": "unavailable",
                        "reason_code": "prediction_ledger_unavailable",
                    }
                ),
                "warnings": [
                    {
                        "source": "prediction",
                        "code": "prediction_ledger_unavailable",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "degraded"
    prediction_source = next(
        source
        for source in response.json()["sources"]
        if source["kind"] == "prediction"
    )
    assert prediction_source["reason_code"] == "prediction_ledger_unavailable"


def test_hermes_artifacts_rejects_duplicate_artifact_ids(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    feed_path = tmp_path / "manifest.v1.json"
    item = {
        "id": "duplicate-id",
        "kind": "prediction",
        "occurred_at": now.isoformat().replace("+00:00", "Z"),
        "quality": "available",
        "status": "open",
        "data": _prediction_data(),
    }
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now.isoformat().replace("+00:00", "Z"),
                "items": [item, item],
                "sources": _sources(
                    prediction={
                        "status": "available",
                        "latest_at": now.isoformat().replace("+00:00", "Z"),
                    }
                ),
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "unavailable"
    assert payload["items"] == []
    assert payload["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]
    assert str(feed_path) not in response.text


def test_hermes_artifacts_rejects_unsupported_manifest_version(tmp_path) -> None:
    feed_path = tmp_path / "manifest.v2.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "read_status": "available",
                "as_of": datetime.now(UTC).isoformat(),
                "items": [],
                "sources": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["read_status"] == "unavailable"
    assert payload["warnings"] == [
        {"source": "artifact_feed", "code": "feed_schema_unsupported"}
    ]


def test_hermes_artifacts_rejects_unknown_item_quality(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now,
                "items": [
                    {
                        "id": "risk-invalid-quality",
                        "kind": "portfolio_risk",
                        "occurred_at": now,
                        "quality": "complete",
                        "status": "available",
                        "data": _risk_data(),
                    }
                ],
                "sources": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


def test_hermes_artifacts_rejects_unknown_source_status(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now,
                "items": [],
                "sources": [
                    {
                        "kind": "prediction",
                        "status": "partial",
                        "latest_at": now,
                        "reason_code": None,
                    }
                ],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


def test_hermes_artifacts_rejects_oversized_manifest_before_reading(
    monkeypatch,
    tmp_path,
) -> None:
    feed_path = tmp_path / "oversized-manifest.json"
    feed_path.write_bytes(b"x" * 33)
    original_read_text = type(feed_path).read_text

    def guarded_read_text(path, *args, **kwargs):
        if path == feed_path:
            raise AssertionError("oversized manifest must not be read")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(type(feed_path), "read_text", guarded_read_text)
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(
                    feed_path=feed_path,
                    max_manifest_bytes=32,
                ),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_too_large"}
    ]
    assert str(feed_path) not in response.text


def test_hermes_artifacts_rejects_empty_manifest_with_items(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "empty",
                "as_of": now,
                "items": [
                    {
                        "id": "unexpected-item",
                        "kind": "prediction",
                        "occurred_at": now,
                        "quality": "available",
                        "status": "open",
                        "data": _prediction_data(),
                    }
                ],
                "sources": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


def test_hermes_artifacts_rejects_duplicate_source_kinds(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    feed_path = tmp_path / "manifest.v1.json"
    source = {
        "kind": "prediction",
        "status": "available",
        "latest_at": now,
        "reason_code": None,
    }
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now,
                "items": [],
                "sources": [source, source],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


def test_hermes_artifacts_requires_as_of_for_available_manifest(tmp_path) -> None:
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": None,
                "items": [],
                "sources": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


def test_hermes_artifacts_requires_as_of_for_persisted_empty_manifest(tmp_path) -> None:
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "read_status": "empty",
                "as_of": None,
                "items": [],
                "sources": _sources_v11(),
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(
                    feed_path=feed_path,
                    freshness_budget_seconds=1,
                ),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest["items"][0]["data"].update(
            {"week_id": "2026-W99"}
        ),
        lambda manifest: manifest["items"][0]["data"].update(
            {"period_start": "2026-07-12T00:00:00Z"}
        ),
        lambda manifest: manifest["items"][1]["data"].update(
            {"window_start": "2026-07-12T00:00:00Z"}
        ),
        lambda manifest: manifest["items"][2]["data"]["jobs"][0].update(
            {
                "last_attempt_at": "2026-07-12T02:00:00Z",
                "last_success_at": "2026-07-12T01:30:00Z",
            }
        ),
    ],
    ids=(
        "invalid-iso-week",
        "short-weekly-window",
        "short-opportunity-window",
        "inverted-timeline",
    ),
)
def test_schema_v11_rejects_invalid_period_and_automation_causality(mutate) -> None:
    manifest = _manifest_v11("2026-07-12T01:00:00Z")
    mutate(manifest)

    with pytest.raises(ValueError):
        HermesArtifactFeedResponse.model_validate(manifest)


@pytest.mark.parametrize(
    "kind",
    ["weekly_review", "opportunity_summary", "automation_status"],
)
def test_hermes_artifacts_rejects_nested_fact_after_item_occurrence(
    tmp_path,
    kind: str,
) -> None:
    as_of = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)
    manifest = _manifest_v11(as_of.isoformat().replace("+00:00", "Z"))
    item = next(item for item in manifest["items"] if item["kind"] == kind)
    item["occurred_at"] = (as_of - timedelta(minutes=10)).isoformat().replace(
        "+00:00", "Z"
    )
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(json.dumps(manifest), encoding="utf-8")
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


@pytest.mark.parametrize("field", ["item", "source"])
def test_hermes_artifacts_rejects_manifest_fact_after_as_of(
    tmp_path,
    field: str,
) -> None:
    as_of = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)
    manifest = _manifest_v11(as_of.isoformat().replace("+00:00", "Z"))
    later = (as_of + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    if field == "item":
        manifest["items"][0]["occurred_at"] = later
    else:
        manifest["sources"][3]["latest_at"] = later
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(json.dumps(manifest), encoding="utf-8")
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


def test_schema_v10_keeps_legacy_clock_skew_contract(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    now_text = now.isoformat()
    within_skew = (now + timedelta(seconds=30)).isoformat()
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now_text,
                "items": [
                    {
                        "id": "legacy-prediction",
                        "kind": "prediction",
                        "occurred_at": within_skew,
                        "quality": "available",
                        "status": "open",
                        "data": _prediction_data(),
                    }
                ],
                "sources": _sources(
                    prediction={"status": "available", "latest_at": within_skew}
                ),
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "available"
    assert response.json()["warnings"] == []


def test_hermes_artifacts_keeps_healthy_empty_sources_empty(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "empty",
                "as_of": now,
                "items": [],
                "sources": _sources(),
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "empty"
    assert response.json()["sources"] == _sources()


@pytest.mark.parametrize("mismatch", ["available_without_items", "empty_with_available_source"])
def test_hermes_artifacts_rejects_aggregate_status_mismatch(
    mismatch,
    tmp_path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    sources = _sources()
    read_status = "available"
    if mismatch == "empty_with_available_source":
        read_status = "empty"
        sources = _sources(
            prediction={"status": "available", "latest_at": now}
        )
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": read_status,
                "as_of": now,
                "items": [],
                "sources": sources,
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


def test_hermes_artifacts_rejects_missing_source_status(tmp_path) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now,
                "items": [],
                "sources": _sources()[:-1],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


@pytest.mark.parametrize(
    "prediction_source",
    [
        {"status": "empty", "latest_at": "2026-07-01T00:00:00Z"},
        {"status": "available", "latest_at": None},
        {"status": "degraded", "reason_code": None},
        {
            "status": "available",
            "latest_at": "2026-07-01T00:00:00Z",
            "reason_code": "unexpected_reason",
        },
    ],
)
def test_hermes_artifacts_rejects_incoherent_source_status(
    prediction_source,
    tmp_path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now,
                "items": [],
                "sources": _sources(prediction=prediction_source),
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        (
            "portfolio_risk",
            {**_risk_data(), "private_path": "/Users/private/risk.json"},
        ),
        (
            "prediction",
            {
                **_prediction_data(),
                "rationale": {"leak": "/Users/private/prediction.json"},
            },
        ),
        (
            "market_foresight",
            {
                **_foresight_data(),
                "candidates": [
                    {
                        **_foresight_data()["candidates"][0],
                        "rationale": {"leak": "/Users/private/foresight.json"},
                    }
                ],
            },
        ),
    ],
)
def test_hermes_artifacts_rejects_untrusted_kind_payloads(
    kind,
    data,
    tmp_path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now,
                "items": [
                    {
                        "id": f"unsafe-{kind}",
                        "kind": kind,
                        "occurred_at": now,
                        "quality": "available",
                        "status": "available",
                        "data": data,
                    }
                ],
                "sources": _sources(
                    **{
                        kind: {
                            "status": "available",
                            "latest_at": now,
                        }
                    }
                ),
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]
    assert "/Users/private" not in response.text
    assert "private_path" not in response.text


@pytest.mark.parametrize(
    "manifest_text",
    [
        "[" * 2000 + "0" + "]" * 2000,
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": "0001-01-01T00:00:00+23:59",
                "items": [],
                "sources": [],
                "warnings": [],
            }
        ),
    ],
)
def test_hermes_artifacts_maps_parser_extremes_to_unavailable(
    manifest_text,
    tmp_path,
) -> None:
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(manifest_text, encoding="utf-8")
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(feed_path=feed_path),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_corrupt"}
    ]
    assert str(feed_path) not in response.text


def test_hermes_artifacts_rejects_timestamps_beyond_clock_skew(tmp_path) -> None:
    future = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=10)
    future_text = future.isoformat()
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "empty",
                "as_of": future_text,
                "items": [],
                "sources": [
                    {
                        "kind": kind,
                        "status": "empty",
                        "latest_at": None,
                        "reason_code": None,
                    }
                    for kind in (
                        "portfolio_risk",
                        "prediction",
                        "market_foresight",
                    )
                ],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(
                    feed_path=feed_path,
                    max_future_clock_skew_seconds=60,
                ),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_clock_skew"}
    ]


@pytest.mark.parametrize("target", ["item", "source"])
def test_hermes_artifacts_rejects_nested_timestamps_beyond_clock_skew(
    target,
    tmp_path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    now_text = now.isoformat()
    future_text = (now + timedelta(minutes=10)).isoformat()
    item_time = future_text if target == "item" else now_text
    source_time = future_text if target == "source" else now_text
    feed_path = tmp_path / "manifest.v1.json"
    feed_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "read_status": "available",
                "as_of": now_text,
                "items": [
                    {
                        "id": "future-prediction",
                        "kind": "prediction",
                        "occurred_at": item_time,
                        "quality": "available",
                        "status": "open",
                        "data": _prediction_data(),
                    }
                ],
                "sources": _sources(
                    prediction={
                        "status": "available",
                        "latest_at": source_time,
                    }
                ),
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                hermes_artifacts=HermesArtifactSettings(
                    feed_path=feed_path,
                    max_future_clock_skew_seconds=60,
                ),
            ),
            output_dir=tmp_path / "platform",
        )
    )

    response = client.get("/api/hermes/artifacts")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"] == [
        {"source": "artifact_feed", "code": "feed_clock_skew"}
    ]
