from __future__ import annotations

from fastapi import APIRouter, Query

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.hermes import HermesArtifactFeedResponse
from quant_system.hermes.artifact_catalog import HermesArtifactCatalog

router = APIRouter()


@router.get("/hermes/artifacts", response_model=HermesArtifactFeedResponse)
def hermes_artifacts(
    settings: SettingsDep,
    limit: int = Query(default=20, ge=1, le=50),
) -> dict:
    catalog = HermesArtifactCatalog(
        settings.hermes_artifacts.feed_path,
        freshness_budget_seconds=settings.hermes_artifacts.freshness_budget_seconds,
        max_future_clock_skew_seconds=(
            settings.hermes_artifacts.max_future_clock_skew_seconds
        ),
        max_manifest_bytes=settings.hermes_artifacts.max_manifest_bytes,
    )
    return catalog.latest(limit=limit)
