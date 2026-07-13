from __future__ import annotations

import os
from pathlib import Path

PLATFORM_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AGENT_OUTPUT_DIR = PLATFORM_REPO_ROOT / "data" / "agent_run"
DEFAULT_LEGACY_CANDIDATES_DIR = PLATFORM_REPO_ROOT / "data" / "agent" / "candidates"


def _repo_anchored_absolute(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    anchored = path if path.is_absolute() else PLATFORM_REPO_ROOT / path
    # abspath/normpath is lexical; unlike Path.resolve(), it does not follow a
    # symlink that the dirfd filesystem boundary must detect and reject.
    return Path(os.path.abspath(os.fspath(anchored)))


def resolve_agent_output_dir(explicit: str | Path | None = None) -> Path:
    raw = explicit if explicit is not None else os.environ.get("QS_AGENT_OUTPUT_DIR")
    if raw is None:
        return DEFAULT_AGENT_OUTPUT_DIR
    return _repo_anchored_absolute(raw)


def resolve_legacy_candidates_dir(explicit: str | Path | None = None) -> Path:
    if explicit is None:
        return DEFAULT_LEGACY_CANDIDATES_DIR
    return _repo_anchored_absolute(explicit)


def resolve_candidates_dir(agent_output_dir: str | Path) -> Path:
    return Path(agent_output_dir) / "agent" / "candidates"
