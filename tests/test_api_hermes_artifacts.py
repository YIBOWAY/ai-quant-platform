import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import HermesArtifactSettings, Settings


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
