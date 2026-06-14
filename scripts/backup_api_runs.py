from __future__ import annotations

import argparse
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

EXCLUDED_PATTERNS = [
    "*.duckdb",
    "*.duckdb.wal",
    "*.duckdb.tmp",
    "*.lock",
    ".env",
    ".env.*",
]


def _should_exclude(path: Path) -> bool:
    name = path.name
    return any(path.match(pattern) or name == pattern for pattern in EXCLUDED_PATTERNS)


def _iter_backup_files(api_runs_dir: Path) -> list[Path]:
    if not api_runs_dir.exists():
        return []
    return sorted(
        path
        for path in api_runs_dir.rglob("*")
        if path.is_file() and not _should_exclude(path)
    )


def create_backup(*, data_dir: Path, output_dir: Path, label: str | None = None) -> dict:
    data_dir = data_dir.resolve()
    api_runs_dir = data_dir / "api_runs"
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_label = f"{label.strip()}-" if label and label.strip() else ""
    archive_path = output_dir / f"api_runs-backup-{safe_label}{stamp}.zip"

    files = _iter_backup_files(api_runs_dir)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "data_dir": str(data_dir),
        "included_root": "api_runs",
        "file_count": len(files),
        "excluded_patterns": EXCLUDED_PATTERNS,
        "files": [path.relative_to(data_dir).as_posix() for path in files],
    }

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        for path in files:
            archive.write(path, path.relative_to(data_dir).as_posix())

    return {
        "archive_path": str(archive_path),
        "file_count": len(files),
        "included_root": "api_runs",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a zip backup of data/api_runs research and paper-account artifacts."
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--label", default=None)
    args = parser.parse_args()

    output_dir = args.output_dir or args.data_dir / "backups"
    result = create_backup(data_dir=args.data_dir, output_dir=output_dir, label=args.label)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
