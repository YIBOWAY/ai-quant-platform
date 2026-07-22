"""V7g-A-M1: project hermetic Vertical A Task/Attempt/Run onto workspace spine.

Promotes L5b empty task/attempt/run slots when the hermetic vertical binder has
rows. Empty remains honest. Never invents rows from ordinary conversation
commands. Health ready when projector mounted.

Also provides VerticalObserveJournal so L4b follow/SSE can fingerprint-gate
Task/Attempt/Run id list emissions (event: vertical) without inventing rows.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from quant_system.hermes.vertical_binding_authority import (
    VerticalBindingAuthority,
    default_vertical_binding_authority,
)


def project_workspace_tasks(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    auth = authority or default_vertical_binding_authority()
    return [r.to_public_dict() for r in auth.list_tasks(workspace_id, limit=limit)]


def project_workspace_attempts(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    auth = authority or default_vertical_binding_authority()
    return [r.to_public_dict() for r in auth.list_attempts(workspace_id, limit=limit)]


def project_workspace_runs(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    auth = authority or default_vertical_binding_authority()
    return [r.to_public_dict() for r in auth.list_runs(workspace_id, limit=limit)]


def task_ids_for_spine(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[str]:
    """Id-only projection for WorkspaceSnapshot.tasks: tuple[str, ...]."""
    return [
        str(r["task_id"])
        for r in project_workspace_tasks(
            workspace_id, authority=authority, limit=limit
        )
        if r.get("task_id")
    ]


def attempt_ids_for_spine(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[str]:
    return [
        str(r["attempt_id"])
        for r in project_workspace_attempts(
            workspace_id, authority=authority, limit=limit
        )
        if r.get("attempt_id")
    ]


def run_ids_for_spine(
    workspace_id: str,
    *,
    authority: VerticalBindingAuthority | None = None,
    limit: int = 50,
) -> list[str]:
    return [
        str(r["run_id"])
        for r in project_workspace_runs(
            workspace_id, authority=authority, limit=limit
        )
        if r.get("run_id")
    ]


def vertical_authority_health() -> dict[str, str]:
    """Hermetic vertical Task/Attempt/Run projector mounted; empty honest."""
    return {
        "task": "ready",
        "attempt": "ready",
        "run": "ready",
    }


class VerticalObserveJournal:
    """Fingerprint Task/Attempt/Run id lists so SSE only emits on change."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._last_fp: dict[str, str] = {}

    def reset(self) -> None:
        with self._lock:
            self._last_fp.clear()

    @staticmethod
    def ids_fingerprint(tasks: list[str], attempts: list[str], runs: list[str]) -> str:
        return (
            "t:"
            + ",".join(tasks)
            + "|a:"
            + ",".join(attempts)
            + "|r:"
            + ",".join(runs)
        )

    def take_vertical_ids_if_changed(
        self,
        workspace_id: str,
        tasks: list[str],
        attempts: list[str],
        runs: list[str],
    ) -> dict[str, list[str]] | None:
        fp = self.ids_fingerprint(tasks, attempts, runs)
        with self._lock:
            prior = self._last_fp.get(workspace_id)
            if prior == fp:
                return None
            self._last_fp[workspace_id] = fp
            return {
                "tasks": list(tasks),
                "attempts": list(attempts),
                "runs": list(runs),
            }


_DEFAULT_VERTICAL_JOURNAL = VerticalObserveJournal()


def default_vertical_observe_journal() -> VerticalObserveJournal:
    return _DEFAULT_VERTICAL_JOURNAL


def reset_default_vertical_observe_journal() -> None:
    _DEFAULT_VERTICAL_JOURNAL.reset()


__all__ = [
    "VerticalObserveJournal",
    "attempt_ids_for_spine",
    "default_vertical_observe_journal",
    "project_workspace_attempts",
    "project_workspace_runs",
    "project_workspace_tasks",
    "reset_default_vertical_observe_journal",
    "run_ids_for_spine",
    "task_ids_for_spine",
    "vertical_authority_health",
]
