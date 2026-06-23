"""Run index repository: PostgreSQL-first reads with filesystem fallback.

The file artifacts under ``data/api_runs/<kind>/<run_id>/metadata.json`` stay the
source of truth. When the optional PostgreSQL index is enabled and reachable,
list endpoints read from it (fast, ordered, no directory scan) and run endpoints
index each new run into it. Any database error degrades silently to the existing
filesystem behaviour, so the API never depends on the database being up.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from quant_system.api.schemas.common import (
    RunStatus,
    sorted_metadata_paths,
    write_json_atomic,
)
from quant_system.storage.database import SCHEMA, get_database

if TYPE_CHECKING:
    from quant_system.config.settings import Settings

log = logging.getLogger(__name__)

# Run kinds that follow the shared api_runs/<dir>/<run_id>/metadata.json layout,
# mapped to their on-disk directory name (note: paper dir is "paper", not "papers").
KIND_DIRS = {
    "backtest": "backtests",
    "factor": "factors",
    "paper": "paper",
    "replication": "replications",
}
INDEXED_KINDS = tuple(KIND_DIRS)


def _created_at_from_run_id(run_id: str) -> str | None:
    """Extract the ISO timestamp encoded in ``<prefix>-YYYYMMDDTHHMMSSZ-<hex>``."""
    for token in run_id.split("-"):
        if len(token) == 16 and token.endswith("Z") and "T" in token:
            try:
                stamp = datetime.strptime(token, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
                return stamp.isoformat()
            except ValueError:
                continue
    return None


def persist_run(
    run_dir: Path,
    kind: str,
    payload: dict[str, Any],
    *,
    settings: Settings,
    status: RunStatus = RunStatus.COMPLETED,
    index: bool = True,
) -> dict[str, Any]:
    """Write a run's ``metadata.json`` atomically under a unified schema.

    Every run producer (backtest / paper / factor / experiment / replication)
    routes its metadata through here so the on-disk ``metadata.json`` always
    carries the shared core fields — ``run_id``, ``kind``, ``status`` and
    ``created_at`` — alongside its kind-specific fields. The filesystem stays
    the source of truth; the optional PostgreSQL index is updated as a best-effort
    mirror when ``index`` is true and the kind is indexable.

    ``payload`` is not mutated; the merged metadata dict (with core fields
    filled in) is returned so the caller can echo it back in the HTTP response.
    The run_id defaults to the run directory name when absent, and created_at is
    derived from the run_id timestamp, then falls back to now.
    """
    run_dir = Path(run_dir)
    metadata = dict(payload)
    run_id = str(metadata.get("run_id") or run_dir.name)
    metadata["run_id"] = run_id
    metadata["kind"] = kind
    metadata["status"] = RunStatus(status).value
    if not metadata.get("created_at"):
        metadata["created_at"] = (
            _created_at_from_run_id(run_id) or datetime.now(UTC).isoformat()
        )
    write_json_atomic(run_dir / "metadata.json", metadata)
    if index and kind in KIND_DIRS:
        index_run(kind, metadata, run_dir, settings)
    return metadata


def index_run(
    kind: str,
    metadata: dict[str, Any],
    artifact_path: Path | str,
    settings: Settings,
) -> None:
    """Upsert a single run into the index. Never raises (warn-and-continue)."""
    database = get_database(settings)
    if database is None:
        return
    run_id = metadata.get("run_id")
    if not run_id:
        return
    try:
        with database.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO {SCHEMA}.runs
                    (kind, run_id, source, artifact_path, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s, COALESCE(%s::timestamptz, now()))
                ON CONFLICT (kind, run_id) DO UPDATE
                SET source = EXCLUDED.source,
                    artifact_path = EXCLUDED.artifact_path,
                    metadata = EXCLUDED.metadata
                """,
                (
                    kind,
                    run_id,
                    metadata.get("source"),
                    str(artifact_path),
                    json.dumps(metadata),
                    _created_at_from_run_id(run_id),
                ),
            )
    except Exception as exc:  # noqa: BLE001 - indexing is best-effort
        log.warning("postgres index for %s run %s failed (using files): %s", kind, run_id, exc)


