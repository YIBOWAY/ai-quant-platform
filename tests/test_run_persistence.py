from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.schemas.common import RunStatus, read_json, write_json_atomic
from quant_system.api.server import create_app
from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.storage import runs_repository as rr


def _disabled_db_settings() -> Settings:
    # Explicit init kwargs override any QS_DATABASE_* values from the local .env.
    return Settings(database=DatabaseSettings(enabled=False, url=None))


# --- write_json_atomic ------------------------------------------------------


def test_write_json_atomic_creates_parents_and_writes_payload(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "metadata.json"

    returned = write_json_atomic(target, {"b": 2, "a": 1})

    assert returned == target
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "b": 2}
    # Pretty + deterministic (sorted keys) so artifacts diff cleanly.
    assert target.read_text(encoding="utf-8").startswith("{\n")
    first_key = target.read_text(encoding="utf-8").split("\n")[1]
    assert first_key.strip().startswith('"a"')


def test_write_json_atomic_overwrites_and_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "metadata.json"
    write_json_atomic(target, {"version": 1})
    write_json_atomic(target, {"version": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 2}
    # The temp file must have been renamed away, never left behind.
    assert list(tmp_path.glob("*.tmp")) == []
    assert [p.name for p in tmp_path.iterdir()] == ["metadata.json"]


def test_write_json_atomic_never_observes_partial_file(tmp_path: Path) -> None:
    """A reader either sees the previous payload or the next, never a half-write."""
    target = tmp_path / "metadata.json"
    write_json_atomic(target, {"n": 0})

    def writer(value: int) -> None:
        write_json_atomic(target, {"n": value, "blob": "x" * 5000})

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(writer, range(40)))

    # Whatever interleaving occurred, the final file must be complete valid JSON
    # and no temp files may linger.
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["blob"] == "x" * 5000
    assert isinstance(payload["n"], int)
    assert list(tmp_path.glob("*.tmp")) == []


# --- persist_run ------------------------------------------------------------


def test_persist_run_stamps_unified_core_fields(tmp_path: Path) -> None:
    settings = _disabled_db_settings()
    run_dir = tmp_path / "backtests" / "backtest-20260601T010203Z-abcd1234"
    payload = {"source": "sample", "metrics": {"sharpe": 1.0}}

    metadata = rr.persist_run(run_dir, "backtest", payload, settings=settings)

    assert metadata["run_id"] == "backtest-20260601T010203Z-abcd1234"
    assert metadata["kind"] == "backtest"
    assert metadata["status"] == RunStatus.COMPLETED.value
    # created_at is derived from the run_id timestamp.
    assert metadata["created_at"].startswith("2026-06-01T01:02:03")
    # Original kind-specific fields are preserved.
    assert metadata["source"] == "sample"
    assert metadata["metrics"] == {"sharpe": 1.0}

    on_disk = read_json(run_dir / "metadata.json")
    assert on_disk == metadata


def test_persist_run_does_not_mutate_caller_payload(tmp_path: Path) -> None:
    settings = _disabled_db_settings()
    run_dir = tmp_path / "factors" / "factor-20260601T010203Z-feedbeef"
    payload = {"source": "futu"}

    rr.persist_run(run_dir, "factor", payload, settings=settings)

    # The caller's dict must be left untouched (no injected core fields).
    assert payload == {"source": "futu"}


def test_persist_run_defaults_run_id_to_directory_name(tmp_path: Path) -> None:
    settings = _disabled_db_settings()
    run_dir = tmp_path / "paper" / "paper-no-stamp-here"

    metadata = rr.persist_run(run_dir, "paper", {"source": "sample"}, settings=settings)

    assert metadata["run_id"] == "paper-no-stamp-here"
    # No timestamp in the id -> created_at falls back to a real ISO "now".
    assert metadata["created_at"].endswith("+00:00")


