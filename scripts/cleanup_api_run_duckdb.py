from __future__ import annotations

import argparse
import json
from pathlib import Path

DUCKDB_RUN_SUFFIXES = (".duckdb", ".duckdb.wal", ".duckdb.tmp")


def _is_duckdb_run_copy(path: Path) -> bool:
    return path.is_file() and path.name.endswith(DUCKDB_RUN_SUFFIXES)


def find_duckdb_run_copies(api_runs_dir: Path) -> list[Path]:
    if not api_runs_dir.exists():
        return []
    return sorted(path for path in api_runs_dir.rglob("*") if _is_duckdb_run_copy(path))


def cleanup_duckdb_run_copies(*, api_runs_dir: Path, apply: bool) -> dict:
    api_runs_dir = api_runs_dir.resolve()
    if api_runs_dir.name != "api_runs":
        raise ValueError("--api-runs-dir must point at an api_runs directory")
    candidates = find_duckdb_run_copies(api_runs_dir)
    total_bytes = sum(path.stat().st_size for path in candidates)

    deleted_count = 0
    if apply:
        for path in candidates:
            path.unlink()
            deleted_count += 1

    return {
        "api_runs_dir": str(api_runs_dir),
        "mode": "apply" if apply else "dry_run",
        "candidate_count": len(candidates),
        "deleted_count": deleted_count,
        "total_bytes": total_bytes,
        "files": [path.relative_to(api_runs_dir).as_posix() for path in candidates],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report or delete historical DuckDB copies under data/api_runs. "
            "Dry-run is the default; pass --apply to delete candidates."
        )
    )
    parser.add_argument("--api-runs-dir", type=Path, default=Path("data/api_runs"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        result = cleanup_duckdb_run_copies(
            api_runs_dir=args.api_runs_dir,
            apply=args.apply,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        action = "Deleted" if args.apply else "Found"
        print(
            f"{action} {result['deleted_count'] if args.apply else result['candidate_count']} "
            f"DuckDB run-copy files ({result['total_bytes']} bytes)."
        )
        if not args.apply:
            print("Dry-run only. Re-run with --apply to delete these files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