def _db_metadatas(kind: str, settings: Settings) -> list[dict[str, Any]] | None:
    database = get_database(settings)
    if database is None:
        return None
    try:
        with database.connect() as conn:
            rows = conn.execute(
                f"SELECT metadata FROM {SCHEMA}.runs WHERE kind = %s "
                f"ORDER BY created_at DESC, indexed_at DESC",
                (kind,),
            ).fetchall()
        return [row[0] for row in rows]
    except Exception as exc:  # noqa: BLE001 - fall back to filesystem
        log.warning("postgres read for %s failed (using files): %s", kind, exc)
        return None


def _fs_metadatas(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted_metadata_paths(root):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - skip unreadable run
            log.warning("skipping unreadable metadata %s: %s", path, exc)
    return out


def list_run_metadatas(kind: str, root: Path, settings: Settings) -> list[dict[str, Any]]:
    """Return run metadata dicts newest-first, using files for membership/order.

    PostgreSQL remains a fast metadata mirror, but the filesystem is the source
    of truth. This also makes runs copied or created while the API is already
    running visible immediately instead of waiting for the next startup sync.
    """
    db_rows = _db_metadatas(kind, settings)
    paths = sorted_metadata_paths(root)
    if db_rows is None:
        return _fs_metadatas(root)

    db_by_id = {
        str(metadata.get("run_id")): metadata
        for metadata in db_rows
        if metadata.get("run_id")
    }
    out: list[dict[str, Any]] = []
    for path in paths:
        run_id = path.parent.name
        metadata = db_by_id.get(run_id)
        if metadata is not None:
            out.append(metadata)
            continue
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001 - skip unreadable run
            log.warning("skipping unreadable metadata %s: %s", path, exc)
    return out


def _prune_missing(kind: str, present_run_ids: set[str], settings: Settings) -> int:
    """Delete index rows for ``kind`` whose run is no longer on disk.

    Keeps the index consistent with the filesystem source of truth so a
    DB-backed list never returns a run whose detail endpoint would 404 (e.g.
    after a run directory is deleted). Never raises.
    """
    database = get_database(settings)
    if database is None:
        return 0
    try:
        with database.connect() as conn:
            existing = conn.execute(
                f"SELECT run_id FROM {SCHEMA}.runs WHERE kind = %s",
                (kind,),
            ).fetchall()
            stale = [row[0] for row in existing if row[0] not in present_run_ids]
            for run_id in stale:
                conn.execute(
                    f"DELETE FROM {SCHEMA}.runs WHERE kind = %s AND run_id = %s",
                    (kind, run_id),
                )
        if stale:
            log.info("pruned %d stale %s index row(s)", len(stale), kind)
        return len(stale)
    except Exception as exc:  # noqa: BLE001 - reconcile is best-effort
        log.warning("postgres prune for %s failed: %s", kind, exc)
        return 0


def sync_filesystem_to_index(api_runs_dir: Path, settings: Settings) -> int:
    """Reconcile the index with the filesystem: backfill present runs, prune gone ones.

    Called once at startup. Idempotent via the ON CONFLICT upsert. Returns the
    number of runs indexed (0 when the DB is disabled/unreachable).
    """
    database = get_database(settings)
    if database is None:
        return 0
    indexed = 0
    for kind, dirname in KIND_DIRS.items():
        root = api_runs_dir / dirname
        present = _fs_metadatas(root)
        present_ids = {str(m.get("run_id")) for m in present if m.get("run_id")}
        # _fs_metadatas is newest-first; insert oldest-first so indexed_at
        # increases with run recency and ties order newest-first on read.
        for metadata in reversed(present):
            run_dir = root / str(metadata.get("run_id", ""))
            index_run(kind, metadata, run_dir, settings)
            indexed += 1
        _prune_missing(kind, present_ids, settings)
    if indexed:
        log.info("backfilled %d run(s) into the postgres index", indexed)
    return indexed