def test_persist_run_accepts_explicit_status_and_index_off(tmp_path: Path) -> None:
    settings = _disabled_db_settings()
    run_dir = tmp_path / "experiments" / "exp-20260601T010203Z-cafef00d"

    metadata = rr.persist_run(
        run_dir,
        "experiment",
        {"source": "sample"},
        settings=settings,
        status=RunStatus.FAILED,
        index=False,
    )

    assert metadata["kind"] == "experiment"
    assert metadata["status"] == RunStatus.FAILED.value
    assert (run_dir / "metadata.json").exists()


def test_persist_run_is_atomic_no_temp_leftovers(tmp_path: Path) -> None:
    settings = _disabled_db_settings()
    run_dir = tmp_path / "backtests" / "backtest-20260601T010203Z-abcd1234"

    rr.persist_run(run_dir, "backtest", {"source": "sample"}, settings=settings)

    assert list(run_dir.glob("*.tmp")) == []
    assert [p.name for p in run_dir.iterdir()] == ["metadata.json"]


# --- replication in the recent-runs aggregation -----------------------------


def _write_metadata(api_runs: Path, dirname: str, run_id: str, metadata: dict) -> None:
    run_dir = api_runs / dirname / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps({"run_id": run_id, **metadata}, sort_keys=True),
        encoding="utf-8",
    )


def test_replication_is_indexed_kind() -> None:
    assert rr.KIND_DIRS["replication"] == "replications"
    assert "replication" in rr.INDEXED_KINDS


def test_recent_runs_includes_replication_runs(tmp_path: Path) -> None:
    api_runs = tmp_path / "api_runs"
    _write_metadata(
        api_runs,
        "backtests",
        "backtest-20260601T010000Z-aaaaaaaa",
        {"source": "tiingo", "kind": "backtest", "metrics": {"sharpe": 1.2}},
    )
    replication_run_id = "replication-20260605T010000Z-rrrrrrrr"
    _write_metadata(
        api_runs,
        "replications",
        replication_run_id,
        {"source": "sample", "kind": "replication", "result_type": "replication"},
    )
    (api_runs / "replications" / replication_run_id / "result.json").write_text(
        json.dumps({"run_id": replication_run_id}),
        encoding="utf-8",
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/runs/recent?limit=10")

    assert response.status_code == 200
    payload = response.json()
    by_kind = {item["kind"]: item for item in payload["runs"]}
    assert "replication" in by_kind
    # Newest first: the replication run is more recent than the backtest run.
    assert payload["runs"][0]["kind"] == "replication"
    assert by_kind["replication"]["run_id"] == "replication-20260605T010000Z-rrrrrrrr"
    assert by_kind["replication"]["source"] == "sample"


def test_replication_run_persists_unified_kind_and_appears_in_recent(tmp_path: Path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    run_response = client.post(
        "/api/replications/reversal-momentum/run",
        json={
            "symbols": ["SPY", "QQQ", "IWM", "DIA"],
            "start": "2023-01-01",
            "end": "2025-12-31",
            "provider": "sample",
            "top_n": 1,
            "initial_cash": 1.0,
        },
    )
    assert run_response.status_code == 200
    body = run_response.json()
    run_id = body["run_id"]
    # The run response now carries the unified core fields.
    assert body["kind"] == "replication"
    assert body["status"] == "completed"
    assert body["created_at"]

    # metadata.json on disk carries the unified kind alongside result_type.
    metadata_path = tmp_path / "api_runs" / "replications" / run_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["kind"] == "replication"
    assert metadata["result_type"] == "replication"
    assert metadata["status"] == "completed"
    assert metadata["created_at"] == body["created_at"]
    # No temp files leaked from the atomic writes.
    run_dir = metadata_path.parent
    assert list(run_dir.glob("*.tmp")) == []

    recent = client.get("/api/runs/recent?limit=10").json()
    assert run_id in {item["run_id"] for item in recent["runs"]}
