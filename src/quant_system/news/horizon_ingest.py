"""Host-side Horizon inbox ingest (cron CLI path only)."""

from __future__ import annotations

import logging
from typing import Any

from quant_system.config.settings import Settings
from quant_system.news.horizon_inbox import iter_ready_runs
from quant_system.news.horizon_repository import is_run_ingested, persist_horizon_run

log = logging.getLogger(__name__)

PROVIDER = "horizon"


def ingest_horizon_inbox(
    *,
    settings: Settings,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Ingest READY Horizon inbox runs into PG.

    Returns ``{"ingested": [...], "skipped": [...], "failed": [{run_id, error}]}``.
    When Horizon is disabled, returns empty lists and performs no DB writes.
    """

    if not settings.horizon.enabled:
        return {"ingested": [], "skipped": [], "failed": []}

    runs = iter_ready_runs(settings.horizon.inbox_dir)
    if run_id is not None:
        runs = [run for run in runs if run.run_id == run_id]

    ingested: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []

    for run in runs:
        if is_run_ingested(PROVIDER, run.run_id, run.content_digest, settings):
            skipped.append(run.run_id)
            continue
        try:
            persist_horizon_run(run, settings=settings)
            ingested.append(run.run_id)
            marker = run.path / "INGESTED"
            marker.write_text(run.content_digest, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - per-run isolation
            failed.append({"run_id": run.run_id, "error": str(exc)})
            log.exception("horizon ingest failed for %s", run.run_id)

    return {"ingested": ingested, "skipped": skipped, "failed": failed}
